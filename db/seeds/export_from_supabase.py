#!/usr/bin/env python3
"""
Exporta a CSV las tablas mantenidas a mano en Supabase (PLAN_MIGRACION_GCP.md §6.2 / F0.3) para versionarlas
en db/seeds/ y cargarlas a BigQuery (afp_dim) con db/bigquery/apply.py --only seeds.

Usa la REST API (supabase-py) con SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY del .env (misma via que el sync:
HTTPS/443, funciona detras del firewall de Patria). Paginacion de 1000 filas (tope de PostgREST).

Uso:
  python db/seeds/export_from_supabase.py                 # las 11 tablas de §6.2
  python db/seeds/export_from_supabase.py --extra         # + dim_ipd_gics, dim_ipd_instrumentos (las necesita v_chilean_stocks_gics)
  python db/seeds/export_from_supabase.py --tables dim_chilean_ticker_homol,dim_bdchile
  python db/seeds/export_from_supabase.py --out otra/carpeta

Escribe <tabla>.csv (UTF-8, cabecera, NULL -> vacio) y _manifest.json (filas, columnas, timestamp) en db/seeds/.
Sale con rc != 0 si alguna tabla falla.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent

# Las 11 tablas manuales de PLAN §6.2 y la columna por la que se ordena la paginacion (clave logica).
SEED_TABLES: dict[str, str | None] = {
    "dim_valorizacion_remanente": None,
    "dim_chilean_ticker_homol": "nemo",
    "dim_chilean_stocks_gics_override": "emisor",
    "dim_foreign_region_override": "fund_id",
    "dim_distributor_by_manager": "manager",
    "dim_strategy_ipd_funds": "id_fund",
    "dim_sec08_top_flows": None,
    "dim_bdchile": None,
    "dim_direct_investment_overlay": "identificador",
    "dim_foreign_classification_overlay": "identificador",
    "dim_data_sources": "dataset_key",
}
# Dimensiones de Inteligencia_Producto que hoy carga sync_inteligencia_producto.py (fuera de main.py) y que
# v_chilean_stocks_gics necesita. Se exportan como seed hasta que el pipeline las incluya.
EXTRA_TABLES: dict[str, str | None] = {
    "dim_ipd_gics": "sector_gics",
    "dim_ipd_instrumentos": "id_instrumento",
}
PAGE = 1000


def connect():
    from supabase import create_client

    load_dotenv(REPO_ROOT / ".env")
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise SystemExit("Faltan SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY en .env")
    return create_client(url, key)


def fetch_all(client, table: str, order_col: str | None) -> pd.DataFrame:
    """Trae toda la tabla en paginas de 1000 filas (PostgREST). Ordena por `order_col` para que las paginas sean estables."""
    rows: list[dict] = []
    start = 0
    while True:
        q = client.table(table).select("*")
        if order_col:
            q = q.order(order_col)
        data = q.range(start, start + PAGE - 1).execute().data or []
        rows.extend(data)
        if len(data) < PAGE:
            break
        start += PAGE
    return pd.DataFrame(rows)


def export_table(client, table: str, order_col: str | None, out_dir: Path) -> dict:
    df = fetch_all(client, table, order_col)
    if not order_col and not df.empty:
        # sin clave conocida: orden determinista por todas las columnas para diffs de git limpios
        df = df.sort_values(by=list(df.columns), kind="stable").reset_index(drop=True)
    path = out_dir / f"{table}.csv"
    df.to_csv(path, index=False, encoding="utf-8", na_rep="", lineterminator="\n")
    return {"table": table, "rows": int(len(df)), "columns": list(df.columns), "file": path.name}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tables", default=None, help="lista separada por coma (default: las 11 de §6.2)")
    ap.add_argument("--extra", action="store_true", help="incluye tambien dim_ipd_gics y dim_ipd_instrumentos")
    ap.add_argument("--out", default=str(HERE), help="carpeta de salida (default db/seeds/)")
    args = ap.parse_args(argv)

    targets: dict[str, str | None] = dict(SEED_TABLES)
    if args.extra:
        targets.update(EXTRA_TABLES)
    if args.tables:
        wanted = [t.strip() for t in args.tables.split(",") if t.strip()]
        known = {**SEED_TABLES, **EXTRA_TABLES}
        targets = {t: known.get(t) for t in wanted}

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    client = connect()

    manifest: list[dict] = []
    failed: list[str] = []
    for table, order_col in targets.items():
        try:
            info = export_table(client, table, order_col, out_dir)
            manifest.append(info)
            print(f"  {table:40s} {info['rows']:>7} filas -> {info['file']}")
        except Exception as e:  # noqa: BLE001
            failed.append(table)
            print(f"  {table:40s} ERROR: {e}", file=sys.stderr)

    (out_dir / "_manifest.json").write_text(
        json.dumps(
            {"exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "tables": manifest},
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    if failed:
        print(f"\n{len(failed)} tabla(s) fallaron: {', '.join(failed)}", file=sys.stderr)
        return 1
    print(f"\nOK: {len(manifest)} tablas exportadas a {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
