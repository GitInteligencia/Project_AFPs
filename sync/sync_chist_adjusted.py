"""
Sync del detalle de cartera CON desfase (por AFP, pre-clasificado) SQL Server -> BigQuery:
  Inteligencia_Mercado.dbo.AFP_CL_CHIST_ADJUSTED  ->  chist_adjusted

Unico nivel con detalle por-AFP x instrumento. `supracategory` ya viene clasificada;
`tipo_valor` = Valorizacion (NAV) / Remanente (uncalled, solo bajo Fondos).

Ventana 2025+ y EXCLUSION de buckets (free tier): Direct Inv. RF Nacional, Derivados
Nacional/Extranjero, Disponible Nacional -> sus totales salen de sd_asset_class_*.
Columnas forward/swap no se traen. Idempotente: DELETE por fecha en el pull + INSERT.
Destino BigQuery (afp_raw) via sync/bq_io.py con ADC (antes: Supabase REST); al final
reconstruye los marts de Alternatives (antes: RPC refresh_alternatives_matviews()).

Requiere que la tabla destino exista (ver chist_adjusted_schema.sql).

VENTANA AUTO-ANCLADA A LA FUENTE (2026-07-09): CHIST llega con ~4 meses de
rezago, asi que una ventana relativa a "hoy" (como la de los demas syncs)
puede quedar POR DELANTE del ultimo dato y cargar 0 filas. Sin --start, este
script ancla la ventana al MAX(fecha) de la propia fuente: re-sincroniza los
ultimos 3 meses PUBLICADOS (mes nuevo + correcciones retroactivas de la SPE).
Asi main.py puede correrlo siempre: si no hay mes nuevo re-copia lo mismo
(idempotente); si aparece, lo toma solo.

Uso:
    python sync/sync_chist_adjusted.py                 # ventana auto (3 meses publicados)
    python sync/sync_chist_adjusted.py --start 2026-01-01
    python sync/sync_chist_adjusted.py --dry-run
"""
import os
import sys
import argparse

from dotenv import load_dotenv
from sqlalchemy import text

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sync_sqlserver_to_supabase import (  # noqa: E402
    connect_sqlserver,
    connect_supabase,
    supabase_insert,
    supabase_delete_in,
    timed_read,
)
from bq_io import ALTERNATIVES_MARTS, bq_count, refresh_marts  # noqa: E402

load_dotenv()

SRC_TABLE = 'AFP_CL_CHIST_ADJUSTED'
DST_TABLE = 'chist_adjusted'
WINDOW = '2025-01-01'
EXCLUDE = (
    "'Direct Inv. RF Nacional', 'Derivados Nacional', "
    "'Derivados Extranjero', 'Disponible Nacional'"
)


def build_query(start):
    return f"""
        SELECT CAST(FechaReporte AS DATE)        AS fecha_reporte,
               CAST(fecha AS DATE)               AS fecha,
               afp                               AS afp,
               tipo_de_fondo                     AS tipo_de_fondo,
               tipo_de_instrumento               AS tipo_de_instrumento,
               nemotecnico_del_instrumento       AS nemotecnico,
               nombre_del_emisor                 AS nombre_del_emisor,
               nacionalidad_del_emisor           AS nacionalidad_del_emisor,
               unidades                          AS unidades,
               precio                            AS precio,
               inversion                         AS inversion,
               Supracategory                     AS supracategory,
               [Type]                            AS tipo_valor
        FROM Inteligencia_Mercado.dbo.{SRC_TABLE}
        WHERE fecha >= '{start}'
          AND Supracategory NOT IN ({EXCLUDE})
    """


def resolve_start(eng, arg_start):
    """--start explicito manda; si no, ventana anclada al MAX(fecha) de la
    fuente: primer dia del mes, 2 meses antes -> re-sync de los ultimos 3
    meses publicados (cubre mes nuevo + correcciones retroactivas)."""
    if arg_start:
        return arg_start
    with eng.connect() as conn:
        max_f = conn.execute(
            text(f"SELECT MAX(CAST(fecha AS DATE)) FROM Inteligencia_Mercado.dbo.{SRC_TABLE}")
        ).scalar()
    if max_f is None:
        return WINDOW
    # pyodbc puede devolver DATE como str segun driver/version
    if isinstance(max_f, str):
        from datetime import date
        max_f = date.fromisoformat(max_f[:10])
    y, m = max_f.year, max_f.month - 2
    if m <= 0:
        y, m = y - 1, m + 12
    start = f"{y:04d}-{m:02d}-01"
    print(f"      ventana auto: MAX(fecha) fuente = {max_f} -> start {start} (3 meses publicados)")
    return start


def main():
    ap = argparse.ArgumentParser(description="Sync AFP_CL_CHIST_ADJUSTED -> BigQuery chist_adjusted")
    ap.add_argument('--start', default=None,
                    help='Inicio YYYY-MM-DD por fecha (default: auto, ultimos 3 meses publicados en la fuente)')
    ap.add_argument('--dry-run', action='store_true', help='Solo lee de SQL y reporta; no escribe en BigQuery')
    args = ap.parse_args()

    eng = connect_sqlserver()
    start = resolve_start(eng, args.start)
    print(f"\n[chist_adjusted] {DST_TABLE} <- {SRC_TABLE}  [fecha >= {start}, sin derivados/RF-nac/disp-nac]")
    df = timed_read(DST_TABLE, eng, build_query(start))
    if df.empty:
        print("      -> 0 filas (nada en el rango)")
        return

    fechas = sorted(df['fecha'].unique().tolist())
    print(f"      leidas {len(df):,} filas en {len(fechas)} fechas [{fechas[0]} .. {fechas[-1]}]")
    print("      Supracategory: " + ", ".join(f"{k}={v}" for k, v in df['supracategory'].value_counts().items()))
    print("      tipo_valor:    " + ", ".join(f"{k}={v}" for k, v in df['tipo_valor'].value_counts().items()))

    if args.dry_run:
        print("      DRY-RUN: no se escribe nada en BigQuery.")
        return

    sb = connect_supabase()
    deleted = supabase_delete_in(sb, DST_TABLE, 'fecha', fechas)
    print(f"      ({deleted:,} filas borradas en {len(fechas)} fechas previas)")
    n = supabase_insert(sb, DST_TABLE, df, batch_size=500, show_progress=True)
    print(f"      -> {n:,} filas insertadas")

    got = bq_count(sb, DST_TABLE)
    print(f"      verificacion: {got:,} filas en BigQuery (esperado >= {len(df):,})")

    # chist_adjusted feeds mv_chist_aa (snapshot behind v_total/v_nav/v_uncalled/...).
    # Refresh it so the dashboard doesn't read stale alternatives after this sync.
    # En BigQuery los mv_* son tablas reconstruidas desde db/bigquery/marts/*.sql.
    print(f"      reconstruyendo marts del dashboard ({', '.join(ALTERNATIVES_MARTS)})...")
    done = refresh_marts(sb, ALTERNATIVES_MARTS)
    print(f"      -> marts reconstruidos: {', '.join(done)}")
    print("\n=== DONE ===")


if __name__ == '__main__':
    main()
