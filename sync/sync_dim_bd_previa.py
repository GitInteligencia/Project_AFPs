"""
Sync del separador fondo/inversion-directa SQL Server -> BigQuery:
  Inteligencia_Mercado.dbo.DIM_BD_Previa_AFPCL  ->  dim_bd_previa

Mapa nemo -> Type {FUND, DIRECT_INV}. Dimensional chica, reload completo (UPSERT
on conflict nemo). La fuente trae 9 filas duplicadas exactas -> SELECT DISTINCT.
Destino BigQuery (afp_dim.dim_bd_previa) via sync/bq_io.py con ADC (antes: Supabase).
Requiere que la tabla destino exista (ver dim_bd_previa_schema.sql).

Uso:
    python sync/sync_dim_bd_previa.py
    python sync/sync_dim_bd_previa.py --dry-run
"""
import os
import sys
import argparse

from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sync_sqlserver_to_supabase import (  # noqa: E402
    connect_sqlserver,
    connect_supabase,
    supabase_upsert,
    timed_read,
)
from bq_io import bq_count  # noqa: E402

load_dotenv()

SRC_TABLE = 'DIM_BD_Previa_AFPCL'
DST_TABLE = 'dim_bd_previa'
QUERY = f"SELECT DISTINCT Nemo AS nemo, Type AS type FROM Inteligencia_Mercado.dbo.{SRC_TABLE}"


def main():
    ap = argparse.ArgumentParser(description="Sync DIM_BD_Previa_AFPCL -> BigQuery dim_bd_previa")
    ap.add_argument('--dry-run', action='store_true', help='Solo lee de SQL y reporta; no escribe en BigQuery')
    args = ap.parse_args()

    eng = connect_sqlserver()
    print(f"\n[dim_bd_previa] {DST_TABLE} <- {SRC_TABLE}")
    df = timed_read(DST_TABLE, eng, QUERY)
    print(f"      leidas {len(df):,} filas distintas | Type: "
          + ", ".join(f"{k}={v}" for k, v in df['type'].value_counts().items()))

    if args.dry_run:
        print("      DRY-RUN: no se escribe nada en BigQuery.")
        return

    sb = connect_supabase()
    n = supabase_upsert(sb, DST_TABLE, df, on_conflict='nemo', batch_size=1000, show_progress=True)
    print(f"      -> {n:,} filas upsert")
    got = bq_count(sb, DST_TABLE)
    print(f"      verificacion: {got:,} filas en BigQuery (esperado {len(df):,})")
    print("\n=== DONE ===")


if __name__ == '__main__':
    main()
