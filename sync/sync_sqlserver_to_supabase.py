"""
Sync SQL Server (Inteligencia_Mercado, DW_MONEDA) -> BigQuery (pat-uat-global)

DESTINO (2026-09, migracion GCP): el destino ya NO es Supabase sino BigQuery
(datasets afp_raw / afp_dim; ver PLAN_MIGRACION_GCP.md). El nombre del archivo
se conserva porque los demas syncs importan de aqui los helpers compartidos
(connect_sqlserver / connect_supabase / supabase_upsert / supabase_insert /
supabase_delete_in / get_last_date / timed_read). Esos helpers conservan su
firma y son wrappers finos sobre sync/bq_io.py, que hace la escritura real
(load jobs parquet + MERGE). Autenticacion GCP por ADC (nunca llaves JSON).
BigQuery va por HTTPS/443, asi que pasa por la red corporativa igual que antes.

MODOS DE EJECUCION
==================

1) MODO HISTORICO (con rango explicito) - usar para carga inicial o backfill:

       python sync_sqlserver_to_supabase.py --start 2020-01-01 --end 2024-12-31
       python sync_sqlserver_to_supabase.py --start 2020-01-01            # sin tope, hasta hoy

2) MODO INCREMENTAL (sin --start) - usar para corridas mensuales:

       python sync_sqlserver_to_supabase.py

   Detecta automaticamente la fecha maxima en cada tabla raw de BigQuery
   y carga desde ahi (re-procesa el ultimo mes para capturar correcciones).
   Si la tabla esta vacia, cae al cutoff por defecto (2020-01-01).

ESTRATEGIA POR TABLA
====================
  - historial_carteras:        DELETE por fecha_reporte (solo fechas en el nuevo data) + INSERT
  - valores_cuota_patrimonio:  UPSERT (MERGE) sobre PK (fecha, multifondo, afp)
  - tipo_cambio:               UPSERT (MERGE) sobre PK (solo CLFXDOOB_sindesf)
  - dim_*:                     UPSERT (MERGE) full reload
  - dim_valorizacion_remanente: skip (seed manual, db/seeds)
  Al final se reconstruyen los marts de Alternatives (bq_io.ALTERNATIVES_MARTS),
  equivalente al antiguo RPC refresh_alternatives_matviews().

VARIABLES REQUERIDAS EN .env
============================
  DB_SERVER, DB_DATABASE, DB_UID, DB_PWD            (SQL Server)
  GCP_PROJECT_ID, BQ_LOCATION (opcionales; defaults en sync/bq_io.py) + ADC
"""

import os
import sys
import argparse
import urllib.parse
from datetime import datetime
from time import time

import pandas as pd
from sqlalchemy import create_engine
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bq_io  # noqa: E402
from bq_io import ALTERNATIVES_MARTS, refresh_marts  # noqa: E402,F401

load_dotenv()

DEFAULT_CUTOFF = '2020-01-01'


# =============================================================
# CONEXIONES
# =============================================================

def connect_sqlserver():
    server = os.getenv('DB_SERVER')
    database = os.getenv('DB_DATABASE')
    user = os.getenv('DB_UID')
    pwd = os.getenv('DB_PWD')
    if not all([server, database, user, pwd]):
        raise RuntimeError("Faltan variables DB_* en .env")

    # ODBC Driver 18 (Linux/Windows); Encrypt=optional + TrustServerCertificate
    # como los demas syncs (el nombre "SQL Server" solo existe en Windows).
    odbc_str = (
        f"DRIVER={{ODBC Driver 18 for SQL Server}};"
        f"SERVER={server};"
        f"DATABASE={database};"
        f"UID={user};"
        f"PWD={pwd};"
        f"Encrypt=optional;"
        f"TrustServerCertificate=yes;"
    )
    params = urllib.parse.quote_plus(odbc_str)
    return create_engine(f"mssql+pyodbc:///?odbc_connect={params}")


def connect_supabase():
    """Wrapper de compatibilidad: devuelve un bigquery.Client (ADC). El nombre se
    conserva para no tocar los imports de los demas scripts."""
    return bq_io.connect_bigquery()


# =============================================================
# HELPERS DE ESCRITURA (wrappers finos sobre bq_io, misma firma que antes)
# =============================================================

def timed_read(label, engine, query):
    print(f"      leyendo de SQL Server ({label})...", flush=True)
    t0 = time()
    df = pd.read_sql(query, engine)
    print(f"      ({len(df):,} filas en {time()-t0:.1f}s)")
    return df


def supabase_upsert(client, table, df, on_conflict, batch_size=1000, show_progress=False):
    """UPSERT sobre la clave: dedupe en pandas (keep='last', como siempre) ->
    staging afp_stg -> MERGE. batch_size/show_progress se ignoran (un load job)."""
    return bq_io.bq_upsert(client, table, df, on_conflict,
                           batch_size=batch_size, show_progress=show_progress)


def supabase_insert(client, table, df, batch_size=1000, show_progress=False):
    """INSERT (append) via load job parquet. batch_size/show_progress se ignoran."""
    return bq_io.bq_insert(client, table, df, batch_size=batch_size, show_progress=show_progress)


def supabase_delete_in(client, table, col, values):
    """DELETE WHERE col IN UNNEST(@values). values pueden ser dates. Devuelve filas borradas."""
    return bq_io.bq_delete_in(client, table, col, values)


# =============================================================
# RESOLUCION DE RANGOS (historico vs incremental)
# =============================================================

def get_last_date(client, table, col):
    """SELECT MAX(col) FROM table. Devuelve string YYYY-MM-DD o None."""
    return bq_io.get_last_date(client, table, col)


def resolve_range(args, client, table, col):
    if args.start:
        return args.start, args.end
    last = get_last_date(client, table, col)
    start = last if last else DEFAULT_CUTOFF
    return start, args.end


# =============================================================
# SYNC: DIMENSIONALES (full reload)
# =============================================================

def sync_dim_afp_equivalencias(ms_engine, client, args):
    print("[dim] dim_afp_equivalencias")
    query = """
        SELECT [Original] AS original, [Reemplazo] AS reemplazo
        FROM Inteligencia_Mercado.dbo.AFP_CL_DIM_EQUIVALENCIAS
    """
    df = timed_read('dim_afp_equivalencias', ms_engine, query)
    n = supabase_upsert(client, 'dim_afp_equivalencias', df, ['original'])
    print(f"      -> {n} filas escritas\n")


def sync_dim_tipo_instrumento_filtro(ms_engine, client, args):
    print("[dim] dim_tipo_instrumento_filtro")
    query = """
        SELECT tipo_de_instrumento, [Filtro1] AS filtro1
        FROM Inteligencia_Mercado.dbo.AFP_CL_DIM_TipoInstrumentoF1
    """
    df = timed_read('dim_tipo_instrumento_filtro', ms_engine, query)
    df['filtro1'] = df['filtro1'].str.strip()
    n = supabase_upsert(client, 'dim_tipo_instrumento_filtro', df, ['tipo_de_instrumento'])
    print(f"      -> {n} filas escritas\n")


def sync_dim_bd_funds(ms_engine, client, args):
    # Sin filtro Asset_Class: traemos universo completo (~4,972 filas).
    # Para el dashboard hacen falta tambien los non-alt (Equity, Fixed Income, etc.)
    #
    # 2026-07-14: las columnas nt_* (nueva taxonomia) se traen ahora de
    # DIM_BD_FUNDS_2_INTMDO.New_* en vez del Excel BD_Funds.xlsx. Verificado:
    # New_* poblado 100% (5.149 filas); reconcilia 99,0% con lo cargado por
    # load_bd_funds_nt.py y rellena 559 fondos que el Excel dejaba en NULL.
    # -> load_bd_funds_nt.py + BD_Funds.xlsx quedan retirados (ver su docstring).
    print("[dim] dim_bd_funds (universo completo)")
    query = """
        SELECT
            [ID] AS id, [RUN_TICKER] AS run_ticker, [Fund] AS fondo,
            [Manager] AS manager, [Type] AS type, [Style] AS style,
            [Asset_Class] AS asset_class, [Category] AS category,
            [Region] AS region, [Alt_Fund_Type] AS alt_fund_type,
            [Alt_Strategy] AS alt_strategy,
            [New_Asset_Class] AS nt_asset_class,
            [New_Sub_Asset_Class] AS nt_sub_asset_class,
            [New_Category] AS nt_category,
            [New_Sub_Category] AS nt_sub_category,
            [New_Region] AS nt_region,
            [Distributor] AS distributor
        FROM Inteligencia_Mercado.dbo.DIM_BD_FUNDS_2_INTMDO
    """
    df = timed_read('dim_bd_funds', ms_engine, query)
    n = supabase_upsert(client, 'dim_bd_funds', df, ['id'])
    print(f"      -> {n} filas escritas\n")


def sync_dim_bd_asset_class(ms_engine, client, args):
    print("[dim] dim_bd_asset_class")
    query = """
        SELECT [ID_Asset_Class] AS id_asset_class, [Asset_Class] AS asset_class
        FROM Inteligencia_Mercado.dbo.DIM_BD_Asset_Class
    """
    df = timed_read('dim_bd_asset_class', ms_engine, query)
    n = supabase_upsert(client, 'dim_bd_asset_class', df, ['id_asset_class'])
    print(f"      -> {n} filas escritas\n")


def sync_dim_bd_category(ms_engine, client, args):
    print("[dim] dim_bd_category")
    query = """
        SELECT [ID_Category] AS id_category, [Category] AS category
        FROM Inteligencia_Mercado.dbo.DIM_BD_Category
    """
    df = timed_read('dim_bd_category', ms_engine, query)
    n = supabase_upsert(client, 'dim_bd_category', df, ['id_category'])
    print(f"      -> {n} filas escritas\n")


def sync_dim_bd_region(ms_engine, client, args):
    print("[dim] dim_bd_region")
    query = """
        SELECT [ID_Region] AS id_region, [Region] AS region
        FROM Inteligencia_Mercado.dbo.DIM_BD_Region
    """
    df = timed_read('dim_bd_region', ms_engine, query)
    n = supabase_upsert(client, 'dim_bd_region', df, ['id_region'])
    print(f"      -> {n} filas escritas\n")


def sync_dim_bd_ac_reg_cat(ms_engine, client, args):
    print("[dim] dim_bd_ac_reg_cat (estrategia sec 04)")
    query = """
        SELECT
            [Supra_ID] AS supra_id, [Asset_Class] AS asset_class,
            [Region] AS region, [Category] AS category
        FROM Inteligencia_Mercado.dbo.DIM_BD_AC_Reg_Cat
    """
    df = timed_read('dim_bd_ac_reg_cat', ms_engine, query)
    n = supabase_upsert(client, 'dim_bd_ac_reg_cat', df, ['supra_id'])
    print(f"      -> {n} filas escritas\n")


def sync_dim_bd_family(ms_engine, client, args):
    print("[dim] dim_bd_family (familias Moneda)")
    query = """
        SELECT
            [Family_ID] AS family_id, [Family_Name] AS family_name,
            [Family_ShortName] AS family_short_name
        FROM Inteligencia_Mercado.dbo.DIM_BD_Family
    """
    df = timed_read('dim_bd_family', ms_engine, query)
    n = supabase_upsert(client, 'dim_bd_family', df, ['family_id'])
    print(f"      -> {n} filas escritas\n")


def sync_dim_bd_family_comp(ms_engine, client, args):
    """Mirror desde AFP_CL_DIM_Family_Comp (115 filas curadas, source of truth
    desde 2026-05-27). NO de DIM_BD_Family_Comp del equipo IM (23 stale)."""
    print("[dim] dim_bd_family_comp (Moneda + peers) <- AFP_CL_DIM_Family_Comp")
    query = """
        SELECT family_id, id, tipo, fund_short_name
        FROM Inteligencia_Mercado.dbo.AFP_CL_DIM_Family_Comp
    """
    df = timed_read('dim_bd_family_comp', ms_engine, query)
    n = supabase_upsert(client, 'dim_bd_family_comp', df, ['family_id', 'id'])
    print(f"      -> {n} filas escritas\n")


def sync_dim_bd_direct_inv_lics(ms_engine, client, args):
    print("[dim] dim_bd_direct_inv_lics")
    query = """
        SELECT
            [NEMO] AS nemo, [ASSET_CLASS] AS asset_class,
            [Region] AS region, [NAME] AS name
        FROM Inteligencia_Mercado.dbo.DIM_BD_Direct_Inv_LICS
    """
    df = timed_read('dim_bd_direct_inv_lics', ms_engine, query)
    n = supabase_upsert(client, 'dim_bd_direct_inv_lics', df, ['nemo'])
    print(f"      -> {n} filas escritas\n")


def sync_dim_homol_funds(ms_engine, client, args):
    # Sources de homologacion relevantes para Chile.
    # AFP_CL: nemos del reporting AFP Chile (~2K filas).
    # LICS_CL: ISINs + codigos chilenos via LICS (Lineas de Inversion CMF).
    # CARTERAS_FM_CMF: tickers Bloomberg / nombres FM CMF.
    # RUT_CMF: RUTs.
    # RENTABILIDADES: tickers Bloomberg para series de retorno.
    # Excluimos AFP_CO y AFP_PE (otros paises, no aplican).
    print("[dim] dim_homol_funds (sources Chile)")
    query = """
        SELECT [Name] AS name, [ID] AS id, [Source] AS source
        FROM Inteligencia_Mercado.dbo.DIM_HOMOL_FUNDS_INTMDO
        WHERE Source IN (
            'AFP_CL', 'LICS_CL', 'CARTERAS_FM_CMF', 'RUT_CMF', 'RENTABILIDADES'
        )
    """
    df = timed_read('dim_homol_funds', ms_engine, query)
    n = supabase_upsert(client, 'dim_homol_funds', df, ['name', 'source'])
    print(f"      -> {n} filas escritas\n")


def sync_dim_tipo_instrumento_sp(ms_engine, client, args):
    # Clasificacion oficial SP por codigo de tipo de instrumento.
    # C1: Local / Foreign / Forward
    # C2: NAV / Remanente
    # C3: liquido / iliquido
    # C4: asset class granular (Equity Local Listado, AA, etc.)
    print("[dim] dim_tipo_instrumento_sp")
    query = """
        SELECT
            [Codigo] AS codigo, [Descripcion] AS descripcion,
            [C1] AS c1, [C2] AS c2, [C3] AS c3, [C4] AS c4
        FROM Inteligencia_Mercado.dbo.TBL_SPE_TIPOS_INSTRUMENTOS
    """
    df = timed_read('dim_tipo_instrumento_sp', ms_engine, query)
    n = supabase_upsert(client, 'dim_tipo_instrumento_sp', df, ['codigo'])
    print(f"      -> {n} filas escritas\n")


def sync_dim_rel_feeder_master(ms_engine, client, args):
    print("[dim] dim_rel_feeder_master")
    query = """
        SELECT [Feeder_ID] AS feeder_id, [Master_ID] AS master_id
        FROM Inteligencia_Mercado.dbo.DIM_Rel_Feeder_Master
    """
    df = timed_read('dim_rel_feeder_master', ms_engine, query)
    n = supabase_upsert(client, 'dim_rel_feeder_master', df, ['feeder_id'])
    print(f"      -> {n} filas escritas\n")


# =============================================================
# SYNC: TABLAS RAW (con rango)
# =============================================================

def sync_tipo_cambio(ms_engine, client, args):
    start, end = resolve_range(args, client, 'tipo_cambio', 'fecha')
    print(f"[raw] tipo_cambio  [{start} -> {end or 'hoy'}]")
    t0 = time()

    where = f"daydate >= '{start}'"
    if end:
        where += f" AND daydate <= '{end}'"

    # Dos series:
    #   CLFXDOOB_sindesf : Dolar Observado BCCH (sin desfase). Oficial.
    #   USDCLP Curncy    : Bloomberg interbank. Lo que el reporte interno usa
    #                       para convertir AUM/returns CLP <-> USD.
    query = f"""
        SELECT
            CAST(daydate AS DATE) AS fecha,
            instrumentcode AS instrumento_codigo,
            instrumentvalue AS valor
        FROM DW_MONEDA.dbo.TBL_RENTABILIDADES_DW
        WHERE instrumentcode IN ('CLFXDOOB_sindesf', 'USDCLP Curncy')
          AND {where}
    """
    df = timed_read('tipo_cambio', ms_engine, query)
    n = supabase_upsert(client, 'tipo_cambio', df, ['fecha', 'instrumento_codigo'])
    print(f"      -> {n:,} filas escritas (total: {time()-t0:.1f}s)\n")


def sync_valores_cuota_patrimonio(ms_engine, client, args):
    start, end = resolve_range(args, client, 'valores_cuota_patrimonio', 'fecha')
    print(f"[raw] valores_cuota_patrimonio  [{start} -> {end or 'hoy'}]")
    t0 = time()

    where = f"Fecha >= '{start}'"
    if end:
        where += f" AND Fecha <= '{end}'"
    # Piso fijo 2020+: AFP_CL_VC_PAT tiene historia desde 2002, pero el dashboard
    # solo usa 2020+. Garantiza la ventana aunque se pase un --start anterior.
    where += " AND Fecha >= '2020-01-01'"

    # Re-origen 2026-06-25 (modelo SQL fuente unica): la fuente pasa de
    # TBL_SPE_VALORESCUOTAPATRIMONIO a AFP_CL_VC_PAT. Mismo esquema/naming y valores
    # identicos (verificado: valor_cuota/valor_patrimonio calzan exacto); AFP_CL_VC_PAT
    # tiene mas historia (2002+). Columnas de origen con el mismo nombre.
    query = f"""
        SELECT
            CAST(Fecha AS DATE) AS fecha,
            Multifondo AS multifondo,
            AFP AS afp,
            Valor_Cuota AS valor_cuota,
            Valor_Patrimonio AS valor_patrimonio
        FROM Inteligencia_Mercado.dbo.AFP_CL_VC_PAT
        WHERE {where}
    """
    df = timed_read('valores_cuota_patrimonio', ms_engine, query)
    n = supabase_upsert(client, 'valores_cuota_patrimonio', df,
                        ['fecha', 'multifondo', 'afp'], show_progress=True)
    print(f"      -> {n:,} filas escritas (total: {time()-t0:.1f}s)\n")


def sync_historial_carteras(ms_engine, client, args):
    start, end = resolve_range(args, client, 'historial_carteras', 'fecha_reporte')
    print(f"[raw] historial_carteras  [{start} -> {end or 'hoy'}]")
    t0 = time()

    where_ms = f"h.FechaReporte >= '{start}'"
    if end:
        where_ms += f" AND h.FechaReporte <= '{end}'"

    query = f"""
        SELECT
            CAST(h.FechaReporte AS DATE) AS fecha_reporte,
            CAST(h.fecha AS DATE) AS fecha,
            h.afp, h.tipo_de_fondo, h.tipo_de_instrumento,
            h.nemotecnico_del_instrumento, h.nombre_del_emisor,
            h.nacionalidad_del_emisor, h.unidad_de_reajuste_de_moneda,
            h.unidades, h.precio, h.inversion, h.grupo_economico,
            h.moneda_contrato_forward, h.moneda_objeto_forward,
            h.precio_ejercicio_forward, h.plazo_economico,
            h.tasa_pactada_del_fondo_swap, h.tasa_pactada_de_la_contraparte_s
        FROM Inteligencia_Mercado.dbo.TBL_SPE_HISTORIAL_CARTERAS h
        INNER JOIN Inteligencia_Mercado.dbo.AFP_CL_DIM_TipoInstrumentoF1 f
            ON h.tipo_de_instrumento = f.tipo_de_instrumento
        WHERE {where_ms}
          AND f.Filtro1 = 'Si'
    """
    df = timed_read('historial_carteras', ms_engine, query)

    if df.empty:
        print(f"      -> 0 filas (no hay data en el rango)\n")
        return

    cols_order = [
        'fecha', 'afp', 'tipo_de_fondo', 'tipo_de_instrumento',
        'nemotecnico_del_instrumento', 'nombre_del_emisor',
        'nacionalidad_del_emisor', 'unidad_de_reajuste_de_moneda',
        'unidades', 'precio', 'inversion', 'grupo_economico',
        'moneda_contrato_forward', 'moneda_objeto_forward',
        'precio_ejercicio_forward', 'plazo_economico',
        'tasa_pactada_del_fondo_swap', 'tasa_pactada_de_la_contraparte_s',
        'fecha_reporte'
    ]
    df = df[cols_order]

    fechas_a_reemplazar = sorted(df['fecha_reporte'].unique().tolist())
    print(f"      borrando {len(fechas_a_reemplazar)} fechas previas en BigQuery...", flush=True)
    deleted = supabase_delete_in(client, 'historial_carteras', 'fecha_reporte', fechas_a_reemplazar)
    print(f"      ({deleted:,} filas borradas)")

    n = supabase_insert(client, 'historial_carteras', df, batch_size=500, show_progress=True)
    print(f"      -> {n:,} filas insertadas (total: {time()-t0:.1f}s)\n")


# =============================================================
# RESUMEN POST-SYNC
# =============================================================

def print_summary(client):
    print("\n--- Resumen BigQuery ---")
    tables = [
        # ('historial_carteras', 'fecha_reporte'),  # RETIRADA 2026-06-26 (dropeada; ver main)
        ('valores_cuota_patrimonio', 'fecha'),
        ('tipo_cambio', 'fecha'),
        ('dim_afp_equivalencias', None),
        ('dim_tipo_instrumento_filtro', None),
        ('dim_valorizacion_remanente', None),
        ('dim_bd_funds', None),
        ('dim_bd_asset_class', None),
        ('dim_bd_category', None),
        ('dim_bd_region', None),
        ('dim_bd_ac_reg_cat', None),
        ('dim_bd_family', None),
        ('dim_bd_family_comp', None),
        ('dim_bd_direct_inv_lics', None),
        ('dim_homol_funds', None),
        ('dim_tipo_instrumento_sp', None),
        ('dim_rel_feeder_master', None),
    ]
    for table, fecha_col in tables:
        # COUNT(*) + MIN/MAX(fecha) en una sola consulta por tabla
        try:
            count, mn, mx = bq_io.bq_table_stats(client, table, fecha_col)
        except Exception as e:  # tabla aun no creada, etc.: no aborta el resumen
            print(f"  {table:32s} {'?':>10} ({type(e).__name__})")
            continue
        rng = f" [{mn} -> {mx}]" if fecha_col and count > 0 else ""
        print(f"  {table:32s} {count:>10} filas{rng}")


# =============================================================
# MAIN
# =============================================================

def main():
    parser = argparse.ArgumentParser(
        description='Sync SQL Server -> BigQuery (load jobs + MERGE, ADC)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument(
        '--start',
        help='Fecha inicio YYYY-MM-DD. Si se especifica = MODO HISTORICO. '
             'Si se omite = MODO INCREMENTAL (detecta ultima fecha por tabla).'
    )
    parser.add_argument(
        '--end',
        help='Fecha fin YYYY-MM-DD. Opcional. Default: sin tope superior.'
    )
    args = parser.parse_args()

    start_time = datetime.now()
    if args.start:
        print(f"MODO: HISTORICO  [{args.start} -> {args.end or 'hoy'}]")
    else:
        print(f"MODO: INCREMENTAL  (cutoff fallback = {DEFAULT_CUTOFF})")
    print(f"Inicio: {start_time:%Y-%m-%d %H:%M:%S}\n")

    print("Conectando a SQL Server...")
    ms_engine = connect_sqlserver()
    print("Conectando a BigQuery (ADC)...")
    client = connect_supabase()
    print("Conexiones OK\n")

    try:
        # Dimensionales
        sync_dim_afp_equivalencias(ms_engine, client, args)
        sync_dim_tipo_instrumento_filtro(ms_engine, client, args)
        sync_dim_bd_funds(ms_engine, client, args)
        sync_dim_bd_asset_class(ms_engine, client, args)
        sync_dim_bd_category(ms_engine, client, args)
        sync_dim_bd_region(ms_engine, client, args)
        sync_dim_bd_ac_reg_cat(ms_engine, client, args)
        sync_dim_bd_family(ms_engine, client, args)
        # Re-habilitado 2026-05-27 tras crear AFP_CL_DIM_Family_Comp con las 115
        # curadas. Ahora lee de nuestra tabla, no de la del equipo IM (DIM_BD_Family_Comp
        # sigue stale en 23 pero ya no la usamos).
        sync_dim_bd_family_comp(ms_engine, client, args)
        sync_dim_bd_direct_inv_lics(ms_engine, client, args)
        sync_dim_homol_funds(ms_engine, client, args)
        sync_dim_tipo_instrumento_sp(ms_engine, client, args)
        sync_dim_rel_feeder_master(ms_engine, client, args)
        # Raw (con rango)
        sync_tipo_cambio(ms_engine, client, args)
        sync_valores_cuota_patrimonio(ms_engine, client, args)
        # historial_carteras RETIRADA 2026-06-26 (dropeada de Supabase, −13 MB). El
        # dashboard de Alternatives ahora lee chist_adjusted (sync/sync_chist_adjusted.py).
        # La función sync_historial_carteras() y su entry en RAW_TABLES quedan por si se
        # quiere recrear, pero NO se invoca (escribiría a una tabla inexistente).
        # sync_historial_carteras(ms_engine, client, args)

        print_summary(client)

        # tipo_cambio / VC_PAT (+ BD dims) feed mv_aum and mv_chist_aa, the snapshots
        # behind v_aum / v_total / v_nav / v_uncalled. Refresh them so the dashboard
        # reflects this sync instead of a stale snapshot. En BigQuery los mv_* son
        # tablas reconstruidas desde db/bigquery/marts/*.sql (antes: RPC
        # refresh_alternatives_matviews()).
        print(f"\nReconstruyendo marts del dashboard ({', '.join(ALTERNATIVES_MARTS)})...")
        done = refresh_marts(client, ALTERNATIVES_MARTS)
        print(f"  -> marts reconstruidos: {', '.join(done)}")
    except Exception as e:
        print(f"\n[ERROR] {e}", file=sys.stderr)
        raise
    finally:
        ms_engine.dispose()

    elapsed = datetime.now() - start_time
    print(f"\nSync completado en {elapsed.total_seconds():.1f}s")


if __name__ == '__main__':
    main()
