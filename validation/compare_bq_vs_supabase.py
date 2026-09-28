#!/usr/bin/env python3
"""
Paridad de datos BigQuery vs Supabase (PLAN_MIGRACION_GCP.md F2.9 y §12).

Para cada uno de los 39 objetos leídos por la web (+ las 4 table functions f_sec05_*) compara BigQuery contra:
  - el baseline JSON de validation/baseline_supabase/ (generado por snapshot_supabase.py), o
  - Supabase en vivo (--live; reutiliza las funciones de snapshot_supabase.py)

Métricas y tolerancias (§12):
  COUNT(*) por fecha                       exacto
  conjunto de claves por fecha             exacto (hash sha256 de las tuplas ordenadas)
  SUM de columnas numéricas por fecha      NUMERIC/INT: |diff| <= 1e-6 relativo ; FLOAT64 (%, ratios): |diff| <= 1e-9 absoluto
  funciones f_sec05_*                      mismas filas, mismo orden (numéricos con las tolerancias anteriores)
  v_module_freshness                       mismas as_of_date por (module_key, source_label)

Resultado por objeto: [OK] / [WARN] (diferencia numérica explicable por tipo: FLOAT dentro de 1e-6 relativo,
o columna presente sólo en un lado) / [FAIL]. Informe markdown en validation/reports/<YYYY-MM-DD_HHMM>.md.
rc = 1 si hay algún [FAIL] (no se corta con ningún FAIL, §12). Sin credenciales GCP no se puede ejecutar.

Uso:
  python validation/compare_bq_vs_supabase.py                         # vs baseline JSON
  python validation/compare_bq_vs_supabase.py --live                  # vs Supabase en vivo (misma captura que el baseline)
  python validation/compare_bq_vs_supabase.py --only v_total,v_aum --project pat-uat-global
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO_ROOT / "db" / "bigquery"))
from objects import OBJECTS, ParityObject, is_float_like  # noqa: E402
import snapshot_supabase as snap  # noqa: E402
from apply import DATASETS, DEFAULT_LOCATION, DEFAULT_PROJECT  # noqa: E402

BASELINE_DIR = HERE / "baseline_supabase"
REPORTS_DIR = HERE / "reports"

REL_TOL_NUMERIC = 1e-6
ABS_TOL_FLOAT = 1e-9
REL_TOL_WARN = 1e-6  # una columna FLOAT que falla el absoluto pero pasa este relativo -> WARN (redondeo de tipo)


# ---------------------------------------------------------------------------
# BigQuery
# ---------------------------------------------------------------------------

def bq_client(project: str, location: str):
    from google.cloud import bigquery

    return bigquery.Client(project=project, location=location)


def bq_ref(obj: ParityObject, project: str) -> str:
    return f"`{project}.{DATASETS[obj.dataset]}.{obj.name}`"


def bq_df(client, sql: str, params: list | None = None) -> pd.DataFrame:
    from google.cloud import bigquery

    cfg = bigquery.QueryJobConfig(query_parameters=params or [])
    return client.query(sql, job_config=cfg).result().to_dataframe(create_bqstorage_client=False)


def bq_fetch(client, obj: ParityObject, project: str, fechas: list[str] | None) -> pd.DataFrame:
    from google.cloud import bigquery

    ref = bq_ref(obj, project)
    if obj.date_col and fechas:
        sql = f"SELECT * FROM {ref} WHERE {obj.date_col} IN UNNEST(@fechas)"
        params = [bigquery.ArrayQueryParameter("fechas", "DATE", fechas)]
        return bq_df(client, sql, params)
    return bq_df(client, f"SELECT * FROM {ref}")


def bq_count_minmax(client, obj: ParityObject, project: str) -> tuple[int, str | None, str | None]:
    ref = bq_ref(obj, project)
    if obj.date_col:
        df = bq_df(client, f"SELECT COUNT(*) AS n, MIN({obj.date_col}) AS lo, MAX({obj.date_col}) AS hi FROM {ref}")
        r = df.iloc[0]
        return int(r["n"]), (str(r["lo"])[:10] if pd.notna(r["lo"]) else None), (str(r["hi"])[:10] if pd.notna(r["hi"]) else None)
    df = bq_df(client, f"SELECT COUNT(*) AS n FROM {ref}")
    return int(df.iloc[0]["n"]), None, None


def bq_function(client, obj: ParityObject, project: str, params: dict) -> pd.DataFrame:
    from google.cloud import bigquery

    args = ", ".join(f"@{k}" for k in params)
    qp = [bigquery.ScalarQueryParameter(k, "DATE", v) for k, v in params.items()]
    df = bq_df(client, f"SELECT * FROM {bq_ref(obj, project)}({args})", qp)
    if not df.empty and obj.order_by:
        df = df.sort_values([c for c in obj.order_by if c in df.columns], kind="stable").reset_index(drop=True)
    return df


# ---------------------------------------------------------------------------
# comparación
# ---------------------------------------------------------------------------

def _f(v) -> float | None:
    if v is None:
        return None
    if isinstance(v, Decimal):
        return float(v)
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def num_equal(col: str, a, b) -> tuple[bool, str]:
    """(igual?, 'OK'|'WARN'|'FAIL'). Tolerancias §12 según tipo inferido de la columna."""
    fa, fb = _f(a), _f(b)
    if fa is None and fb is None:
        return True, "OK"
    if fa is None or fb is None:
        return False, "FAIL"
    diff = abs(fa - fb)
    scale = max(abs(fa), abs(fb), 1e-300)
    if is_float_like(col):
        if diff <= ABS_TOL_FLOAT:
            return True, "OK"
        if diff / scale <= REL_TOL_WARN:
            return True, "WARN"
        return False, "FAIL"
    if diff / scale <= REL_TOL_NUMERIC or diff <= 1e-9:
        return True, "OK"
    return False, "FAIL"


def worst(statuses: list[str]) -> str:
    if "FAIL" in statuses:
        return "FAIL"
    if "WARN" in statuses:
        return "WARN"
    return "OK"


def compare_slice(bq_metrics: dict, sb_metrics: dict, label: str, lines: list[str]) -> list[str]:
    st: list[str] = []
    if bq_metrics["count"] != sb_metrics["count"]:
        st.append("FAIL")
        lines.append(f"  - {label}: COUNT BigQuery={bq_metrics['count']} Supabase={sb_metrics['count']} **FAIL**")
    else:
        st.append("OK")
    kb, ks = bq_metrics["keyset"], sb_metrics["keyset"]
    if kb["keys"] and ks["keys"]:
        if kb["sha256"] != ks["sha256"] or kb["n"] != ks["n"]:
            st.append("FAIL")
            detail = ""
            if kb.get("values") is not None and ks.get("values") is not None:
                sb_only = [v for v in ks["values"] if v not in kb["values"]][:5]
                bq_only = [v for v in kb["values"] if v not in ks["values"]][:5]
                detail = f" sólo Supabase={sb_only} sólo BigQuery={bq_only}"
            lines.append(f"  - {label}: conjunto de claves {kb['keys']} distinto (n {kb['n']} vs {ks['n']}){detail} **FAIL**")
        else:
            st.append("OK")
    cols = sorted(set(bq_metrics["sums"]) | set(sb_metrics["sums"]))
    for c in cols:
        if c not in bq_metrics["sums"] or c not in sb_metrics["sums"]:
            st.append("WARN")
            lines.append(f"  - {label}: columna numérica `{c}` sólo en {'BigQuery' if c in bq_metrics['sums'] else 'Supabase'} (WARN)")
            continue
        ok, s = num_equal(c, bq_metrics["sums"][c], sb_metrics["sums"][c])
        st.append(s)
        if s != "OK":
            lines.append(f"  - {label}: SUM(`{c}`) BigQuery={bq_metrics['sums'][c]} Supabase={sb_metrics['sums'][c]} **{s}**")
    return st


def compare_object(client, obj: ParityObject, project: str, sb: dict) -> tuple[str, list[str]]:
    lines: list[str] = []
    statuses: list[str] = []

    if obj.kind == "function":
        params = sb.get("params") or obj.params
        bq = bq_function(client, obj, project, params)
        sb_rows = pd.DataFrame(sb.get("rows") or [])
        if len(bq) != len(sb_rows):
            statuses.append("FAIL")
            lines.append(f"  - filas: BigQuery={len(bq)} Supabase={len(sb_rows)} **FAIL**")
        else:
            statuses.append("OK")
            cols = [c for c in sb_rows.columns if c in bq.columns]
            missing = [c for c in sb_rows.columns if c not in bq.columns]
            if missing:
                statuses.append("FAIL")
                lines.append(f"  - columnas ausentes en BigQuery: {missing} **FAIL**")
            for i in range(len(bq)):
                for c in cols:
                    a, b = bq.iloc[i][c], sb_rows.iloc[i][c]
                    if _f(a) is not None or _f(b) is not None:
                        ok, s = num_equal(c, a, b)
                    else:
                        s = "OK" if (str(a) if pd.notna(a) else None) == (str(b) if b is not None and not (isinstance(b, float) and math.isnan(b)) else None) else "FAIL"
                    statuses.append(s)
                    if s != "OK":
                        lines.append(f"  - fila {i} `{c}`: BigQuery={a} Supabase={b} **{s}**")
        lines.insert(0, f"  - params={params}, filas Supabase={len(sb_rows)}")
        return worst(statuses), lines

    n_bq, lo_bq, hi_bq = bq_count_minmax(client, obj, project)
    if n_bq != sb.get("count"):
        statuses.append("FAIL")
        lines.append(f"  - COUNT total: BigQuery={n_bq} Supabase={sb.get('count')} **FAIL**")
    if obj.date_col:
        if (lo_bq, hi_bq) != (sb.get("min_date"), sb.get("max_date")):
            statuses.append("FAIL")
            lines.append(f"  - rango {obj.date_col}: BigQuery=[{lo_bq}, {hi_bq}] Supabase=[{sb.get('min_date')}, {sb.get('max_date')}] **FAIL**")
        fechas = sb.get("dates") or []
        df = bq_fetch(client, obj, project, fechas)
        for f in fechas:
            sub = df[df[obj.date_col].astype(str).str[:10] == f] if not df.empty else df
            statuses += compare_slice(snap.slice_metrics(sub, obj), sb["by_date"][f], f, lines)
        lines.insert(0, f"  - fechas comparadas: {fechas}")
    else:
        df = bq_fetch(client, obj, project, None)
        statuses += compare_slice(snap.slice_metrics(df, obj), sb["all"], "tabla completa", lines)
        if obj.name == "v_module_freshness" and sb.get("as_of"):
            bq_asof = {
                f"{r['module_key']}|{r['source_label']}": (str(r["as_of_date"])[:10] if pd.notna(r["as_of_date"]) else None)
                for r in df.to_dict("records")
            }
            for k, v in sb["as_of"].items():
                if bq_asof.get(k) != v:
                    statuses.append("FAIL")
                    lines.append(f"  - as_of_date `{k}`: BigQuery={bq_asof.get(k)} Supabase={v} **FAIL**")
    if not statuses:
        statuses.append("OK")
    return worst(statuses), lines


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", default=DEFAULT_PROJECT)
    ap.add_argument("--location", default=DEFAULT_LOCATION)
    ap.add_argument("--live", action="store_true", help="comparar contra Supabase en vivo en lugar del baseline JSON")
    ap.add_argument("--only", default=None, help="objetos separados por coma")
    ap.add_argument("--baseline", default=str(BASELINE_DIR))
    ap.add_argument("--fecha-func", default=None, help="p_fecha para las f_sec05_* en modo --live")
    ap.add_argument("--n-dates", type=int, default=3)
    args = ap.parse_args(argv)

    targets = OBJECTS
    if args.only:
        wanted = {s.strip() for s in args.only.split(",") if s.strip()}
        targets = [o for o in OBJECTS if o.name in wanted]
        unknown = wanted - {o.name for o in targets}
        if unknown:
            ap.error(f"objetos desconocidos: {sorted(unknown)}")

    try:
        client = bq_client(args.project, args.location)
    except Exception as e:  # noqa: BLE001
        print(f"No se pudo crear el cliente BigQuery: {e}", file=sys.stderr)
        return 2
    sb_client = snap.connect() if args.live else None

    results: list[tuple[str, str, list[str]]] = []
    for obj in targets:
        try:
            if args.live:
                sb = snap.snapshot_object(sb_client, obj, args.n_dates, True, args.fecha_func)
            else:
                path = Path(args.baseline) / f"{obj.name}.json"
                if not path.exists():
                    results.append((obj.name, "FAIL", [f"  - sin baseline {path.name} (correr snapshot_supabase.py) **FAIL**"]))
                    print(f"  FAIL {obj.name:40s} sin baseline")
                    continue
                sb = json.loads(path.read_text(encoding="utf-8"))
            status, lines = compare_object(client, obj, args.project, sb)
        except Exception as e:  # noqa: BLE001
            status, lines = "FAIL", [f"  - error: {type(e).__name__}: {str(e)[:300]} **FAIL**"]
        results.append((obj.name, status, lines))
        print(f"  {status:4s} {obj.name}")

    n = {s: sum(1 for _, st, _ in results if st == s) for s in ("OK", "WARN", "FAIL")}
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M")
    report = REPORTS_DIR / f"{stamp}.md"
    src = "Supabase en vivo" if args.live else f"baseline `{Path(args.baseline).relative_to(REPO_ROOT) if Path(args.baseline).is_relative_to(REPO_ROOT) else args.baseline}`"
    md = [
        f"# Paridad BigQuery vs Supabase — {stamp} UTC",
        "",
        f"- Proyecto BigQuery: `{args.project}` ({args.location}); datasets {DATASETS}",
        f"- Referencia: {src}",
        f"- Tolerancias (§12): COUNT y claves exactos; NUMERIC rel ≤ {REL_TOL_NUMERIC}; FLOAT64 abs ≤ {ABS_TOL_FLOAT} (WARN si rel ≤ {REL_TOL_WARN})",
        f"- Resultado: **{n['OK']} OK · {n['WARN']} WARN · {n['FAIL']} FAIL** de {len(results)} objetos",
        "",
        "| Objeto | Tipo | Resultado |",
        "|---|---|---|",
    ]
    kinds = {o.name: o.kind for o in OBJECTS}
    for name, st, _ in results:
        md.append(f"| `{name}` | {kinds[name]} | [{st}] |")
    md += ["", "## Detalle", ""]
    for name, st, lines in results:
        md.append(f"### `{name}` — [{st}]")
        md += lines or ["  - sin diferencias"]
        md.append("")
    md += [
        "## Criterio de corte (§12)",
        "",
        "No se corta con ningún `[FAIL]`. Cada `[WARN]` debe tener explicación escrita (redondeo de tipo NUMERIC/FLOAT64)",
        "y ninguna justificación puede implicar cambio de números.",
        "",
    ]
    report.write_text("\n".join(md), encoding="utf-8")
    print(f"\n{n['OK']} OK · {n['WARN']} WARN · {n['FAIL']} FAIL  ->  {report}")
    return 1 if n["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
