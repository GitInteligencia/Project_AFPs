"""
Sync de la cartera consolidada SIN desfase (nivel sistema) de SQL Server -> BigQuery:
  Inteligencia_Mercado.dbo.AFP_CL_09_17_25_sd_consolidated  ->  consolidated_sd

Detalle a nivel SISTEMA (no por AFP): fecha x tipo_fondo x nemotecnico, con monto
USD MM y limites nacional/extranjero. `source` = cuadro SP (09/17 nacional, 25
extranjero, 17+25 ambos). Reemplaza la rama SP XML (sp_*) para el detalle fresco.

Historia COMPLETA por defecto (la tabla es chica). Idempotente: DELETE de las
fechas presentes en el pull + INSERT. Destino BigQuery (afp_raw) via sync/bq_io.py
con ADC (antes: Supabase REST).

Requiere que la tabla destino exista (ver consolidated_sd_schema.sql).

Uso:
    python sync/sync_consolidated_sd.py                  # historia completa
    python sync/sync_consolidated_sd.py --start 2026-01-01   # solo refresco reciente
    python sync/sync_consolidated_sd.py --dry-run        # solo lee y reporta, no escribe
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

SRC_TABLE = 'AFP_CL_09_17_25_sd_consolidated'
DST_TABLE = 'consolidated_sd'


def build_query(start):
    where = f"WHERE fecha >= '{start}'" if start else ""
    return f"""
        SELECT CAST(fecha AS DATE)        AS fecha,
               tipo_fondo                 AS tipo_fondo,
               nemotecnico                AS nemotecnico,
               [Source]                   AS source,
               lim_nac_usdmm              AS lim_nac_usdmm,
               lim_extr_usdmm             AS lim_extr_usdmm,
               monto_usdmm                AS monto_usdmm
        FROM Inteligencia_Mercado.dbo.{SRC_TABLE}
        {where}
    """


def main():
    ap = argparse.ArgumentParser(description="Sync AFP_CL_09_17_25_sd_consolidated -> BigQuery consolidated_sd")
    ap.add_argument('--start', default=None, help='Inicio YYYY-MM-DD (default: historia completa)')
    ap.add_argument('--dry-run', action='store_true', help='Solo lee de SQL y reporta; no escribe en BigQuery')
    args = ap.parse_args()

    eng = connect_sqlserver()

    print(f"\n[consolidated_sd] {DST_TABLE} <- {SRC_TABLE}"
          + (f"  [fecha >= {args.start}]" if args.start else "  [historia completa]"))
    df = timed_read(DST_TABLE, eng, build_query(args.start))
    if df.empty:
        print("      -> 0 filas (nada en el rango)")
        return

    fechas = sorted(df['fecha'].unique().tolist())
    print(f"      leidas {len(df):,} filas en {len(fechas)} fechas "
          f"[{fechas[0]} .. {fechas[-1]}]")

    if args.dry_run:
        print("      DRY-RUN: no se escribe nada en BigQuery.")
        return

    sb = connect_supabase()
    deleted = supabase_delete_in(sb, DST_TABLE, 'fecha', fechas)
    print(f"      ({deleted:,} filas borradas en {len(fechas)} fechas previas)")
    n = supabase_insert(sb, DST_TABLE, df, batch_size=500, show_progress=True)
    print(f"      -> {n:,} filas insertadas")

    # verificacion: conteo destino debe igualar lo leido
    got = bq_count(sb, DST_TABLE)
    print(f"      verificacion: {got:,} filas en BigQuery (esperado >= {len(df):,})")
    print("\n=== DONE ===")


if __name__ == '__main__':
    main()
