"""
Sync SQL Server (Inteligencia_Mercado.dbo.AFP_CL_SP_*) -> BigQuery (sp_*, cotizantes_afp).

DESTINO (2026-09, migracion GCP): BigQuery afp_raw via sync/bq_io.py (ADC), ya no
Supabase. El nombre del archivo se conserva (main.py lo invoca como paso
`cotizantes`). SQL Server es source of truth con historia completa; BigQuery es
el backend que sirve al dashboard y mantiene solo la "ventana viva" de datos.

⚠️ MIRROR sp_* RETIRADO (2026-06-26)
====================================
El dashboard ya NO lee las tablas Supabase sp_* (sp_fila / sp_valor_fondo /
sp_valor_afp / sp_valor_instrumento): todo se migró a `consolidated_sd`
(+ chist_adjusted / bbg_returns) en la iniciativa "SQL fuente única". Esas
tablas se dropearon de Supabase (−66 MB). El flag `SYNC_SP_TABLES = False`
apaga la pata sp_* de este script; **cotizantes_afp se sigue sincronizando**
(lo usa Market Share). La fuente SQL Server AFP_CL_SP_* queda intacta, así que
re-habilitar es solo poner el flag en True y recrear las tablas en Supabase.

VENTANA
=======
Solo periodos >= 2025-01 (y fechas >= 2025-01-01 para cotizantes) viajan a
Supabase. Decision del usuario para mantener el free tier holgado. Si en el
futuro se quiere extender, ajustar WINDOW_START_*.

TABLAS Y ESTRATEGIA
===================
  AFP_CL_SP_Fila              -> sp_fila               (DELETE+INSERT por periodo, CASCADE limpia hijas)
  AFP_CL_SP_Valor_Fondo       -> sp_valor_fondo
  AFP_CL_SP_Valor_AFP         -> sp_valor_afp
  AFP_CL_SP_Valor_Instrumento -> sp_valor_instrumento
  AFP_CL_Cotizantes           -> cotizantes_afp        (DELETE WHERE fecha >= window + INSERT todo)

FUENTE DE COTIZANTES (cambio 2026-07-09)
========================================
Los scrapers de spensiones.cl quedaron retirados; cotizantes se lee ahora de
dbo.AFP_CL_Cotizantes (mantenida por el equipo, historia desde 2002, columnas
Fecha/AFP/Numero_Cotizantes) en vez de AFP_CL_SP_Cotizantes (la tabla del
scraper, congelada en 2026-03). Se validó paridad exacta en los meses
solapados 2025+. Las AFPs extintas pre-2009 (BANSANDER, MAGISTER, etc.) quedan
fuera por el filtro de ventana >= 2025-01-01.

IDs PRESERVADOS
===============
fila_id se copia 1:1 de SQL Server (no se regenera). El BIGSERIAL de Supabase
permite override explicito; Postgres no auto-incrementa cuando se pasa el
valor. Esto facilita debugging (mismo ID en ambos DBs).

MODOS DE EJECUCION
==================

1) DEFAULT - sincroniza todos los periodos en la ventana:

       python sync_sp_sqlserver_to_supabase.py

2) PERIODO unico:

       python sync_sp_sqlserver_to_supabase.py --periodo 2025-11
       python sync_sp_sqlserver_to_supabase.py --periodo 202511

3) Solo cotizantes / solo XML:

       python sync_sp_sqlserver_to_supabase.py --skip-cotizantes
       python sync_sp_sqlserver_to_supabase.py --only-cotizantes

VARIABLES REQUERIDAS EN .env
============================
  DB_SERVER, DB_DATABASE, DB_UID, DB_PWD     (SQL Server)
  GCP_PROJECT_ID, BQ_LOCATION (opcionales; defaults en sync/bq_io.py) + ADC
"""

import os
import sys
import argparse
import urllib.parse
from datetime import datetime
from time import time

import pandas as pd
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bq_io  # noqa: E402

load_dotenv()


# =============================================================
# CONFIG
# =============================================================

# sp_* mirror retirado (ver docstring). False = no toca las tablas sp_* (dropeadas
# en Supabase); el script queda efectivamente como sync de cotizantes_afp. Poner en
# True solo si se recrean las tablas sp_* y se quiere volver al two-hop completo.
SYNC_SP_TABLES = False

WINDOW_START_PERIODO = "2025-01"      # sp_*: filtro f.periodo >= esto
WINDOW_START_FECHA   = "2025-01-01"   # cotizantes_afp: filtro fecha >= esto

# Periodos pre-ventana que el dashboard usa como baselines del tab Changes de
# /foreign (LTM = Nov-24, 3Y = Nov-22). El cleanup NO debe borrarlos: en
# 2026-06 el cleanup se llevo ambos y rompio los baselines (Nov-22 ya no
# existe ni en SQL Server; se restaurara via TBL_SPE_REPORTE25_SD).
BASELINE_PERIODOS = ("2022-11", "2024-11")

# Tamano de batch heredado de supabase-py; bq_insert lo ignora (un load job
# parquet por DataFrame). Se conserva para no tocar las firmas.
SB_BATCH = 500


# =============================================================
# CONEXIONES
# =============================================================

def connect_sqlserver():
    """Engine SQLAlchemy contra Inteligencia_Mercado via ODBC Driver 18."""
    server = os.getenv("DB_SERVER")
    database = os.getenv("DB_DATABASE")
    user = os.getenv("DB_UID")
    pwd = os.getenv("DB_PWD")
    if not all([server, database, user, pwd]):
        raise RuntimeError("Faltan DB_SERVER/DB_DATABASE/DB_UID/DB_PWD en .env")

    odbc = (
        f"DRIVER={{ODBC Driver 18 for SQL Server}};"
        f"SERVER={server};"
        f"DATABASE={database};"
        f"UID={user};"
        f"PWD={pwd};"
        f"Encrypt=optional;"
        f"TrustServerCertificate=yes;"
    )
    params = urllib.parse.quote_plus(odbc)
    print(f"  SQL Server: {server} / {database}")
    return create_engine(f"mssql+pyodbc:///?odbc_connect={params}")


def connect_supabase():
    """Wrapper de compatibilidad: devuelve un bigquery.Client (ADC)."""
    return bq_io.connect_bigquery()


# =============================================================
# HELPERS
# =============================================================

def normalize_periodo(s: str) -> str:
    """'202511' | '2025-11' | '2025/11' -> '2025-11'."""
    s = s.strip().replace("/", "-")
    if len(s) == 7 and s[4] == "-":
        return s
    if len(s) == 6:
        return f"{s[:4]}-{s[4:]}"
    raise ValueError(f"Periodo invalido: {s!r}")


def cleanup_out_of_window(client) -> None:
    """Borra de BigQuery los periodos < WINDOW_START_PERIODO (data heredada del
    pipeline viejo que escribia directo), EXCEPTO los BASELINE_PERIODOS que el
    dashboard necesita. One-shot al inicio del mirror."""
    print(f"[cleanup] borrando cotizantes con fecha < {WINDOW_START_FECHA}"
          + (f" y sp_* con periodo < {WINDOW_START_PERIODO} "
             f"(preservando baselines {', '.join(BASELINE_PERIODOS)})" if SYNC_SP_TABLES else ""))
    n_fila = 0
    if SYNC_SP_TABLES:
        # BigQuery no tiene ON DELETE CASCADE: primero las 3 hijas por fila_id, luego sp_fila.
        from google.cloud import bigquery
        params = [
            bigquery.ScalarQueryParameter("w", "STRING", WINDOW_START_PERIODO),
            bigquery.ArrayQueryParameter("baselines", "STRING", list(BASELINE_PERIODOS)),
        ]
        cond = "periodo < @w AND periodo NOT IN UNNEST(@baselines)"
        fila_fq = bq_io.resolve_table("sp_fila")
        for child in ("sp_valor_fondo", "sp_valor_afp", "sp_valor_instrumento"):
            bq_io.run_dml(client, f"DELETE FROM `{bq_io.resolve_table(child)}` WHERE fila_id IN "
                                  f"(SELECT fila_id FROM `{fila_fq}` WHERE {cond})", params)
        n_fila = bq_io.run_dml(client, f"DELETE FROM `{fila_fq}` WHERE {cond}", params)
        if n_fila:
            print(f"      {n_fila:,} sp_fila viejas borradas (+ hijas)")
    n_cot = bq_io.bq_delete_where_lt(client, "cotizantes_afp", "fecha", WINDOW_START_FECHA)
    if n_cot:
        print(f"      {n_cot:,} cotizantes_afp viejos borrados")
    if not (n_fila or n_cot):
        print(f"      nada fuera de ventana")
    print()


def _insert_batches(client, table: str, df: pd.DataFrame, batch_size: int = SB_BATCH) -> int:
    """INSERT (append) del DataFrame via bq_io.bq_insert (un load job parquet;
    batch_size se ignora). Antes recibia list[dict] JSON para supabase-py."""
    if df is None or df.empty:
        return 0
    return bq_io.bq_insert(client, table, df, batch_size=batch_size)


# =============================================================
# SYNC sp_fila + 3 hijas
# =============================================================

# Columnas exactas a copiar (excluyo created_at: el destino pone el suyo via default)
SP_FILA_COLS = [
    "fila_id", "periodo", "fecha_valor", "fecha_publicacion",
    "cuadro", "sub_listado_codigo", "fila_numero", "glosa",
    "tipo_institucion", "moneda_objeto", "agrupacion",
    "emisor", "nemotecnico", "tipo_accion",
    "elegibilidad", "condicion", "unidad_indexada", "es_subtotal",
]
SP_VF_COLS = [
    "fila_id", "tipo_fondo",
    "monto_dolares", "monto_pesos", "porcentaje",
    "porcentaje_sobre_emisor", "porcentaje_sobre_extranjero",
]
SP_VA_COLS = [
    "fila_id", "afp_rut", "afp_nombre",
    "monto_dolares", "porcentaje",
]
SP_VI_COLS = [
    "fila_id", "instrumento_glosa",
    "porcentaje", "monto_pesos", "monto_dolares",
]


def get_target_periodos(engine, override: str = None) -> list:
    """Periodos a sincronizar: todo en SQL Server >= WINDOW_START_PERIODO,
    o solo `override` si esta dado. Oldest first para que el log se vea claro."""
    if override:
        return [override]
    with engine.connect() as conn:
        rows = conn.execute(text(f"""
            SELECT DISTINCT periodo
            FROM dbo.AFP_CL_SP_Fila
            WHERE periodo >= '{WINDOW_START_PERIODO}'
            ORDER BY periodo
        """)).fetchall()
    return [r[0] for r in rows]


def sync_periodo(engine, client, periodo: str) -> dict:
    """Mirror un periodo completo. Asume que en SQL Server esta finalizado."""
    print(f"[periodo {periodo}]")
    t0 = time()

    # === 1. LECTURA SQL SERVER ===
    with engine.connect() as conn:
        df_fila = pd.read_sql_query(
            text(f"""
                SELECT {', '.join(SP_FILA_COLS)}
                FROM dbo.AFP_CL_SP_Fila
                WHERE periodo = :p
            """),
            conn, params={"p": periodo},
        )
        if df_fila.empty:
            print(f"      SKIP: 0 filas en SQL Server")
            return {"filas": 0, "vf": 0, "va": 0, "vi": 0}

        fila_ids = tuple(int(x) for x in df_fila["fila_id"].tolist())
        # SQL Server no acepta tupla vacia con IN ();
        # ya saltamos arriba si esta vacio.
        in_clause = f"({', '.join(str(x) for x in fila_ids)})"

        df_vf = pd.read_sql_query(
            text(f"SELECT {', '.join(SP_VF_COLS)} FROM dbo.AFP_CL_SP_Valor_Fondo WHERE fila_id IN {in_clause}"),
            conn,
        )
        df_va = pd.read_sql_query(
            text(f"SELECT {', '.join(SP_VA_COLS)} FROM dbo.AFP_CL_SP_Valor_AFP WHERE fila_id IN {in_clause}"),
            conn,
        )
        df_vi = pd.read_sql_query(
            text(f"SELECT {', '.join(SP_VI_COLS)} FROM dbo.AFP_CL_SP_Valor_Instrumento WHERE fila_id IN {in_clause}"),
            conn,
        )

    # SQL Server BIT viene como int 0/1; el destino espera bool. Casteamos.
    if "es_subtotal" in df_fila.columns:
        df_fila["es_subtotal"] = df_fila["es_subtotal"].astype(bool)

    print(
        f"      SQL:  {len(df_fila):,} fila | "
        f"{len(df_vf):,} vf | {len(df_va):,} va | {len(df_vi):,} vi"
    )

    # === 2. DELETE EN BIGQUERY (sin CASCADE: hijas por fila_id, luego sp_fila) ===
    fila_fq = bq_io.resolve_table("sp_fila")
    for child in ("sp_valor_fondo", "sp_valor_afp", "sp_valor_instrumento"):
        bq_io.run_dml(client, f"DELETE FROM `{bq_io.resolve_table(child)}` WHERE fila_id IN "
                              f"(SELECT fila_id FROM `{fila_fq}` WHERE periodo = @p)",
                      [bq_io.scalar_param("p", periodo)])
    deleted = bq_io.run_dml(client, f"DELETE FROM `{fila_fq}` WHERE periodo = @p",
                            [bq_io.scalar_param("p", periodo)])
    if deleted:
        print(f"      BQ:   {deleted:,} sp_fila previas borradas")

    # === 3. INSERT EN BIGQUERY ===
    n_filas = _insert_batches(client, "sp_fila",              df_fila)
    n_vf    = _insert_batches(client, "sp_valor_fondo",       df_vf)
    n_va    = _insert_batches(client, "sp_valor_afp",         df_va)
    n_vi    = _insert_batches(client, "sp_valor_instrumento", df_vi)

    print(
        f"      Ins:  {n_filas:,} fila | "
        f"{n_vf:,} vf | {n_va:,} va | {n_vi:,} vi  ({time()-t0:.1f}s)\n"
    )
    return {"filas": n_filas, "vf": n_vf, "va": n_va, "vi": n_vi}


# =============================================================
# SYNC cotizantes
# =============================================================

def sync_cotizantes(engine, client) -> int:
    """Sincroniza la ventana entera de un saque (es chiquita: 7 filas/mes)."""
    print(f"[cotizantes >= {WINDOW_START_FECHA}]")
    t0 = time()
    with engine.connect() as conn:
        df = pd.read_sql_query(
            text(f"""
                SELECT Fecha               AS fecha,
                       AFP                 AS afp,
                       Numero_Cotizantes   AS n_cotizantes
                FROM dbo.AFP_CL_Cotizantes
                WHERE Fecha >= '{WINDOW_START_FECHA}'
                ORDER BY Fecha, AFP
            """),
            conn,
        )

    if df.empty:
        print(f"      SKIP: 0 filas en SQL Server\n")
        return 0

    print(f"      SQL:  {len(df):,} filas")

    # DELETE rango entero + INSERT (mas simple que per-fecha)
    deleted = bq_io.bq_delete_where_gte(client, "cotizantes_afp", "fecha", WINDOW_START_FECHA)
    if deleted:
        print(f"      BQ:   {deleted:,} cotizantes_afp previas borradas")

    n = _insert_batches(client, "cotizantes_afp", df)
    print(f"      Ins:  {n:,} filas  ({time()-t0:.1f}s)\n")
    return n


# =============================================================
# RESUMEN
# =============================================================

def print_summary(client):
    print("--- Resumen BigQuery tras sync ---")
    tablas = ("sp_fila", "sp_valor_fondo", "sp_valor_afp", "sp_valor_instrumento", "cotizantes_afp") \
        if SYNC_SP_TABLES else ("cotizantes_afp",)
    for tbl in tablas:
        print(f"  {tbl:24s} {bq_io.bq_count(client, tbl):>10,} filas")

    if SYNC_SP_TABLES:
        _, mn, mx = bq_io.bq_table_stats(client, "sp_fila", "periodo")
        if mn and mx:
            print(f"  rango sp_fila:           [{mn} -> {mx}]")


# =============================================================
# MAIN
# =============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Sync SQL Server AFP_CL_SP_* -> BigQuery sp_* / cotizantes_afp (ventana >= 2025-01)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--periodo", help="Solo este periodo (YYYY-MM o YYYYMM)")
    parser.add_argument("--skip-cotizantes", action="store_true", help="No sincronizar cotizantes_afp")
    parser.add_argument("--only-cotizantes", action="store_true", help="Solo sincronizar cotizantes_afp")
    args = parser.parse_args()

    if args.skip_cotizantes and args.only_cotizantes:
        parser.error("--skip-cotizantes y --only-cotizantes son incompatibles")

    start_time = datetime.now()
    print(f"Inicio: {start_time:%Y-%m-%d %H:%M:%S}")
    print("Conexiones:")
    engine = connect_sqlserver()
    client = connect_supabase()
    print()

    # Cleanup one-shot de data fuera de ventana, solo si NO es periodo unico.
    if not args.periodo:
        cleanup_out_of_window(client)

    if not args.only_cotizantes and SYNC_SP_TABLES:
        override = normalize_periodo(args.periodo) if args.periodo else None
        periodos = get_target_periodos(engine, override=override)
        print(f"Periodos sp_* a sincronizar ({len(periodos)}): {', '.join(periodos)}\n")
        for p in periodos:
            sync_periodo(engine, client, p)
    elif not SYNC_SP_TABLES and not args.only_cotizantes:
        print("sp_* mirror retirado (SYNC_SP_TABLES=False): se omite; solo cotizantes_afp.\n")

    if not args.skip_cotizantes:
        sync_cotizantes(engine, client)

    print_summary(client)
    elapsed = datetime.now() - start_time
    print(f"\nSync completado en {elapsed.total_seconds():.1f}s")


if __name__ == "__main__":
    main()
