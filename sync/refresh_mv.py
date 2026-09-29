"""Reconstruye los marts del dashboard (tablas mv_* en afp_mart) ejecutando los
.sql de db/bigquery/marts en el orden de refresh_order.txt (bq_io.refresh_marts).

Reemplaza al RPC refresh_alternatives_matviews() de Supabase: BigQuery no tiene
REFRESH MATERIALIZED VIEW con esa semantica, asi que cada mv_* es una tabla
recreada con CREATE OR REPLACE TABLE ... AS SELECT (PLAN_MIGRACION_GCP.md D4).

Los syncs ya reconstruyen solos los marts de Alternatives (sync_chist_adjusted.py
y sync_sqlserver_to_supabase.py -> bq_io.ALTERNATIVES_MARTS). Este script corre
TODOS los marts; usalo tras un cambio manual de datos o de un .sql:

    python sync/refresh_mv.py                       # todos, en orden
    python sync/refresh_mv.py --only mv_chist_aa,mv_aum

Requiere ADC (gcloud auth application-default login) y, opcionalmente,
GCP_PROJECT_ID / BQ_LOCATION / AFP_MARTS_DIR (defaults en sync/bq_io.py).
"""
import argparse
import os
import sys
from time import time

from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bq_io import MARTS_DIR, connect_bigquery, list_marts, refresh_marts  # noqa: E402

load_dotenv()


def main():
    ap = argparse.ArgumentParser(description="Reconstruye los marts mv_* en BigQuery")
    ap.add_argument("--only", default=None,
                    help="Solo estos marts, separados por coma (default: todos, en orden)")
    ap.add_argument("--list", action="store_true", help="Muestra el orden y sale")
    args = ap.parse_args()

    names = [n.strip() for n in args.only.split(",") if n.strip()] if args.only else None
    if args.list:
        for n in list_marts(MARTS_DIR):
            print(f"  {n}")
        return

    client = connect_bigquery()
    print(f"Reconstruyendo marts desde {MARTS_DIR} ...")
    t0 = time()
    done = refresh_marts(client, names)
    print(f"OK: {len(done)} marts en {time() - t0:.1f}s -> {', '.join(done)}")


if __name__ == "__main__":
    main()
