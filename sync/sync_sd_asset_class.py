"""
Sync de las tablas pre-agregadas de asset allocation de la SP:
  Inteligencia_Mercado.dbo.AFP_CL_01_sd  (sistema, por tipo de fondo)  -> sd_asset_class_tipo
  Inteligencia_Mercado.dbo.AFP_CL_02_sd  (por AFP)                     -> sd_asset_class_afp

Estas tablas las mantiene el pipeline del equipo IM (van un mes por delante del
scrape SP propio) y ya vienen en USD MM con la taxonomia nivel_1 (Nacional/
Extranjera) x nivel_2 (Renta Fija/Variable/Derivados/Otros) x glosa (detalle).
Reemplazan a sp_fila como fuente de /asset-allocation (ver vistas v_asset_class_*_sd).

Ventana por defecto: fecha >= 2025-01-01 (lo que el dashboard muestra).
Idempotente: DELETE de las fechas presentes en el pull + INSERT.
Destino: BigQuery (afp_raw; via sync/bq_io.py, ADC). Antes: Supabase REST.

Uso:
    python sync/sync_sd_asset_class.py
    python sync/sync_sd_asset_class.py --start 2024-01-01
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

load_dotenv()

WINDOW = '2025-01-01'


def sync_one(eng, sb, src_table, dst_table, extra_cols, start):
    print(f"\n[sd] {dst_table} <- {src_table}  [fecha >= {start}]")
    query = f"""
        SELECT CAST(fecha AS DATE) AS fecha, {extra_cols}
        FROM Inteligencia_Mercado.dbo.{src_table}
        WHERE fecha >= '{start}'
    """
    df = timed_read(dst_table, eng, query)
    if df.empty:
        print("      -> 0 filas (nada en el rango)")
        return 0
    fechas = sorted(df['fecha'].unique().tolist())
    deleted = supabase_delete_in(sb, dst_table, 'fecha', fechas)
    print(f"      ({deleted:,} filas borradas en {len(fechas)} fechas previas)")
    n = supabase_insert(sb, dst_table, df, batch_size=500, show_progress=True)
    print(f"      -> {n:,} filas insertadas")
    return n


def main():
    ap = argparse.ArgumentParser(
        description="Sync AFP_CL_01_sd/02_sd -> BigQuery sd_asset_class_*",
    )
    ap.add_argument('--start', default=WINDOW, help=f'Inicio YYYY-MM-DD (default {WINDOW})')
    args = ap.parse_args()

    eng = connect_sqlserver()
    sb = connect_supabase()

    sync_one(eng, sb, 'AFP_CL_01_sd', 'sd_asset_class_tipo',
             'tipo_fondo, nivel_1, nivel_2, glosa, monto_usdmm', args.start)
    sync_one(eng, sb, 'AFP_CL_02_sd', 'sd_asset_class_afp',
             'afp, tipo_fondo, nivel_1, nivel_2, glosa, monto_usdmm', args.start)

    print("\n=== DONE ===")


if __name__ == '__main__':
    main()
