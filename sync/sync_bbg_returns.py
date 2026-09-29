"""
Sync de retornos Bloomberg de fondos (no alternativos) SQL Server -> BigQuery:
  Inteligencia_Mercado.dbo.AFP_CL_BBG_Returns  ->  bbg_returns

Retorno mensual USD por fondo (Nemo_SP). Reemplaza a bbg_returns_foreign (Excel,
solo foreign). Historia COMPLETA por defecto. Idempotente: DELETE de los end_date
presentes en el pull + INSERT. Destino BigQuery (afp_raw) via sync/bq_io.py con ADC
(antes: Supabase REST).

Requiere que la tabla destino exista (ver bbg_returns_schema.sql).

Uso:
    python sync/sync_bbg_returns.py                    # historia completa
    python sync/sync_bbg_returns.py --start 2026-01-01 # solo refresco reciente (por end_date)
    python sync/sync_bbg_returns.py --dry-run
"""
import os
import sys
import argparse

from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sync_sqlserver_to_supabase import (  # noqa: E402
    connect_sqlserver,
    connect_supabase,
    supabase_insert,
    supabase_delete_in,
    timed_read,
)
from bq_io import bq_count  # noqa: E402

load_dotenv()

SRC_TABLE = 'AFP_CL_BBG_Returns'
DST_TABLE = 'bbg_returns'


def build_query(start):
    where = f"WHERE EndDate >= '{start}'" if start else ""
    return f"""
        SELECT CAST(StartDate AS DATE) AS start_date,
               CAST(EndDate   AS DATE) AS end_date,
               Nemo_SP                 AS nemo_sp,
               ISIN_Ticker             AS isin_ticker,
               USD_Ret                 AS usd_ret
        FROM Inteligencia_Mercado.dbo.{SRC_TABLE}
        {where}
    """


def main():
    ap = argparse.ArgumentParser(description="Sync AFP_CL_BBG_Returns -> BigQuery bbg_returns")
    ap.add_argument('--start', default=None, help='Inicio YYYY-MM-DD por end_date (default: historia completa)')
    ap.add_argument('--dry-run', action='store_true', help='Solo lee de SQL y reporta; no escribe en BigQuery')
    args = ap.parse_args()

    eng = connect_sqlserver()

    print(f"\n[bbg_returns] {DST_TABLE} <- {SRC_TABLE}"
          + (f"  [end_date >= {args.start}]" if args.start else "  [historia completa]"))
    df = timed_read(DST_TABLE, eng, build_query(args.start))
    if df.empty:
        print("      -> 0 filas (nada en el rango)")
        return

    fechas = sorted(df['end_date'].unique().tolist())
    print(f"      leidas {len(df):,} filas en {len(fechas)} periodos "
          f"[{fechas[0]} .. {fechas[-1]}]")

    if args.dry_run:
        print("      DRY-RUN: no se escribe nada en BigQuery.")
        return

    sb = connect_supabase()
    deleted = supabase_delete_in(sb, DST_TABLE, 'end_date', fechas)
    print(f"      ({deleted:,} filas borradas en {len(fechas)} periodos previos)")
    n = supabase_insert(sb, DST_TABLE, df, batch_size=500, show_progress=True)
    print(f"      -> {n:,} filas insertadas")

    got = bq_count(sb, DST_TABLE)
    print(f"      verificacion: {got:,} filas en BigQuery (esperado >= {len(df):,})")
    print("\n=== DONE ===")


if __name__ == '__main__':
    main()
