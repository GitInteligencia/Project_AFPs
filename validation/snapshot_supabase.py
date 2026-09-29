#!/usr/bin/env python3
"""
Baseline de paridad desde Supabase (PLAN_MIGRACION_GCP.md F0.4): por cada uno de los 39 objetos leídos por la web
(+ las 4 RPC f_sec05_*) guarda en validation/baseline_supabase/<objeto>.json:

  - count total (COUNT(*) exacto)
  - min / max de la columna de fecha
  - para las últimas 3 fechas disponibles (+ las fechas fijas de §12 si existen): count por fecha,
    conjunto de claves de negocio (hash + tamaño, y la lista si es chica) y SUM de todas las columnas numéricas
  - objetos sin fecha: count + sumas + claves sobre la tabla completa
  - funciones: las filas devueltas por la RPC con los parámetros de ejemplo, en el orden canónico

Todo vía REST (supabase-py: SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY en .env), paginando de 1000 en 1000.
No requiere acceso al puerto de Postgres.

Uso:
  python validation/snapshot_supabase.py                       # los 43 objetos
  python validation/snapshot_supabase.py --only v_total,v_aum
  python validation/snapshot_supabase.py --fecha-func 2026-03-31
  python validation/snapshot_supabase.py --n-dates 5 --no-fixed-dates

Sale con rc != 0 si algún objeto falla (p. ej. la vista no existe en Supabase).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from objects import FIXED_DATES, OBJECTS, ParityObject  # noqa: E402

BASELINE_DIR = HERE / "baseline_supabase"
PAGE = 1000
MAX_KEYS_INLINE = 2000  # si el conjunto de claves es mayor sólo se guarda su hash + tamaño


# ---------------------------------------------------------------------------
# REST helpers
# ---------------------------------------------------------------------------

def connect():
    from supabase import create_client

    load_dotenv(REPO_ROOT / ".env")
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise SystemExit("Faltan SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY en .env")
    return create_client(url, key)


def count_exact(client, table: str) -> int:
    resp = client.table(table).select("*", count="exact").limit(1).execute()
    return int(resp.count or 0)


def min_max_date(client, table: str, col: str) -> tuple[str | None, str | None]:
    asc = client.table(table).select(col).not_.is_(col, "null").order(col, desc=False).limit(1).execute().data
    dsc = client.table(table).select(col).not_.is_(col, "null").order(col, desc=True).limit(1).execute().data
    lo = str(asc[0][col])[:10] if asc else None
    hi = str(dsc[0][col])[:10] if dsc else None
    return lo, hi


def last_n_dates(client, table: str, col: str, n: int) -> list[str]:
    """Últimas n fechas DISTINTAS. PostgREST no tiene DISTINCT: se pagina hacia atrás hasta juntar n."""
    out: list[str] = []
    start = 0
    while len(out) < n:
        data = (
            client.table(table).select(col).not_.is_(col, "null")
            .order(col, desc=True).range(start, start + PAGE - 1).execute().data or []
        )
        for r in data:
            f = str(r[col])[:10]
            if f not in out:
                out.append(f)
                if len(out) >= n:
                    break
        if len(data) < PAGE:
            break
        start += PAGE
    return out


def fetch_rows(client, table: str, col: str | None, fechas: list[str] | None) -> pd.DataFrame:
    rows: list[dict] = []
    start = 0
    while True:
        q = client.table(table).select("*")
        if col and fechas:
            q = q.in_(col, fechas)
        data = q.range(start, start + PAGE - 1).execute().data or []
        rows.extend(data)
        if len(data) < PAGE:
            break
        start += PAGE
    return pd.DataFrame(rows)


def call_rpc(client, name: str, params: dict) -> pd.DataFrame:
    data = client.rpc(name, params).execute().data or []
    return pd.DataFrame(data)


# ---------------------------------------------------------------------------
# métricas
# ---------------------------------------------------------------------------

def _num(v):
    if v is None:
        return None
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return v


def numeric_columns(df: pd.DataFrame, exclude: tuple[str, ...]) -> list[str]:
    cols = []
    for c in df.columns:
        if c in exclude:
            continue
        s = pd.to_numeric(df[c], errors="coerce")
        # numérica si todo lo no-nulo se convierte y no es una columna de texto puro
        if df[c].notna().any() and s.notna().sum() == df[c].notna().sum() and not df[c].map(lambda x: isinstance(x, bool)).any():
            cols.append(c)
    return cols


def key_set(df: pd.DataFrame, keys: tuple[str, ...]) -> dict:
    present = [k for k in keys if k in df.columns]
    if not present:
        return {"keys": [], "n": int(len(df)), "sha256": None, "values": None}
    tuples = sorted({tuple("" if pd.isna(v) else str(v) for v in row) for row in df[present].itertuples(index=False)})
    payload = "\n".join("|".join(t) for t in tuples).encode("utf-8")
    return {
        "keys": present,
        "n": len(tuples),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "values": [list(t) for t in tuples] if len(tuples) <= MAX_KEYS_INLINE else None,
    }


def slice_metrics(df: pd.DataFrame, obj: ParityObject) -> dict:
    exclude = tuple(k for k in obj.keys) + ((obj.date_col,) if obj.date_col else ())
    num_cols = numeric_columns(df, exclude) if not df.empty else []
    sums = {c: _num(pd.to_numeric(df[c], errors="coerce").sum(min_count=1)) for c in num_cols}
    nn = {c: int(pd.to_numeric(df[c], errors="coerce").notna().sum()) for c in num_cols}
    return {"count": int(len(df)), "sums": sums, "non_null": nn, "keyset": key_set(df, obj.keys)}


def snapshot_object(client, obj: ParityObject, n_dates: int, fixed: bool, fecha_func: str | None) -> dict:
    out: dict = {
        "object": obj.name,
        "kind": obj.kind,
        "date_col": obj.date_col,
        "keys": list(obj.keys),
        "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "supabase-rest",
    }
    if obj.kind == "function":
        params = dict(obj.params)
        if fecha_func:
            params = {k: fecha_func for k in params}
        df = call_rpc(client, obj.name, params)
        if not df.empty and obj.order_by:
            df = df.sort_values([c for c in obj.order_by if c in df.columns], kind="stable").reset_index(drop=True)
        out["params"] = params
        out["columns"] = list(df.columns)
        out["rows"] = json.loads(df.to_json(orient="records", date_format="iso")) if not df.empty else []
        out["count"] = int(len(df))
        return out

    out["count"] = count_exact(client, obj.name)
    if obj.date_col:
        lo, hi = min_max_date(client, obj.name, obj.date_col)
        out["min_date"], out["max_date"] = lo, hi
        fechas = last_n_dates(client, obj.name, obj.date_col, n_dates)
        if fixed:
            for f in FIXED_DATES:
                if lo and hi and lo <= f <= hi and f not in fechas:
                    fechas.append(f)
        fechas = sorted(fechas)
        df = fetch_rows(client, obj.name, obj.date_col, fechas)
        out["dates"] = fechas
        out["by_date"] = {}
        for f in fechas:
            sub = df[df[obj.date_col].astype(str).str[:10] == f] if not df.empty else df
            out["by_date"][f] = slice_metrics(sub, obj)
        out["columns"] = list(df.columns)
    else:
        df = fetch_rows(client, obj.name, None, None)
        out["columns"] = list(df.columns)
        out["all"] = slice_metrics(df, obj)
        if obj.name == "v_module_freshness" and not df.empty:
            # §12: mismas as_of_date por módulo
            out["as_of"] = {
                f"{r['module_key']}|{r['source_label']}": (str(r["as_of_date"])[:10] if r.get("as_of_date") else None)
                for r in df.to_dict("records")
            }
    return out


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", default=None, help="objetos separados por coma")
    ap.add_argument("--n-dates", type=int, default=3, help="últimas N fechas por objeto (default 3)")
    ap.add_argument("--no-fixed-dates", action="store_true", help="no añadir las fechas fijas de §12")
    ap.add_argument("--fecha-func", default=None, help="p_fecha para las RPC f_sec05_* (default objects.FUNC_FECHA_DEFAULT)")
    ap.add_argument("--out", default=str(BASELINE_DIR))
    args = ap.parse_args(argv)

    targets = OBJECTS
    if args.only:
        wanted = {s.strip() for s in args.only.split(",") if s.strip()}
        targets = [o for o in OBJECTS if o.name in wanted]
        unknown = wanted - {o.name for o in targets}
        if unknown:
            ap.error(f"objetos desconocidos: {sorted(unknown)}")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    client = connect()

    failed: list[str] = []
    for obj in targets:
        try:
            snap = snapshot_object(client, obj, args.n_dates, not args.no_fixed_dates, args.fecha_func)
            (out_dir / f"{obj.name}.json").write_text(
                json.dumps(snap, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8"
            )
            extra = f"fechas={snap.get('dates')}" if snap.get("dates") else ""
            print(f"  OK   {obj.name:40s} count={snap.get('count')} {extra}")
        except Exception as e:  # noqa: BLE001
            failed.append(obj.name)
            print(f"  FAIL {obj.name:40s} {type(e).__name__}: {str(e)[:200]}", file=sys.stderr)

    print(f"\n{len(targets) - len(failed)}/{len(targets)} objetos capturados en {out_dir}")
    if failed:
        print(f"Fallaron: {', '.join(failed)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
