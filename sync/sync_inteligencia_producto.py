"""
Sync SQL Server `Inteligencia_Producto_Dev` -> BigQuery (`dim_ipd_*` en afp_dim, `ipd_*` en afp_raw).

Destino (2026-09, migracion GCP): BigQuery via sync/bq_io.py con ADC; antes
Supabase REST. Estrategia por tabla intacta: DELETE all + INSERT (full reload).

This DB is the Bloomberg/IPA Moneda internal pipeline. Tables we pull:

Tier A — dimensionales (full reload, ~800 rows total)
  - BD_GICS, BD_Benchmarks, HOMOL_Benchmarks, BD_Funds, HOMOL_Funds,
    BD_Paises, BD_Monedas_Dimensiones

Tier B — instrumentos filtrado (TickerBBG IS NOT NULL, ~2,300 rows)
  - BD_Instrumentos

Tier C — time-series facts
  - extract.IPA (Moneda fund positions, rolling 3 meses, ~100K rows)
  - process.CUBO_Final (aggregated, 1 fecha, ~5K rows)
  - metrics.TBL_JPM_CEMBI_AGG_METRICS (864 rows)
  - metrics.TBL_RISK_AMERICA_AGG_METRICS (1,332 rows)

Connection: BigQuery API over HTTPS/443 (pasa el firewall corporativo igual que la REST de Supabase).

Usage:
    python sync/sync_inteligencia_producto.py
"""

import os
import sys
import urllib.parse
from time import time

import pandas as pd
from sqlalchemy import create_engine
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bq_io  # noqa: E402

load_dotenv()


# =============================================================
# CONEXIONES
# =============================================================

def connect_sqlserver():
    server = os.getenv('DB_SERVER')
    user = 'ccampos'  # Inteligencia_Producto_Dev credentials (from mcp_servers.json)
    pwd = 'Patria2024####'
    database = 'Inteligencia_Producto_Dev'

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
    """Wrapper de compatibilidad: devuelve un bigquery.Client (ADC)."""
    return bq_io.connect_bigquery()


# =============================================================
# HELPERS (wrappers finos sobre bq_io, misma firma que antes)
# =============================================================

def float_to_int(df, cols):
    """Convert pandas float cols (which have NaN-friendly storage) to nullable Int64."""
    for c in cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce').astype('Int64')
    return df


def timed_read(label, engine, query):
    print(f"      leyendo de SQL Server ({label})...", flush=True)
    t0 = time()
    df = pd.read_sql(query, engine)
    print(f"      ({len(df):,} filas en {time()-t0:.1f}s)")
    return df


def supabase_replace(client, table, df, batch_size=1000):
    """Full reload (load WRITE_TRUNCATE). For full-reload dim tables."""
    if df.empty:
        print("      -> 0 filas (DataFrame vacio, skip)")
        return 0
    return bq_io.bq_replace(client, table, df)


def supabase_insert(client, table, df, batch_size=1000, show_progress=True):
    """INSERT (append) via load job parquet. batch_size/show_progress se ignoran."""
    return bq_io.bq_insert(client, table, df, batch_size=batch_size, show_progress=show_progress)


def supabase_delete_all(client, table, pk_col):
    """DELETE FROM tabla WHERE TRUE (pk_col se conserva por firma; no hace falta)."""
    return bq_io.bq_delete_all(client, table)


# =============================================================
# Tier A — Dimensionales (full reload)
# =============================================================

def sync_bd_gics(ms, sb):
    print("\n[A] dim_ipd_gics")
    df = timed_read('BD_GICS', ms, """
        SELECT
            Sector_GICS              AS sector_gics,
            GICS_Sector              AS gics_sector,
            GICS_Sector_Name         AS gics_sector_name,
            GICS_Industry_Group      AS gics_industry_group,
            GICS_Industry_Group_Name AS gics_industry_group_name,
            GICS_Industry            AS gics_industry,
            GICS_Industry_Name       AS gics_industry_name,
            GICS_Sub_Industry        AS gics_sub_industry,
            GICS_Sub_Industry_Name   AS gics_sub_industry_name,
            GICS_Sector_ShortName    AS gics_sector_shortname,
            Description              AS description,
            [GICS_Sector_ShortName.1] AS gics_sector_shortname_2
        FROM dimensionales.BD_GICS
    """)
    df = df.drop_duplicates(subset=['sector_gics'], keep='last')
    supabase_delete_all(sb, 'dim_ipd_gics', 'sector_gics')
    n = supabase_insert(sb, 'dim_ipd_gics', df, batch_size=500)
    print(f"      -> {n:,} insertadas")


def sync_bd_benchmarks(ms, sb):
    print("\n[A] dim_ipd_benchmarks")
    df = timed_read('BD_Benchmarks', ms, """
        SELECT
            ID_BM AS id_bm,
            FundShortName AS fund_short_name,
            BMName AS bm_name,
            FundBaseCurrency AS fund_base_currency,
            NombreTupungato AS nombre_tupungato,
            Estrategia_Comparador AS estrategia_comparador
        FROM dimensionales.BD_Benchmarks
    """)
    df = df.drop_duplicates(subset=['id_bm'], keep='last')
    supabase_delete_all(sb, 'dim_ipd_benchmarks', 'id_bm')
    n = supabase_insert(sb, 'dim_ipd_benchmarks', df, batch_size=500)
    print(f"      -> {n:,} insertadas")


def sync_homol_benchmarks(ms, sb):
    print("\n[A] dim_ipd_homol_benchmarks")
    df = timed_read('HOMOL_Benchmarks', ms, """
        SELECT
            Portfolio AS portfolio,
            ID_BM AS id_bm,
            Source AS source
        FROM dimensionales.HOMOL_Benchmarks
    """)
    df = df.drop_duplicates(subset=['portfolio', 'source'], keep='last')
    df = float_to_int(df, ['id_bm'])
    supabase_delete_all(sb, 'dim_ipd_homol_benchmarks', 'portfolio')
    n = supabase_insert(sb, 'dim_ipd_homol_benchmarks', df, batch_size=500)
    print(f"      -> {n:,} insertadas")


def sync_bd_funds(ms, sb):
    print("\n[A] dim_ipd_funds")
    df = timed_read('BD_Funds', ms, """
        SELECT
            ID_Fund AS id_fund,
            FundShortName AS fund_short_name,
            FundName AS fund_name,
            FundBaseCurrency AS fund_base_currency,
            id_CURR AS id_curr,
            NombreTupungato AS nombre_tupungato,
            Estrategia_Cons_Fondo AS estrategia_cons_fondo,
            Estrategia_Comparador AS estrategia_comparador,
            BM1 AS bm1,
            BM2 AS bm2,
            Activo_MantenedorFondos AS activo_mantenedor_fondos,
            Flag_Derivados AS flag_derivados,
            Flag_UBS AS flag_ubs,
            Fund_Code AS fund_code
        FROM dimensionales.BD_Funds
    """)
    df = df.drop_duplicates(subset=['id_fund'], keep='last')
    df = float_to_int(df, ['id_fund'])
    supabase_delete_all(sb, 'dim_ipd_funds', 'id_fund')
    n = supabase_insert(sb, 'dim_ipd_funds', df, batch_size=500)
    print(f"      -> {n:,} insertadas")


def sync_homol_funds(ms, sb):
    print("\n[A] dim_ipd_homol_funds")
    df = timed_read('HOMOL_Funds', ms, """
        SELECT
            Portfolio AS portfolio,
            ID_Fund AS id_fund,
            Source AS source
        FROM dimensionales.HOMOL_Funds
    """)
    df = df.drop_duplicates(subset=['portfolio', 'source'], keep='last')
    df = float_to_int(df, ['id_fund'])
    supabase_delete_all(sb, 'dim_ipd_homol_funds', 'portfolio')
    n = supabase_insert(sb, 'dim_ipd_homol_funds', df, batch_size=500)
    print(f"      -> {n:,} insertadas")


def sync_bd_paises(ms, sb):
    print("\n[A] dim_ipd_paises")
    df = timed_read('BD_Paises', ms, """
        SELECT
            Code AS code,
            Description AS description,
            Short_Name AS short_name
        FROM dimensionales.BD_Paises
    """)
    df = df.drop_duplicates(subset=['code'], keep='last')
    supabase_delete_all(sb, 'dim_ipd_paises', 'code')
    n = supabase_insert(sb, 'dim_ipd_paises', df, batch_size=500)
    print(f"      -> {n:,} insertadas")


def sync_bd_monedas(ms, sb):
    print("\n[A] dim_ipd_monedas")
    df = timed_read('BD_Monedas_Dimensiones', ms, """
        SELECT
            id_CURR AS id_curr,
            Code AS code,
            LocalCurrency AS local_currency,
            Code_Supramoneda AS code_supramoneda
        FROM dimensionales.BD_Monedas_Dimensiones
    """)
    df = df.drop_duplicates(subset=['id_curr'], keep='last')
    supabase_delete_all(sb, 'dim_ipd_monedas', 'id_curr')
    n = supabase_insert(sb, 'dim_ipd_monedas', df, batch_size=500)
    print(f"      -> {n:,} insertadas")


# =============================================================
# Tier B — Instrumentos (subset)
# =============================================================

def sync_bd_instrumentos(ms, sb):
    print("\n[B] dim_ipd_instrumentos (TickerBBG NOT NULL)")
    df = timed_read('BD_Instrumentos', ms, """
        SELECT
            ID_Instrumento          AS id_instrumento,
            SubID_Instrumento       AS sub_id_instrumento,
            Name_Instrumento        AS name_instrumento,
            ISIN                    AS isin,
            TickerBBG               AS ticker_bbg,
            Sedol                   AS sedol,
            Cusip                   AS cusip,
            CompanyName             AS company_name,
            Investment_Type_Code    AS investment_type_code,
            Issuer_Type_Code        AS issuer_type_code,
            Issue_Type_Code         AS issue_type_code,
            Coupon_Type_Code        AS coupon_type_code,
            Sector_GICS AS sector_gics,
            Sector_Chile_Type_Code  AS sector_chile_type_code,
            Issue_Country           AS issue_country,
            Risk_Country            AS risk_country,
            Issue_Currency          AS issue_currency,
            Risk_Currency           AS risk_currency,
            Rank_Code               AS rank_code,
            Cash_Type_Code          AS cash_type_code,
            Bank_Debt_Type_Code     AS bank_debt_type_code,
            Fund_Type_Code          AS fund_type_code,
            Yield_Type              AS yield_type,
            Yield_Source            AS yield_source,
            Emision_nacional        AS emision_nacional,
            Comentarios             AS comentarios
        FROM dimensionales.BD_Instrumentos
        WHERE TickerBBG IS NOT NULL
    """)
    df = df.drop_duplicates(subset=['id_instrumento'], keep='last')
    int_cols = [
        'investment_type_code', 'issuer_type_code', 'issue_type_code',
        'coupon_type_code', 'sector_chile_type_code', 'rank_code',
        'cash_type_code', 'bank_debt_type_code', 'fund_type_code',
        'yield_type', 'emision_nacional',
    ]
    df = float_to_int(df, int_cols)
    # Convert GICS code (float in SQL Server) -> integer-string. NaN -> None.
    if 'sector_gics' in df.columns:
        gics_int = pd.to_numeric(df['sector_gics'], errors='coerce').astype('Int64')
        df['sector_gics'] = gics_int.astype(str).where(gics_int.notna(), None)
    supabase_delete_all(sb, 'dim_ipd_instrumentos', 'id_instrumento')
    n = supabase_insert(sb, 'dim_ipd_instrumentos', df, batch_size=500)
    print(f"      -> {n:,} insertadas")


# =============================================================
# Tier C — Time-series facts
# =============================================================

def sync_ipa(ms, sb):
    # OBSOLETO 2026-07-01: ipd_positions fue dropeada de Supabase. Pionero/MRV
    # (Sec05) ahora salen de TBL_IPA_V2 via sync/sync_ipd_strategy.py
    # (ipd_cartera_eom). Esta funcion queda solo como referencia historica.
    print("\n[C] ipd_positions (extract.IPA)")
    df = timed_read('IPA', ms, """
        SELECT
            ID_Proceso         AS id_proceso,
            ID_Ejecucion       AS id_ejecucion,
            ID_Fund            AS id_fund,
            Portfolio          AS portfolio,
            FechaReporte       AS fecha_reporte,
            FechaCartera       AS fecha_cartera,
            TotalText          AS total_text,
            ReportMode         AS report_mode,
            LSDesc             AS ls_desc,
            SortKey            AS sort_key,
            LocalCurrency      AS local_currency,
            BasketInvestDesc   AS basket_invest_desc,
            InvestDescription  AS invest_description,
            InvestID           AS invest_id,
            Qty                AS qty,
            LocalPrice         AS local_price,
            CostLocal          AS cost_local,
            CostBook           AS cost_book,
            UnRealGL           AS unreal_gl,
            AI                 AS ai,
            MVBook             AS mv_book,
            PercentInvest      AS percent_invest,
            PercentSign        AS percent_sign,
            IsSwap             AS is_swap,
            BasketInvID        AS basket_inv_id
        FROM extract.IPA
    """)
    # Reset table (full reload — rolling 3 fechas)
    supabase_delete_all(sb, 'ipd_positions', 'row_id')
    n = supabase_insert(sb, 'ipd_positions', df, batch_size=500)
    print(f"      -> {n:,} insertadas")


def sync_cubo_final(ms, sb):
    print("\n[C] ipd_cubo_final (process.CUBO_Final)")
    df = timed_read('CUBO_Final', ms, """
        SELECT
            ID                  AS id,
            ID_Ejecucion        AS id_ejecucion,
            ID_Fund             AS id_fund,
            TipoRegistro        AS tipo_registro,
            PK2                 AS pk2,
            ID_Instrumento      AS id_instrumento,
            id_CURR             AS id_curr,
            FechaReporte        AS fecha_reporte,
            FechaCartera        AS fecha_cartera,
            BalanceSheet        AS balance_sheet,
            Source              AS source,
            LocalPrice          AS local_price,
            Qty                 AS qty,
            OriginalFace        AS original_face,
            Factor              AS factor,
            AI                  AS ai,
            MVBook              AS mv_book,
            TotalMVal           AS total_mval,
            TotalMVal_Balance   AS total_mval_balance,
            FechaProceso        AS fecha_proceso,
            ID_Proceso          AS id_proceso,
            PRgain              AS pr_gain,
            PUgain              AS pu_gain,
            FxRgain             AS fx_r_gain,
            FxUgain             AS fx_u_gain,
            Income              AS income,
            TotGL               AS tot_gl,
            PctGL               AS pct_gl,
            BasisPoint          AS basis_point,
            FuenteOrigen        AS fuente_origen,
            EsAjuste            AS es_ajuste,
            NotaConsolidacion   AS nota_consolidacion
        FROM process.CUBO_Final
    """)
    df = df.drop_duplicates(subset=['id'], keep='last')
    supabase_delete_all(sb, 'ipd_cubo_final', 'id')
    n = supabase_insert(sb, 'ipd_cubo_final', df, batch_size=500)
    print(f"      -> {n:,} insertadas")


def sync_jpm_cembi_metrics(ms, sb):
    print("\n[C] ipd_jpm_cembi_metrics")
    df = timed_read('TBL_JPM_CEMBI_AGG_METRICS', ms, """
        SELECT
            ID_BM AS id_bm,
            [Mkt Value (USD)] AS mkt_value_usd,
            FechaReporte AS fecha_reporte,
            FechaCartera AS fecha_cartera,
            Source AS source,
            BalanceSheet AS balance_sheet,
            id_CURR AS id_curr,
            CY AS cy,
            [Rating Prom.] AS rating_prom,
            FechaProceso AS fecha_proceso
        FROM metrics.TBL_JPM_CEMBI_AGG_METRICS
    """)
    df = df.drop_duplicates(subset=['id_bm', 'fecha_reporte', 'id_curr'], keep='last')
    supabase_delete_all(sb, 'ipd_jpm_cembi_metrics', 'id_bm')
    n = supabase_insert(sb, 'ipd_jpm_cembi_metrics', df, batch_size=500)
    print(f"      -> {n:,} insertadas")


def sync_risk_america_metrics(ms, sb):
    print("\n[C] ipd_risk_america_metrics")
    df = timed_read('TBL_RISK_AMERICA_AGG_METRICS', ms, """
        SELECT
            Fecha AS fecha,
            ID_BM AS id_bm,
            id_CURR AS id_curr,
            [%_Weight] AS pct_weight,
            TIR AS tir,
            FechaProceso AS fecha_proceso
        FROM metrics.TBL_RISK_AMERICA_AGG_METRICS
    """)
    df = df.drop_duplicates(subset=['fecha', 'id_bm', 'id_curr'], keep='last')
    supabase_delete_all(sb, 'ipd_risk_america_metrics', 'id_bm')
    n = supabase_insert(sb, 'ipd_risk_america_metrics', df, batch_size=500)
    print(f"      -> {n:,} insertadas")


# =============================================================
# MAIN
# =============================================================

def main():
    print("=" * 60)
    print("Sync Inteligencia_Producto_Dev -> BigQuery")
    print("=" * 60)

    ms = connect_sqlserver()
    sb = connect_supabase()

    t0 = time()

    # Tier A
    sync_bd_gics(ms, sb)
    sync_bd_benchmarks(ms, sb)
    sync_homol_benchmarks(ms, sb)
    sync_bd_funds(ms, sb)
    sync_homol_funds(ms, sb)
    sync_bd_paises(ms, sb)
    sync_bd_monedas(ms, sb)

    # Tier B
    sync_bd_instrumentos(ms, sb)

    # Tier C
    sync_jpm_cembi_metrics(ms, sb)
    sync_risk_america_metrics(ms, sb)
    sync_cubo_final(ms, sb)
    # sync_ipa(ms, sb)  # OBSOLETO: ipd_positions dropeada; ver sync_ipd_strategy.py

    print(f"\nTotal: {time()-t0:.1f}s")


if __name__ == '__main__':
    main()
