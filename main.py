"""
Orquestador mensual del pipeline de datos del dashboard: SQL Server -> BigQuery.

DESTINO (2026-09, migracion GCP): BigQuery, proyecto pat-uat-global
(datasets afp_raw / afp_dim; marts mv_* en afp_mart; ver PLAN_MIGRACION_GCP.md).
Antes el destino era Supabase; los scripts conservan su nombre de archivo y su
logica de lectura/ventanas, solo cambio la capa de escritura (sync/bq_io.py).

DONDE CORRE: como Cloud Run Job (imagen sync/Dockerfile, disparada por Cloud
Scheduler o por el workflow run-sync.yml) o en cualquier maquina con acceso al
SQL Server y credenciales ADC de GCP (gcloud auth application-default login).
Nunca llaves JSON. `python main.py --list` no necesita GCP.

OBSERVABILIDAD: cada paso escribe una fila en afp_ops.run_log (inicio, fin, rc)
via bq_io.log_run; si no hay credenciales ADC se avisa y se sigue. Al final, si
WEB_URL y REVALIDATE_TOKEN estan definidos, se hace POST {WEB_URL}/api/revalidate
(header x-revalidate-token) para invalidar el cache de la web; error no fatal.

Los scrapers de spensiones.cl quedaron RETIRADOS (2026-07): las tablas fuente
en SQL Server las mantiene el equipo con sus propios procesos. Este script
solo espeja SQL Server -> BigQuery, y es UN solo comando:

    python main.py

Cada paso toma lo que haya en su tabla fuente; si una fuente aun no tiene el
mes nuevo, el paso simplemente re-sincroniza lo ya cargado (todo es
idempotente: DELETE por fecha + INSERT, o UPSERT). Por eso da lo mismo correr
antes o despues de que llegue cada fuente — la corrida siguiente recoge lo que
falto. En particular CHIST llega con ~4 meses de rezago: su paso ancla la
ventana al MAX(fecha) de la propia fuente (ultimos 3 meses publicados), asi
que apenas el equipo cargue el mes nuevo en SQL, la siguiente corrida lo toma.

  paso             fuente SQL Server                   destino BigQuery
  ---------------  ----------------------------------  -----------------------
  cotizantes       AFP_CL_Cotizantes                   cotizantes_afp
  core             dims + FX + VC_PAT                  dim_* / tipo_cambio /
                                                       valores_cuota_patrimonio
                                                       (+ rebuild marts mv_*)
  sd_asset_class   AFP_CL_01_sd / 02_sd                sd_asset_class_*
  consolidated_sd  AFP_CL_09_17_25_sd_consolidated     consolidated_sd
  chist_adjusted   AFP_CL_CHIST_ADJUSTED               chist_adjusted (ventana
                                                       auto-anclada a la fuente;
                                                       + rebuild marts mv_*)
  bbg_returns      AFP_CL_BBG_Returns                  bbg_returns
  dim_bd_previa    DIM_BD_Previa_AFPCL                 dim_bd_previa
  ipd_strategy     TBL_IPA_V2                          ipd_* (full reload, lo
                                                       mas lento; omitible con
                                                       --skip-strategy)

VENTANA: los pasos marcados [--start] re-sincronizan desde el primer dia del
mes, 3 meses hacia atras (default), para absorber correcciones retroactivas
de la SPE. chist_adjusted calcula su propia ventana (ver arriba) salvo que se
pase --start explicito.

Uso:
    python main.py                     # la corrida mensual completa
    python main.py --list              # muestra el plan y sale, no ejecuta nada
    python main.py --skip-strategy     # sin ipd_strategy (mas rapida)
    python main.py --months-back 6     # ventana mas ancha
    python main.py --start 2025-01-01  # ventana explicita (aplica tambien a CHIST)
    python main.py --only chist_adjusted,bbg_returns
    python main.py --keep-going        # no se detiene en el primer fallo
"""
import argparse
import os
import subprocess
import sys
import time
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SYNC_DIR = ROOT / 'sync'

# .env local (WEB_URL, REVALIDATE_TOKEN, GCP_PROJECT_ID...). En Cloud Run llegan por env.
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
except ImportError:  # dotenv no es imprescindible para --list
    pass


# =============================================================
# RUN LOG (afp_ops.run_log) y REVALIDACION DE LA WEB
# =============================================================

def connect_run_log():
    """Cliente BigQuery para afp_ops.run_log. Si no hay credenciales ADC (o no
    esta instalada la libreria) devuelve None con un aviso: el pipeline sigue."""
    try:
        sys.path.insert(0, str(SYNC_DIR))
        import bq_io
        client = bq_io.connect_bigquery()
        return client
    except Exception as e:
        print(f'[warn] run_log deshabilitado (sin BigQuery/ADC): {type(e).__name__}: {e}')
        return None


def write_run_log(client, run_id, name, started, finished, rc, extra=None):
    """Una fila por paso; cualquier error se reporta y no interrumpe."""
    if client is None:
        return
    try:
        import bq_io
        bq_io.log_run(client, name, started, finished, rc,
                      extra={'run_id': run_id, **(extra or {})})
    except Exception as e:
        print(f'[warn] run_log no escrito para [{name}]: {e}')


def revalidate_web():
    """POST {WEB_URL}/api/revalidate con x-revalidate-token (D5). No fatal."""
    url, token = os.getenv('WEB_URL'), os.getenv('REVALIDATE_TOKEN')
    if not (url and token):
        return
    endpoint = f"{url.rstrip('/')}/api/revalidate"
    try:
        import requests
        r = requests.post(endpoint, headers={'x-revalidate-token': token}, timeout=30)
        print(f'\nRevalidacion web: POST {endpoint} -> {r.status_code}')
    except Exception as e:
        print(f'\n[warn] revalidacion web fallo ({endpoint}): {e}')


def default_start(months_back: int) -> str:
    """Primer dia del mes, months_back meses hacia atras desde hoy."""
    today = date.today()
    y, m = today.year, today.month - months_back
    while m <= 0:
        y, m = y - 1, m + 12
    return date(y, m, 1).isoformat()


def build_steps(start: str, explicit_start: str):
    """(name, cmd, descripcion) en orden de ejecucion. chist_adjusted no recibe
    --start salvo que el usuario lo haya pasado explicito: sin el, ese sync
    ancla la ventana al MAX(fecha) de su fuente (CHIST rezaga ~4 meses; una
    ventana relativa a hoy quedaria por delante del dato y cargaria 0 filas)."""
    chist_cmd = ['sync_chist_adjusted.py']
    chist_desc = 'AFP_CL_CHIST_ADJUSTED -> chist_adjusted (ventana auto: ultimos 3 meses publicados, + rebuild marts)'
    if explicit_start:
        chist_cmd += ['--start', explicit_start]
        chist_desc = f'AFP_CL_CHIST_ADJUSTED -> chist_adjusted (fecha >= {explicit_start}, + rebuild marts)'
    return [
        ('cotizantes', ['sync_sp_sqlserver_to_supabase.py'],
         'AFP_CL_Cotizantes -> cotizantes_afp (ventana >= 2025-01)'),
        ('core', ['sync_sqlserver_to_supabase.py'],
         'Dims + tipo_cambio + valores_cuota_patrimonio, incremental (+ rebuild marts)'),
        ('sd_asset_class', ['sync_sd_asset_class.py', '--start', start],
         f'AFP_CL_01_sd/02_sd -> sd_asset_class_* (fecha >= {start})'),
        ('consolidated_sd', ['sync_consolidated_sd.py', '--start', start],
         f'AFP_CL_09_17_25_sd_consolidated -> consolidated_sd (fecha >= {start})'),
        ('chist_adjusted', chist_cmd, chist_desc),
        ('bbg_returns', ['sync_bbg_returns.py', '--start', start],
         f'AFP_CL_BBG_Returns -> bbg_returns (end_date >= {start})'),
        ('dim_bd_previa', ['sync_dim_bd_previa.py'],
         'DIM_BD_Previa_AFPCL -> dim_bd_previa (reload completo, dimensional chica)'),
        ('ipd_strategy', ['sync_ipd_strategy.py'],
         'TBL_IPA_V2 -> ipd_* (Strategy 4.1/4.2 + Sec05, full reload)'),
    ]


def main():
    ap = argparse.ArgumentParser(
        description='Orquestador mensual: syncs SQL Server -> BigQuery',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument('--start', default=None,
                    help='Inicio YYYY-MM-DD de la ventana re-sincronizada (default: --months-back)')
    ap.add_argument('--months-back', type=int, default=3,
                    help='Meses hacia atras para la ventana (default 3; no aplica a chist_adjusted)')
    ap.add_argument('--skip-strategy', action='store_true',
                    help='Omite sync_ipd_strategy.py (el paso mas lento)')
    ap.add_argument('--only', default=None,
                    help='Solo estos pasos, separados por coma (ej: chist_adjusted,bbg_returns)')
    ap.add_argument('--keep-going', action='store_true',
                    help='Sigue con los pasos restantes aunque uno falle')
    ap.add_argument('--list', action='store_true',
                    help='Muestra el plan y sale sin ejecutar nada')
    args = ap.parse_args()

    start = args.start or default_start(args.months_back)
    steps = build_steps(start, args.start)

    if args.only:
        wanted = {s.strip() for s in args.only.split(',') if s.strip()}
        known = {name for name, _, _ in steps}
        bad = wanted - known
        if bad:
            ap.error(f"pasos desconocidos: {', '.join(sorted(bad))}. "
                     f"Validos: {', '.join(name for name, _, _ in steps)}")
        steps = [s for s in steps if s[0] in wanted]

    if args.skip_strategy:
        steps = [s for s in steps if s[0] != 'ipd_strategy']

    print('=' * 72)
    print(f'PIPELINE MENSUAL DASHBOARD AFP  |  ventana --start {start}')
    print('=' * 72)
    for i, (name, cmd, desc) in enumerate(steps, 1):
        print(f'  {i}. [{name}] {desc}')
    print('=' * 72)
    if args.list:
        return 0

    # run_id agrupa las filas de esta corrida en afp_ops.run_log; los subprocesos
    # lo reciben por env (AFP_RUN_ID) por si quieren loguear algo propio.
    run_id = os.getenv('AFP_RUN_ID') or datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + uuid.uuid4().hex[:6]
    os.environ['AFP_RUN_ID'] = run_id
    print(f'run_id: {run_id}')
    log_client = connect_run_log()

    results = []   # (name, status, seconds)
    failed = False
    for name, cmd, _desc in steps:
        if failed and not args.keep_going:
            results.append((name, 'SKIP', 0.0))
            now = datetime.now(timezone.utc)
            write_run_log(log_client, run_id, name, now, now, None, {'status': 'SKIP'})
            continue
        full_cmd = [sys.executable, str(SYNC_DIR / cmd[0]), *cmd[1:]]
        print(f'\n>>> [{name}] {" ".join(full_cmd[1:])}')
        t0 = time.time()
        rc = subprocess.run(full_cmd, cwd=ROOT).returncode
        dt = time.time() - t0
        status = 'OK' if rc == 0 else f'FAIL (rc={rc})'
        results.append((name, status, dt))
        write_run_log(log_client, run_id, name, t0, t0 + dt, rc,
                      {'args': cmd[1:], 'start': start})
        if rc != 0:
            failed = True
            print(f'\n[ERROR] paso [{name}] fallo con codigo {rc}'
                  + ('' if args.keep_going else ' -- se omiten los pasos restantes'))

    print('\n' + '=' * 72)
    print('RESUMEN')
    print('=' * 72)
    for name, status, dt in results:
        line = f'  {name:18s} {status:12s}'
        if status != 'SKIP':
            line += f' {dt:7.1f}s'
        print(line)
    total = sum(dt for _, _, dt in results)
    print(f'  {"TOTAL":18s} {"":12s} {total:7.1f}s')

    # Invalida Data Cache + ISR de la web si al menos un paso escribio algo.
    if any(status == 'OK' for _, status, _ in results):
        revalidate_web()
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
