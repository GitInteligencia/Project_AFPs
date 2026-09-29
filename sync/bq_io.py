"""
Capa de escritura a BigQuery para los scripts de sync (reemplaza a supabase-py).

Contrato (PLAN_MIGRACION_GCP.md §9.2): mismas firmas que los helpers
`supabase_*` de sync_sqlserver_to_supabase.py, para que el cambio en los
scripts sea quirurgico (solo se sustituye la capa de escritura; la lectura de
SQL Server, las ventanas y los calculos en pandas no cambian).

  connect_bigquery()                          <- connect_supabase()
  bq_insert(client, table, df, ...)           <- supabase_insert     (load WRITE_APPEND)
  bq_upsert(client, table, df, on_conflict)   <- supabase_upsert     (staging + MERGE)
  bq_delete_in(client, table, col, values)    <- supabase_delete_in  (DELETE ... IN UNNEST)
  bq_replace(client, table, df)               <- supabase_replace    (load WRITE_TRUNCATE)
  bq_delete_where_gte / bq_delete_where_lt / bq_delete_all
  get_last_date(client, table, col)           <- get_last_date       (SELECT MAX)
  bq_table_stats(client, table, date_col)     <- select(count='exact') + order/limit
  refresh_marts(client, names=None)           <- rpc('refresh_alternatives_matviews')
  log_run(client, step, started, finished, rc, rows=None, extra=None)  (nuevo, afp_ops.run_log)
  resolve_table(table)                        -> `project.dataset.table`

AUTENTICACION: siempre Application Default Credentials (ADC). En Cloud Run Job
es la service account del job; en una maquina local, `gcloud auth
application-default login`. Nunca llaves JSON.

DATASETS (proyecto pat-uat-global, location southamerica-west1):
  afp_raw   tablas espejo de SQL Server         (resto de tablas)
  afp_dim   toda tabla `dim_*`
  afp_mart  vistas v_*, tablas mv_*, table functions (las reconstruye refresh_marts)
  afp_ops   run_log
  afp_stg   staging temporal para MERGE (tablas con sufijo uuid; expiran en 1 dia)

VARIABLES DE ENTORNO (todas con default):
  GCP_PROJECT_ID=pat-uat-global   BQ_LOCATION=southamerica-west1
  BQ_DATASET_RAW=afp_raw  BQ_DATASET_DIM=afp_dim  BQ_DATASET_MART=afp_mart
  BQ_DATASET_OPS=afp_ops  BQ_DATASET_STG=afp_stg
  AFP_MARTS_DIR=<repo>/db/bigquery/marts   (los .sql de los marts + refresh_order.txt)

TIPOS: antes de cargar, `prepare_dataframe` convierte columnas datetime a DATE
(`df[col].dt.date`), NaN/NaT -> NULL y, si la tabla destino ya existe, alinea
los tipos de cada columna al esquema de la tabla (INT64 vs FLOAT64, NUMERIC,
DATE desde strings, BOOL desde 0/1) para que pandas/pyarrow no infieran un
tipo distinto al de la tabla y el load falle.
"""

import json
import os
import socket
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from string import Template

import numpy as np
import pandas as pd

# La importacion de google-cloud-bigquery se hace perezosa en connect_bigquery()
# para que los helpers puros (resolve_table, build_merge_sql, prepare_dataframe,
# parse_refresh_order) sean usables/testeables sin GCP ni la libreria instalada.

# =============================================================
# CONFIGURACION
# =============================================================

PROJECT_ID = os.getenv('GCP_PROJECT_ID', 'pat-uat-global')
LOCATION = os.getenv('BQ_LOCATION', 'southamerica-west1')
DATASET_RAW = os.getenv('BQ_DATASET_RAW', 'afp_raw')
DATASET_DIM = os.getenv('BQ_DATASET_DIM', 'afp_dim')
DATASET_MART = os.getenv('BQ_DATASET_MART', 'afp_mart')
DATASET_OPS = os.getenv('BQ_DATASET_OPS', 'afp_ops')
DATASET_STG = os.getenv('BQ_DATASET_STG', 'afp_stg')

_REPO_ROOT = Path(__file__).resolve().parents[1]
MARTS_DIR = Path(os.getenv('AFP_MARTS_DIR', str(_REPO_ROOT / 'db' / 'bigquery' / 'marts')))
REFRESH_ORDER_FILE = 'refresh_order.txt'

# Override puntual tabla -> dataset (gana sobre la regla dim_* / resto).
# Ejemplo: ALT_DATASETS['mi_tabla'] = 'afp_mart'
ALT_DATASETS: dict[str, str] = {}

# Marts que hoy refresca refresh_alternatives_matviews() en Supabase
# (sync/mv_alternatives_materialize.sql + sync/mv_strategy_afp_ow_uw.sql).
ALTERNATIVES_MARTS = ['mv_chist_aa', 'mv_aum', 'mv_strategy_afp_ow_uw']

RUN_LOG_TABLE = 'run_log'
# Staging: las tablas expiran solas aunque el drop final falle.
STAGING_TTL = timedelta(days=1)


# =============================================================
# RESOLUCION DE NOMBRES
# =============================================================

def dataset_for(table: str) -> str:
    """Dataset por convencion: dim_* -> afp_dim; resto -> afp_raw. ALT_DATASETS manda."""
    if table in ALT_DATASETS:
        return ALT_DATASETS[table]
    return DATASET_DIM if table.startswith('dim_') else DATASET_RAW


def resolve_table(table: str) -> str:
    """'tabla' -> 'project.dataset.tabla'. Acepta tambien 'dataset.tabla' (se
    antepone el proyecto) y 'project.dataset.tabla' (se devuelve tal cual)."""
    parts = table.split('.')
    if len(parts) == 3:
        return table
    if len(parts) == 2:
        return f'{PROJECT_ID}.{table}'
    return f'{PROJECT_ID}.{dataset_for(table)}.{table}'


def _q(fq_table: str) -> str:
    """Nombre calificado entre backticks para SQL."""
    return f'`{fq_table}`'


# =============================================================
# CONEXION
# =============================================================

def connect_bigquery():
    """bigquery.Client con ADC. Falla temprano (y claro) si no hay credenciales."""
    from google.cloud import bigquery
    client = bigquery.Client(project=PROJECT_ID, location=LOCATION)
    print(f"      bigquery: project={PROJECT_ID} location={LOCATION}")
    return client


# =============================================================
# PREPARACION DE DATAFRAMES
# =============================================================

def _nan_to_none(s: pd.Series) -> pd.Series:
    """Serie a dtype object con None en los faltantes (NaN/NaT/pd.NA -> None)."""
    return s.astype(object).where(s.notna(), None)


def _to_date_series(s: pd.Series) -> pd.Series:
    """Cualquier serie de fechas (datetime64, strings ISO, date) -> objetos date, None si falta."""
    if pd.api.types.is_datetime64_any_dtype(s):
        out = s.dt.date
    else:
        out = pd.to_datetime(s, errors='coerce').dt.date
    return _nan_to_none(out)


def _to_decimal_series(s: pd.Series, scale: int) -> pd.Series:
    """Float/int -> Decimal cuantizado a `scale` decimales (NUMERIC(38,9) por defecto).
    pyarrow convierte Decimal -> decimal128 sin ambiguedad; con floats fallaria."""
    quantum = Decimal(1).scaleb(-scale)

    def conv(v):
        if v is None:
            return None
        try:
            if pd.isna(v):
                return None
        except (TypeError, ValueError):
            pass
        if isinstance(v, Decimal):
            return v.quantize(quantum)
        return Decimal(str(v)).quantize(quantum)

    return s.astype(object).map(conv)


def _align_column(s: pd.Series, field) -> pd.Series:
    """Alinea una columna al tipo del campo BigQuery destino."""
    t = (field.field_type or '').upper()
    if t in ('INTEGER', 'INT64'):
        if pd.api.types.is_bool_dtype(s):
            return s.astype('Int64')
        return pd.to_numeric(s, errors='coerce').astype('Int64')
    if t in ('FLOAT', 'FLOAT64'):
        return pd.to_numeric(s, errors='coerce').astype('float64')
    if t == 'NUMERIC':
        return _to_decimal_series(s, field.scale if field.scale is not None else 9)
    if t == 'BIGNUMERIC':
        return _to_decimal_series(s, field.scale if field.scale is not None else 38)
    if t == 'DATE':
        return _to_date_series(s)
    if t in ('DATETIME', 'TIMESTAMP'):
        out = s if pd.api.types.is_datetime64_any_dtype(s) else pd.to_datetime(s, errors='coerce')
        if t == 'TIMESTAMP' and out.dt.tz is None:
            out = out.dt.tz_localize('UTC')
        return out
    if t in ('BOOLEAN', 'BOOL'):
        if pd.api.types.is_bool_dtype(s):
            return s.astype('boolean')
        return _nan_to_none(s).map(lambda v: None if v is None else bool(v)).astype('boolean')
    if t == 'STRING':
        # _nan_to_none al final: pandas>=3 re-infiere dtype `str` tras el map y
        # volveria a guardar None como NaN.
        return _nan_to_none(_nan_to_none(s).map(lambda v: None if v is None else str(v)))
    # Tipos no contemplados (BYTES, GEOGRAPHY, STRUCT...): se deja tal cual.
    return s


def prepare_dataframe(df: pd.DataFrame, schema=None) -> pd.DataFrame:
    """Copia del df lista para load_table_from_dataframe.

    - Con `schema` (lista de SchemaField de la tabla destino): cada columna
      presente en la tabla se alinea a su tipo (ver _align_column).
    - Sin schema, o para columnas que no estan en la tabla: datetime -> DATE
      (`.dt.date`), NaN/NaT en columnas object/str -> None. Los NaN de columnas
      float quedan como NaN (pyarrow los escribe como NULL en parquet).
    Los nombres de columna se conservan.
    """
    out = df.copy()
    by_name = {f.name: f for f in (schema or [])}
    for col in out.columns:
        s = out[col]
        if col in by_name:
            out[col] = _align_column(s, by_name[col])
        elif pd.api.types.is_datetime64_any_dtype(s):
            out[col] = _to_date_series(s)
        elif s.dtype == object or pd.api.types.is_string_dtype(s):
            out[col] = _nan_to_none(s)
    return out


def _get_table_schema(client, fq_table):
    """Esquema de la tabla destino si existe; None si no existe (se creara al cargar)."""
    from google.api_core.exceptions import NotFound
    try:
        return client.get_table(fq_table).schema
    except NotFound:
        return None


def _load_dataframe(client, fq_table, df, write_disposition, schema=None):
    """load_table_from_dataframe via parquet. Espera el job y propaga errores."""
    from google.cloud import bigquery
    df_ready = prepare_dataframe(df, schema)
    job_config = bigquery.LoadJobConfig(
        write_disposition=write_disposition,
        source_format=bigquery.SourceFormat.PARQUET,
    )
    if schema:
        # Solo los campos que vienen en el df; el resto lo infiere la libreria.
        job_config.schema = [f for f in schema if f.name in df_ready.columns]
    job = client.load_table_from_dataframe(df_ready, fq_table, job_config=job_config)
    job.result()
    return len(df_ready)


# =============================================================
# ESCRITURA
# =============================================================

def bq_insert(client, table, df, batch_size=None, show_progress=False):
    """INSERT (append) de un DataFrame. `batch_size`/`show_progress` se aceptan
    por compatibilidad de firma con supabase_insert y se ignoran: el load job
    va en un solo parquet."""
    if df is None or df.empty:
        print("      -> 0 filas")
        return 0
    fq = resolve_table(table)
    schema = _get_table_schema(client, fq)
    from google.cloud import bigquery
    return _load_dataframe(client, fq, df, bigquery.WriteDisposition.WRITE_APPEND, schema)


def build_merge_sql(dest_fq: str, stg_fq: str, columns: list, keys: list) -> str:
    """MERGE destino USING staging ON claves; UPDATE de todas las columnas no
    clave e INSERT con lista explicita de columnas (equivale a INSERT ROW pero
    tolera que el destino tenga columnas extra, p. ej. con DEFAULT)."""
    missing = [k for k in keys if k not in columns]
    if missing:
        raise ValueError(f"claves {missing} no estan en las columnas del DataFrame {list(columns)}")
    on = ' AND '.join(f'T.`{k}` = S.`{k}`' for k in keys)
    non_key = [c for c in columns if c not in keys]
    cols_sql = ', '.join(f'`{c}`' for c in columns)
    vals_sql = ', '.join(f'S.`{c}`' for c in columns)
    sql = f"MERGE {_q(dest_fq)} T\nUSING {_q(stg_fq)} S\nON {on}\n"
    if non_key:
        set_sql = ', '.join(f'`{c}` = S.`{c}`' for c in non_key)
        sql += f"WHEN MATCHED THEN UPDATE SET {set_sql}\n"
    sql += f"WHEN NOT MATCHED THEN INSERT ({cols_sql}) VALUES ({vals_sql})"
    return sql


def _conflict_list(on_conflict):
    return (
        list(on_conflict) if isinstance(on_conflict, (list, tuple))
        else [c.strip() for c in on_conflict.split(',') if c.strip()]
    )


def bq_upsert(client, table, df, on_conflict, batch_size=None, show_progress=False):
    """UPSERT sobre la(s) clave(s) `on_conflict`: dedupe en pandas (igual que
    hoy: keep='last') -> load a afp_stg.<tabla>_<uuid> -> MERGE -> drop staging.
    Devuelve el numero de filas enviadas (tras dedupe), como supabase_upsert."""
    if df is None or df.empty:
        print("      -> 0 filas (DataFrame vacio)")
        return 0

    conflict_list = _conflict_list(on_conflict)
    pre = len(df)
    df = df.drop_duplicates(subset=conflict_list, keep='last')
    if len(df) < pre:
        print(f"      ({pre - len(df)} duplicados removidos en {conflict_list})")

    from google.cloud import bigquery
    dest_fq = resolve_table(table)
    schema = _get_table_schema(client, dest_fq)
    stg_fq = f"{PROJECT_ID}.{DATASET_STG}.{table}_{uuid.uuid4().hex[:12]}"

    n = _load_dataframe(client, stg_fq, df, bigquery.WriteDisposition.WRITE_TRUNCATE, schema)
    try:
        try:
            stg_tbl = client.get_table(stg_fq)
            stg_tbl.expires = datetime.now(timezone.utc) + STAGING_TTL
            client.update_table(stg_tbl, ['expires'])
        except Exception as e:  # la expiracion es red de seguridad, no bloquea
            print(f"      [warn] no se pudo fijar expiracion del staging: {e}")

        if schema is None:
            # Destino no existia: el MERGE necesita la tabla. La creamos vacia
            # con el esquema del staging (mismo comportamiento que un primer load).
            client.query(
                f"CREATE TABLE IF NOT EXISTS {_q(dest_fq)} AS SELECT * FROM {_q(stg_fq)} WHERE FALSE"
            ).result()

        sql = build_merge_sql(dest_fq, stg_fq, list(df.columns), conflict_list)
        client.query(sql).result()
    finally:
        client.delete_table(stg_fq, not_found_ok=True)
    return n


def bq_replace(client, table, df, pk_col=None):
    """Full reload: load WRITE_TRUNCATE (reemplaza el contenido completo).
    `pk_col` se acepta por compatibilidad con supabase_replace y se ignora.
    Con df vacio, vacia la tabla (equivale al DELETE-all de hoy)."""
    fq = resolve_table(table)
    if df is None or df.empty:
        bq_delete_all(client, table)
        print(f"      -> {table}: 0 filas")
        return 0
    schema = _get_table_schema(client, fq)
    from google.cloud import bigquery
    n = _load_dataframe(client, fq, df, bigquery.WriteDisposition.WRITE_TRUNCATE, schema)
    print(f"      -> {table}: {n:,} filas")
    return n


# =============================================================
# DELETE
# =============================================================

def _is_date_like(v) -> bool:
    if isinstance(v, (datetime, date, pd.Timestamp, np.datetime64)):
        return True
    if isinstance(v, str) and len(v) >= 10:
        try:
            date.fromisoformat(v[:10])
            return True
        except ValueError:
            return False
    return False


def _to_iso_date(v) -> str:
    if isinstance(v, np.datetime64):
        v = pd.Timestamp(v)
    if isinstance(v, (datetime, pd.Timestamp)):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    return str(v)[:10]


def infer_param_type(values) -> tuple[str, list]:
    """(tipo BigQuery, valores normalizados) para un ArrayQueryParameter.
    Fechas (date/datetime/Timestamp/strings ISO) -> DATE; ints -> INT64;
    floats -> FLOAT64; resto -> STRING."""
    vals = list(values)
    if vals and all(_is_date_like(v) for v in vals):
        return 'DATE', [_to_iso_date(v) for v in vals]
    if vals and all(isinstance(v, (int, np.integer)) and not isinstance(v, bool) for v in vals):
        return 'INT64', [int(v) for v in vals]
    if vals and all(isinstance(v, (int, float, np.integer, np.floating)) and not isinstance(v, bool) for v in vals):
        return 'FLOAT64', [float(v) for v in vals]
    return 'STRING', [str(v) for v in vals]


def scalar_param(name, value):
    """ScalarQueryParameter con tipo inferido (DATE para fechas, INT64, FLOAT64, STRING)."""
    from google.cloud import bigquery
    ptype, vals = infer_param_type([value])
    return bigquery.ScalarQueryParameter(name, ptype, vals[0])


def run_dml(client, sql, params=None) -> int:
    """Ejecuta un DML y devuelve num_dml_affected_rows (0 si no aplica)."""
    from google.cloud import bigquery
    job_config = bigquery.QueryJobConfig(query_parameters=list(params or []))
    job = client.query(sql, job_config=job_config)
    job.result()
    return int(job.num_dml_affected_rows or 0)


def bq_delete_in(client, table, col, values):
    """DELETE FROM tabla WHERE col IN UNNEST(@values). El parametro se tipa
    como DATE si los valores son fechas. Devuelve filas afectadas."""
    vals = list(values) if values is not None else []
    if not vals:
        return 0
    from google.cloud import bigquery
    ptype, norm = infer_param_type(vals)
    sql = f"DELETE FROM {_q(resolve_table(table))} WHERE `{col}` IN UNNEST(@values)"
    return run_dml(client, sql, [bigquery.ArrayQueryParameter('values', ptype, norm)])


def bq_delete_where_gte(client, table, col, value):
    """DELETE FROM tabla WHERE col >= @value (reemplaza .delete().gte())."""
    sql = f"DELETE FROM {_q(resolve_table(table))} WHERE `{col}` >= @value"
    return run_dml(client, sql, [scalar_param('value', value)])


def bq_delete_where_lt(client, table, col, value):
    """DELETE FROM tabla WHERE col < @value (reemplaza .delete().lt())."""
    sql = f"DELETE FROM {_q(resolve_table(table))} WHERE `{col}` < @value"
    return run_dml(client, sql, [scalar_param('value', value)])


def bq_delete_all(client, table):
    """DELETE FROM tabla WHERE TRUE (reemplaza los trucos .or_/.not_.is_ de supabase-py)."""
    return run_dml(client, f"DELETE FROM {_q(resolve_table(table))} WHERE TRUE")


# =============================================================
# LECTURA (rangos y resumen)
# =============================================================

def _scalar(client, sql, params=None):
    from google.cloud import bigquery
    job_config = bigquery.QueryJobConfig(query_parameters=list(params or []))
    rows = list(client.query(sql, job_config=job_config).result())
    return rows[0][0] if rows else None


def get_last_date(client, table, col):
    """SELECT MAX(col). Devuelve string 'YYYY-MM-DD' (como hoy) o None si la
    tabla esta vacia."""
    v = _scalar(client, f"SELECT MAX(`{col}`) FROM {_q(resolve_table(table))}")
    if v is None:
        return None
    return v.isoformat()[:10] if hasattr(v, 'isoformat') else str(v)


def bq_table_stats(client, table, date_col=None):
    """(count, min, max) de la tabla; min/max solo si se pasa date_col."""
    fq = _q(resolve_table(table))
    if date_col:
        rows = list(client.query(
            f"SELECT COUNT(*), MIN(`{date_col}`), MAX(`{date_col}`) FROM {fq}"
        ).result())
        count, mn, mx = rows[0][0], rows[0][1], rows[0][2]
        return int(count or 0), mn, mx
    count = _scalar(client, f"SELECT COUNT(*) FROM {fq}")
    return int(count or 0), None, None


def bq_count(client, table) -> int:
    return bq_table_stats(client, table)[0]


# =============================================================
# MARTS (reemplazo de REFRESH MATERIALIZED VIEW)
# =============================================================

def parse_refresh_order(text: str) -> list:
    """refresh_order.txt: un nombre por linea, '#' comenta, se ignora el
    sufijo .sql y las lineas vacias. Conserva el orden, sin repetidos."""
    out = []
    for raw in text.splitlines():
        line = raw.split('#', 1)[0].strip()
        if not line:
            continue
        if line.endswith('.sql'):
            line = line[:-4]
        if line not in out:
            out.append(line)
    return out


def render_mart_sql(sql: str, project=None, raw=None, dim=None, mart=None, ops=None) -> str:
    """Sustituye ${project}, ${raw}, ${dim}, ${mart}, ${ops} (y ${stg}) en el
    texto del .sql. Placeholders desconocidos se dejan intactos."""
    return Template(sql).safe_substitute(
        project=project or PROJECT_ID,
        raw=raw or DATASET_RAW,
        dim=dim or DATASET_DIM,
        mart=mart or DATASET_MART,
        ops=ops or DATASET_OPS,
        stg=DATASET_STG,
    )


def list_marts(marts_dir=None) -> list:
    """Orden de refresco: refresh_order.txt; si no existe, *.sql ordenados.
    Los .sql que existen pero no figuran en refresh_order.txt van al final."""
    d = Path(marts_dir or MARTS_DIR)
    order_file = d / REFRESH_ORDER_FILE
    on_disk = sorted(p.stem for p in d.glob('*.sql'))
    if order_file.exists():
        ordered = parse_refresh_order(order_file.read_text(encoding='utf-8'))
        extra = [n for n in on_disk if n not in ordered]
        if extra:
            print(f"      [warn] marts sin entrada en {REFRESH_ORDER_FILE} (van al final): {', '.join(extra)}")
        return ordered + extra
    print(f"      [warn] no existe {order_file}; se usa orden alfabetico de *.sql")
    return on_disk


def refresh_marts(client, names=None, marts_dir=None) -> list:
    """Ejecuta los .sql de AFP_MARTS_DIR en el orden de refresh_order.txt.
    `names`: solo esos (respetando el orden global). Devuelve los ejecutados."""
    d = Path(marts_dir or MARTS_DIR)
    order = list_marts(d)
    if names is not None:
        wanted = set(names)
        unknown = wanted - set(order)
        if unknown:
            raise FileNotFoundError(
                f"marts no encontrados en {d}: {', '.join(sorted(unknown))}")
        order = [n for n in order if n in wanted]

    done = []
    for name in order:
        path = d / f'{name}.sql'
        if not path.exists():
            raise FileNotFoundError(f"falta {path} (listado en {REFRESH_ORDER_FILE})")
        sql = render_mart_sql(path.read_text(encoding='utf-8'))
        print(f"      mart {name} ...", flush=True)
        client.query(sql).result()
        done.append(name)
    return done


# =============================================================
# RUN LOG (afp_ops.run_log)
# =============================================================

RUN_LOG_DDL = """
CREATE TABLE IF NOT EXISTS {table} (
  run_id      STRING,      -- agrupa los pasos de una misma corrida de main.py
  step        STRING,
  started_at  TIMESTAMP,
  finished_at TIMESTAMP,
  duration_s  FLOAT64,
  rc          INT64,
  status      STRING,      -- OK / FAIL / SKIP
  rows        INT64,
  extra       JSON,
  host        STRING,
  inserted_at TIMESTAMP
)
PARTITION BY DATE(started_at)
CLUSTER BY step
"""


def _as_utc(ts):
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    return ts


def log_run(client, step, started, finished, rc, rows=None, extra=None) -> bool:
    """Inserta una fila en afp_ops.run_log. Tolerante: si la tabla no existe la
    crea (CREATE TABLE IF NOT EXISTS); si algo falla, imprime un aviso y
    devuelve False sin interrumpir el pipeline. `started`/`finished`: datetime
    o epoch (time.time()). `extra`: dict serializable a JSON."""
    from google.cloud import bigquery
    fq = f"{PROJECT_ID}.{DATASET_OPS}.{RUN_LOG_TABLE}"
    started, finished = _as_utc(started), _as_utc(finished)
    duration = (finished - started).total_seconds() if started and finished else None
    extra = dict(extra or {})
    run_id = extra.pop('run_id', None) or os.getenv('AFP_RUN_ID')
    status = extra.pop('status', None) or ('OK' if rc == 0 else 'FAIL')
    params = [
        bigquery.ScalarQueryParameter('run_id', 'STRING', run_id),
        bigquery.ScalarQueryParameter('step', 'STRING', step),
        bigquery.ScalarQueryParameter('started_at', 'TIMESTAMP', started),
        bigquery.ScalarQueryParameter('finished_at', 'TIMESTAMP', finished),
        bigquery.ScalarQueryParameter('duration_s', 'FLOAT64', duration),
        bigquery.ScalarQueryParameter('rc', 'INT64', None if rc is None else int(rc)),
        bigquery.ScalarQueryParameter('status', 'STRING', status),
        bigquery.ScalarQueryParameter('rows', 'INT64', None if rows is None else int(rows)),
        bigquery.ScalarQueryParameter('extra', 'STRING', json.dumps(extra, default=str) if extra else None),
        bigquery.ScalarQueryParameter('host', 'STRING', socket.gethostname()),
    ]
    sql = (
        f"INSERT INTO {_q(fq)} "
        "(run_id, step, started_at, finished_at, duration_s, rc, status, rows, extra, host, inserted_at) "
        "VALUES (@run_id, @step, @started_at, @finished_at, @duration_s, @rc, @status, @rows, "
        "SAFE.PARSE_JSON(@extra), @host, CURRENT_TIMESTAMP())"
    )
    try:
        try:
            run_dml(client, sql, params)
        except Exception as first:
            from google.api_core.exceptions import NotFound
            if not isinstance(first, NotFound):
                raise
            client.query(RUN_LOG_DDL.format(table=_q(fq))).result()
            run_dml(client, sql, params)
        return True
    except Exception as e:
        print(f"      [warn] run_log no escrito ({fq}): {e}")
        return False
