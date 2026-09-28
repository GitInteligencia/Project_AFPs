#!/usr/bin/env python3
"""
Aplicador idempotente de la capa de datos AFP en BigQuery (PLAN_MIGRACION_GCP.md F2.7).

Orden de aplicación (por defecto todo):

  datasets  -> crea afp_raw / afp_dim / afp_mart / afp_ops / afp_stg si no existen
  tables    -> db/bigquery/tables/*.sql      (CREATE TABLE IF NOT EXISTS)
  seeds     -> db/seeds/*.csv -> afp_dim.<tabla>  (WRITE_TRUNCATE, esquema de tables/<tabla>.sql o autodetect)
  views     -> db/bigquery/views/*.sql + db/bigquery/marts/*.sql en orden topológico.
               Las vistas referencian tablas mv_* (marts), por eso ambos se resuelven en un mismo grafo:
               un mart se construye completo sólo si no existe todavía (bootstrap) o si se pasó --with-marts.
  functions -> db/bigquery/functions/*.sql   (CREATE OR REPLACE TABLE FUNCTION)
  marts     -> sólo con --only marts (o --with-marts): reconstruye las tablas mv_* en el orden de
               db/bigquery/marts/refresh_order.txt (lo que hoy hace refresh_alternatives_matviews()).

Placeholders sustituidos en TODO el SQL: ${project} ${raw} ${dim} ${mart} ${ops} ${stg}.

Uso:
  python db/bigquery/apply.py --parse-check                 # sin GCP: sintaxis BigQuery con sqlglot
  python db/bigquery/apply.py --dry-run                     # valida contra el proyecto (QueryJobConfig(dry_run=True))
  python db/bigquery/apply.py --only tables,views
  python db/bigquery/apply.py --with-marts                  # despliegue completo incluyendo reconstrucción de marts
  python db/bigquery/apply.py --only marts                  # = paso `marts` del job (refresh_order.txt)

Sale con código != 0 si algo falla. Sin credenciales GCP sólo funciona --parse-check.
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB_DIR = HERE.parent
SEEDS_DIR = DB_DIR / "seeds"

DEFAULT_PROJECT = os.environ.get("GCP_PROJECT", "pat-uat-global")
DEFAULT_LOCATION = os.environ.get("BQ_LOCATION", "southamerica-west1")
DATASETS = {
    "raw": os.environ.get("BQ_DATASET_RAW", "afp_raw"),
    "dim": os.environ.get("BQ_DATASET_DIM", "afp_dim"),
    "mart": os.environ.get("BQ_DATASET_MART", "afp_mart"),
    "ops": os.environ.get("BQ_DATASET_OPS", "afp_ops"),
    "stg": os.environ.get("BQ_DATASET_STG", "afp_stg"),
}
STG_EXPIRATION_MS = 86_400_000  # 1 día
LABELS = {"app": "afp-dashboard"}

STEPS = ("tables", "seeds", "views", "functions", "marts")

# Archivos .sql que sqlglot no puede parsear aunque sean BigQuery válido. Cada entrada debe llevar
# justificación; --parse-check los reporta como EXENTO (no como error). Hoy: ninguno.
PARSE_CHECK_EXEMPT: dict[str, str] = {
    # "views/x.sql": "motivo",
}


# ---------------------------------------------------------------------------
# utilidades
# ---------------------------------------------------------------------------

class ApplyError(Exception):
    pass


def log(msg: str) -> None:
    print(msg, flush=True)


def render(sql: str, project: str) -> str:
    """Sustituye los placeholders ${project}/${raw}/${dim}/${mart}/${ops}/${stg}."""
    out = sql.replace("${project}", project)
    for key, ds in DATASETS.items():
        out = out.replace("${" + key + "}", ds)
    left = sorted(set(re.findall(r"\$\{(\w+)\}", out)))
    if left:
        raise ApplyError(f"placeholders sin resolver: {left}")
    return out


def sql_files(folder: Path) -> list[Path]:
    """*.sql de una carpeta, orden alfabético; ignora los que empiezan por '_' (plantillas / docs)."""
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.glob("*.sql") if not p.name.startswith("_"))


def object_name(path: Path) -> str:
    return path.stem


@dataclass
class SqlObject:
    name: str
    kind: str          # 'view' | 'mart' | 'table' | 'function'
    path: Path
    sql: str
    deps: set[str] = field(default_factory=set)
    unknown: set[str] = field(default_factory=set)   # referencias ${mart}.x sin .sql en el repo (pendientes de dump)


def load_objects(folder: Path, kind: str) -> dict[str, SqlObject]:
    objs: dict[str, SqlObject] = {}
    for p in sql_files(folder):
        objs[object_name(p)] = SqlObject(object_name(p), kind, p, p.read_text(encoding="utf-8"))
    return objs


_REF_RE = re.compile(r"\$\{mart\}\.(\w+)")


def resolve_deps(objs: dict[str, SqlObject]) -> None:
    """Dependencias entre objetos de afp_mart por referencia textual `${mart}.<nombre>`."""
    for o in objs.values():
        body = strip_comments(o.sql)
        refs = set(_REF_RE.findall(body)) - {o.name}
        o.deps = {r for r in refs if r in objs}
        o.unknown = set(refs) - set(objs) - {o.name}


def strip_comments(sql: str) -> str:
    return "\n".join(line.split("--", 1)[0] for line in sql.splitlines())


def topo_order(objs: dict[str, SqlObject]) -> list[SqlObject]:
    """Orden topológico determinista (Kahn, desempate alfabético). Error si hay ciclo."""
    indeg = {n: len(o.deps) for n, o in objs.items()}
    rev: dict[str, set[str]] = {n: set() for n in objs}
    for n, o in objs.items():
        for d in o.deps:
            rev[d].add(n)
    ready = sorted(n for n, k in indeg.items() if k == 0)
    out: list[SqlObject] = []
    while ready:
        n = ready.pop(0)
        out.append(objs[n])
        for m in sorted(rev[n]):
            indeg[m] -= 1
            if indeg[m] == 0:
                ready.append(m)
                ready.sort()
    if len(out) != len(objs):
        cyc = sorted(n for n, k in indeg.items() if k > 0)
        raise ApplyError(f"ciclo de dependencias entre objetos afp_mart: {cyc}")
    return out


def read_refresh_order(path: Path) -> list[str]:
    names: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            names.append(line)
    return names


# ---------------------------------------------------------------------------
# --parse-check (offline, sqlglot)
# ---------------------------------------------------------------------------

def parse_check(project: str) -> int:
    try:
        import sqlglot
        from sqlglot.errors import ParseError
    except ImportError:
        log("[parse-check] falta sqlglot: pip install sqlglot")
        return 2

    folders = {"tables": HERE / "tables", "views": HERE / "views", "marts": HERE / "marts", "functions": HERE / "functions"}
    n_ok = n_err = n_exempt = 0
    errors: list[str] = []
    for kind, folder in folders.items():
        for p in sql_files(folder):
            rel = f"{kind}/{p.name}"
            sql = render(p.read_text(encoding="utf-8"), project)
            if rel in PARSE_CHECK_EXEMPT:
                n_exempt += 1
                log(f"[parse-check] EXENTO  {rel}: {PARSE_CHECK_EXEMPT[rel]}")
                continue
            try:
                stmts = [s for s in sqlglot.parse(sql, read="bigquery") if s is not None]
                if not stmts:
                    raise ParseError("archivo sin sentencias")
                # sqlglot devuelve exp.Command cuando no entiende una sentencia (la "traga" sin parsearla):
                # eso NO cuenta como validación, se trata como error.
                from sqlglot import exp

                if any(isinstance(s, exp.Command) or s.find(exp.Command) is not None for s in stmts):
                    raise ParseError("sentencia no parseada por sqlglot (exp.Command); revisar sintaxis")
                n_ok += 1
            except ParseError as e:  # sqlglot lanza ParseError (subclase de SqlglotError)
                n_err += 1
                msg = str(e).splitlines()[0]
                errors.append(f"{rel}: {msg}")
                log(f"[parse-check] ERROR   {rel}: {msg}")
            except Exception as e:  # noqa: BLE001 - cualquier otro fallo del parser también cuenta
                n_err += 1
                errors.append(f"{rel}: {type(e).__name__}: {e}")
                log(f"[parse-check] ERROR   {rel}: {type(e).__name__}: {e}")

    # consistencia del grafo de vistas/marts y de refresh_order.txt (no requiere GCP)
    objs = load_objects(HERE / "views", "view") | load_objects(HERE / "marts", "mart")
    resolve_deps(objs)
    try:
        order = topo_order(objs)
        log(f"[parse-check] grafo afp_mart OK: {len(order)} objetos, orden topológico resuelto")
    except ApplyError as e:
        n_err += 1
        errors.append(str(e))
        log(f"[parse-check] ERROR   {e}")
    unknown = {o.name: sorted(o.unknown) for o in objs.values() if o.unknown}
    for name, refs in sorted(unknown.items()):
        log(f"[parse-check] AVISO   {name} referencia objetos afp_mart sin .sql en el repo (pendientes de dump): {refs}")

    marts = load_objects(HERE / "marts", "mart")
    order_file = HERE / "marts" / "refresh_order.txt"
    listed = read_refresh_order(order_file) if order_file.exists() else []
    missing_sql = [n for n in listed if n not in marts]
    missing_list = [n for n in marts if n not in listed]
    if missing_sql:
        n_err += 1
        errors.append(f"refresh_order.txt nombra marts sin .sql: {missing_sql}")
        log(f"[parse-check] ERROR   refresh_order.txt nombra marts sin .sql: {missing_sql}")
    if missing_list:
        n_err += 1
        errors.append(f"marts/*.sql no listados en refresh_order.txt: {missing_list}")
        log(f"[parse-check] ERROR   marts/*.sql no listados en refresh_order.txt: {missing_list}")

    log(f"[parse-check] {n_ok} archivos OK, {n_exempt} exentos, {n_err} errores")
    return 1 if n_err else 0


# ---------------------------------------------------------------------------
# BigQuery
# ---------------------------------------------------------------------------

def bq_client(project: str, location: str):
    from google.cloud import bigquery

    return bigquery.Client(project=project, location=location)


def ensure_datasets(client, project: str, location: str, dry_run: bool) -> None:
    from google.api_core.exceptions import NotFound
    from google.cloud import bigquery

    for key, ds_name in DATASETS.items():
        ref = bigquery.Dataset(f"{project}.{ds_name}")
        try:
            client.get_dataset(ref)
            log(f"[datasets] existe   {ds_name}")
            continue
        except NotFound:
            pass
        if dry_run:
            log(f"[datasets] (dry-run) se crearía {ds_name} en {location}")
            continue
        ref.location = location
        ref.labels = dict(LABELS)
        if key == "stg":
            ref.default_table_expiration_ms = STG_EXPIRATION_MS
        ref.description = {
            "raw": "Tablas espejo del pipeline afp-sync (SQL Server -> BigQuery).",
            "dim": "Dimensiones (pipeline + seeds manuales) del dashboard AFP.",
            "mart": "Vistas v_*, tablas mv_* y table functions f_sec05_* leídas por la web AFP.",
            "ops": "Operación del pipeline afp-sync (run_log).",
            "stg": "Staging del pipeline (MERGE); las tablas expiran en 1 día.",
        }[key]
        client.create_dataset(ref, exists_ok=True)
        log(f"[datasets] creado   {ds_name} ({location})")


def run_sql(client, sql: str, label: str, dry_run: bool) -> None:
    from google.cloud import bigquery

    cfg = bigquery.QueryJobConfig(dry_run=dry_run, use_query_cache=False)
    t0 = time.time()
    job = client.query(sql, job_config=cfg)
    if not dry_run:
        job.result()
    dt = time.time() - t0
    tag = "(dry-run) " if dry_run else ""
    log(f"[sql] {tag}OK {label} ({dt:.1f}s)")


def table_exists(client, table_id: str) -> bool:
    from google.api_core.exceptions import NotFound

    try:
        client.get_table(table_id)
        return True
    except NotFound:
        return False


def apply_tables(client, project: str, dry_run: bool) -> None:
    for p in sql_files(HERE / "tables"):
        run_sql(client, render(p.read_text(encoding="utf-8"), project), f"tables/{p.name}", dry_run)


def schema_from_ddl(ddl_path: Path, project: str):
    """SchemaField[] a partir del CREATE TABLE de tables/<tabla>.sql (vía sqlglot). None si no se puede."""
    try:
        import sqlglot
        from google.cloud import bigquery
        from sqlglot import exp
    except ImportError:
        return None
    try:
        stmt = sqlglot.parse_one(render(ddl_path.read_text(encoding="utf-8"), project), read="bigquery")
    except Exception:  # noqa: BLE001
        return None
    fields = []
    for col in stmt.find_all(exp.ColumnDef):
        name = col.this.name
        kind = col.kind.sql(dialect="bigquery") if col.kind is not None else "STRING"
        kind = kind.split("(")[0].upper()
        mode = "REQUIRED" if any(isinstance(c.kind, exp.NotNullColumnConstraint) for c in col.constraints) else "NULLABLE"
        fields.append(bigquery.SchemaField(name, kind, mode=mode))
    return fields or None


def apply_seeds(client, project: str, dry_run: bool) -> None:
    from google.cloud import bigquery

    csvs = sorted(SEEDS_DIR.glob("*.csv")) if SEEDS_DIR.is_dir() else []
    if not csvs:
        log(f"[seeds] no hay CSV en {SEEDS_DIR} (ejecutar db/seeds/export_from_supabase.py); se omite")
        return
    for csv_path in csvs:
        table = csv_path.stem
        table_id = f"{project}.{DATASETS['dim']}.{table}"
        ddl = HERE / "tables" / f"{table}.sql"
        schema = schema_from_ddl(ddl, project) if ddl.exists() else None
        with csv_path.open(encoding="utf-8", newline="") as fh:
            n_rows = max(sum(1 for _ in csv.reader(fh)) - 1, 0)
        if dry_run:
            how = f"esquema de tables/{table}.sql ({len(schema)} cols)" if schema else "autodetect"
            log(f"[seeds] (dry-run) {csv_path.name} -> {table_id} WRITE_TRUNCATE, {n_rows} filas, {how}")
            continue
        cfg = bigquery.LoadJobConfig(
            source_format=bigquery.SourceFormat.CSV,
            skip_leading_rows=1,
            write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
            allow_quoted_newlines=True,
        )
        if schema:
            cfg.schema = schema
        else:
            cfg.autodetect = True
        with csv_path.open("rb") as fh:
            job = client.load_table_from_file(fh, table_id, job_config=cfg)
        job.result()
        log(f"[seeds] OK {csv_path.name} -> {table_id} ({job.output_rows} filas)")
    # trazabilidad: actualiza last_loaded_at de los seeds en dim_data_sources si la tabla/columna existe
    ds_table = f"{project}.{DATASETS['dim']}.dim_data_sources"
    if not dry_run and table_exists(client, ds_table):
        keys = ", ".join(f"'{c.stem}'" for c in csvs)
        try:
            run_sql(
                client,
                f"UPDATE `{ds_table}` SET last_loaded_at = CURRENT_TIMESTAMP(), last_loaded_by = 'apply.py' "
                f"WHERE dataset_key IN ({keys})",
                "seeds/dim_data_sources.last_loaded_at",
                dry_run,
            )
        except Exception as e:  # noqa: BLE001 - no bloquea el despliegue
            log(f"[seeds] aviso: no se pudo actualizar dim_data_sources.last_loaded_at: {e}")


def apply_views_and_marts(client, project: str, dry_run: bool, with_marts: bool) -> None:
    objs = load_objects(HERE / "views", "view") | load_objects(HERE / "marts", "mart")
    resolve_deps(objs)
    order = topo_order(objs)
    failures: list[str] = []
    for o in order:
        label = f"{o.kind}s/{o.path.name}"
        if o.unknown:
            log(f"[sql] AVISO {label} depende de objetos pendientes de dump: {sorted(o.unknown)}")
        if o.kind == "mart":
            table_id = f"{project}.{DATASETS['mart']}.{o.name}"
            if not with_marts and (dry_run or table_exists(client, table_id)):
                log(f"[sql] skip {label} (mart ya existe o dry-run; usar --with-marts para reconstruir)")
                continue
            if not with_marts:
                log(f"[sql] bootstrap {label} (no existía; lo necesitan sus vistas)")
        try:
            run_sql(client, render(o.sql, project), label, dry_run)
        except Exception as e:  # noqa: BLE001
            failures.append(f"{label}: {str(e).splitlines()[0]}")
            log(f"[sql] ERROR {label}: {str(e).splitlines()[0]}")
    if failures:
        raise ApplyError(f"{len(failures)} objeto(s) fallaron:\n  " + "\n  ".join(failures))


def apply_functions(client, project: str, dry_run: bool) -> None:
    files = sql_files(HERE / "functions")
    if not files:
        log("[functions] sin *.sql (f_sec05_* pendientes de dump, ver functions/_PENDIENTES_DUMP.md)")
        return
    for p in files:
        run_sql(client, render(p.read_text(encoding="utf-8"), project), f"functions/{p.name}", dry_run)


def apply_marts(client, project: str, dry_run: bool) -> None:
    """Reconstrucción de todos los marts en el orden de refresh_order.txt (paso `marts` del job)."""
    marts = load_objects(HERE / "marts", "mart")
    names = read_refresh_order(HERE / "marts" / "refresh_order.txt")
    missing = [n for n in names if n not in marts]
    if missing:
        raise ApplyError(f"refresh_order.txt nombra marts sin .sql: {missing}")
    for n in names:
        run_sql(client, render(marts[n].sql, project), f"marts/{n}.sql", dry_run)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", default=DEFAULT_PROJECT)
    ap.add_argument("--location", default=DEFAULT_LOCATION)
    ap.add_argument("--dry-run", action="store_true", help="QueryJobConfig(dry_run=True); no escribe nada")
    ap.add_argument("--only", default=None, help="pasos separados por coma: " + "|".join(STEPS))
    ap.add_argument("--with-marts", action="store_true", help="reconstruye las tablas mv_* (ademas de crear las que falten)")
    ap.add_argument("--parse-check", action="store_true", help="sin GCP: valida sintaxis BigQuery de todos los .sql con sqlglot")
    args = ap.parse_args(argv)

    if args.parse_check:
        return parse_check(args.project)

    steps = list(STEPS[:-1])  # marts sólo explícito
    if args.only:
        steps = [s.strip() for s in args.only.split(",") if s.strip()]
        bad = [s for s in steps if s not in STEPS]
        if bad:
            ap.error(f"pasos desconocidos {bad}; válidos: {', '.join(STEPS)}")
    if args.with_marts and "marts" not in steps and not args.only:
        steps.append("marts")

    try:
        client = bq_client(args.project, args.location)
    except Exception as e:  # noqa: BLE001
        log(f"[apply] no se pudo crear el cliente BigQuery ({e}). Sin credenciales use --parse-check.")
        return 2

    log(f"[apply] proyecto={args.project} location={args.location} pasos={steps} dry_run={args.dry_run}")
    try:
        ensure_datasets(client, args.project, args.location, args.dry_run)
        for step in steps:
            log(f"\n=== {step} ===")
            if step == "tables":
                apply_tables(client, args.project, args.dry_run)
            elif step == "seeds":
                apply_seeds(client, args.project, args.dry_run)
            elif step == "views":
                apply_views_and_marts(client, args.project, args.dry_run, args.with_marts)
            elif step == "functions":
                apply_functions(client, args.project, args.dry_run)
            elif step == "marts":
                apply_marts(client, args.project, args.dry_run)
    except ApplyError as e:
        log(f"\n[apply] FALLO: {e}")
        return 1
    except Exception as e:  # noqa: BLE001
        log(f"\n[apply] FALLO inesperado: {type(e).__name__}: {e}")
        return 1
    log("\n[apply] OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
