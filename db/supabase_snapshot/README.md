# `db/supabase_snapshot/` — captura del esquema Supabase (F0)

Objetivo: tener en el repo **la fuente canónica** para traducir a BigQuery los objetos que hoy sólo existen en
Supabase (PLAN_MIGRACION_GCP.md §1.3.1, F0.1–F0.2). Los `sync/*.sql` son migrations incrementales, no el estado final.

Artefactos a generar en esta carpeta:

| Archivo | Contenido | Quién lo consume |
|---|---|---|
| `schema.sql` | DDL completo de `public`: tablas, vistas (`pg_get_viewdef`), matviews, funciones (`pg_get_functiondef`), índices | traducción de `db/bigquery/{views,marts,functions}` y confirmación de los `TODO(dump)` en `db/bigquery/tables` |
| `deps.csv` | grafo `dependiente → objeto base` desde `pg_depend`/`pg_rewrite` | orden topológico, detectar huérfanos, `_PENDIENTES_DUMP.md` |
| `sizes.csv` | tamaño por tabla (`pg_total_relation_size`) | perfil F0.4 |

Proyecto Supabase: `ProjectAFP_v2` (`vmehawqqhcyhxyaoznpc`). **Nunca** versionar la connection string ni las keys.

---

## Opción A — `pg_dump` (preferida; requiere red sin bloqueo del puerto 5432/6543)

La red Patria bloquea Postgres directo (por eso el sync usa REST). Ejecutar desde una red doméstica / hotspot, o
desde una Cloud Shell. Connection string: Supabase → *Project Settings → Database → Connection string (URI)*,
modo *Session* (puerto 5432) para que `pg_dump` funcione. La versión de `pg_dump` debe ser ≥ la del servidor (Supabase
usa Postgres 15/17; `pg_dump` 17 sirve para ambos).

```bash
export PGURI='postgresql://postgres.<ref>:<PASSWORD>@aws-0-<region>.pooler.supabase.com:5432/postgres'

# 1) Esquema completo de public (sin datos, sin owners/privilegios, sin RLS policies -> no aplican en BigQuery)
pg_dump "$PGURI" \
  --schema-only --schema=public \
  --no-owner --no-privileges --no-security-labels --no-tablespaces --no-comments=false \
  --file db/supabase_snapshot/schema.sql

# 2) Grafo de dependencias (ver query abajo) y tamaños
psql "$PGURI" -At -F ',' -f db/supabase_snapshot/deps.sql   > db/supabase_snapshot/deps.csv
psql "$PGURI" -At -F ',' -f db/supabase_snapshot/sizes.sql  > db/supabase_snapshot/sizes.csv
```

Revisar `schema.sql` antes de commitear: no debe contener contraseñas ni `auth.*`. `--schema=public` ya excluye
`auth`, `storage`, etc.

---

## Opción B — desde el SQL editor de Supabase (sin acceso al puerto de Postgres)

Ejecutar cada query en el SQL editor, descargar el resultado como CSV/texto y pegar/concatenar en `schema.sql`
respetando el orden: **tablas → vistas/matviews → funciones**.

### B.1 Tablas (columnas y tipos exactos)

```sql
SELECT table_name, ordinal_position, column_name, data_type,
       character_maximum_length, numeric_precision, numeric_scale, is_nullable, column_default
FROM information_schema.columns
WHERE table_schema = 'public'
ORDER BY table_name, ordinal_position;
```

y las claves / índices:

```sql
SELECT tablename, indexname, indexdef FROM pg_indexes WHERE schemaname = 'public' ORDER BY 1, 2;
SELECT conrelid::regclass AS tabla, conname, pg_get_constraintdef(oid) AS def
FROM pg_constraint WHERE connamespace = 'public'::regnamespace ORDER BY 1, 2;
```

### B.2 Vistas y matviews (DDL reconstruido)

```sql
SELECT format('CREATE OR REPLACE VIEW public.%I AS%s%s', c.relname, E'\n', pg_get_viewdef(c.oid, true)) AS ddl
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind = 'v'
ORDER BY c.relname;

SELECT format('CREATE MATERIALIZED VIEW public.%I AS%s%s;', c.relname, E'\n', pg_get_viewdef(c.oid, true)) AS ddl
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind = 'm'
ORDER BY c.relname;
```

### B.3 Funciones (las 4 `f_sec05_*` y `refresh_alternatives_matviews`)

```sql
SELECT pg_get_functiondef(p.oid) || ';' AS ddl
FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = 'public'
ORDER BY p.proname;
```

### B.4 Tipos de las columnas de salida de vistas/funciones (útil para fijar NUMERIC vs FLOAT64)

```sql
SELECT table_name, column_name, data_type
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name LIKE 'v\_%'
ORDER BY table_name, ordinal_position;
```

---

## `deps.sql` — grafo de dependencias (`pg_depend` / `pg_rewrite`)

Guardar como `db/supabase_snapshot/deps.sql`; salida CSV con cabecera
`dependent,dependent_kind,source,source_kind`.

```sql
SELECT 'dependent,dependent_kind,source,source_kind'
UNION ALL
SELECT DISTINCT
       dv.relname
       || ',' || CASE dv.relkind WHEN 'v' THEN 'view' WHEN 'm' THEN 'matview' ELSE dv.relkind::text END
       || ',' || sc.relname
       || ',' || CASE sc.relkind WHEN 'r' THEN 'table' WHEN 'v' THEN 'view' WHEN 'm' THEN 'matview' ELSE sc.relkind::text END
FROM pg_depend d
JOIN pg_rewrite  rw ON rw.oid = d.objid
JOIN pg_class    dv ON dv.oid = rw.ev_class          -- vista/matview dependiente
JOIN pg_class    sc ON sc.oid = d.refobjid           -- objeto del que depende
JOIN pg_namespace nd ON nd.oid = dv.relnamespace
JOIN pg_namespace ns ON ns.oid = sc.relnamespace
WHERE d.classid = 'pg_rewrite'::regclass
  AND d.refclassid = 'pg_class'::regclass
  AND d.deptype = 'n'
  AND nd.nspname = 'public' AND ns.nspname = 'public'
  AND dv.oid <> sc.oid
ORDER BY 1;
```

Dependencias de las **funciones** (no están en `pg_rewrite`; se obtienen leyendo el cuerpo):

```sql
SELECT p.proname AS function, c.relname AS source,
       CASE c.relkind WHEN 'r' THEN 'table' WHEN 'v' THEN 'view' WHEN 'm' THEN 'matview' END AS source_kind
FROM pg_proc p
JOIN pg_namespace n ON n.oid = p.pronamespace
JOIN pg_class c ON c.relnamespace = n.oid AND c.relkind IN ('r','v','m')
WHERE n.nspname = 'public' AND p.proname LIKE 'f\_sec05\_%'
  AND pg_get_functiondef(p.oid) ~ ('\m' || c.relname || '\M')
ORDER BY 1, 2;
```

Con `deps.csv` se ordena la traducción: todo lo que aparezca como `source` de tipo `view`/`matview` de un objeto
leído por la web debe existir en `db/bigquery/{views,marts}`; lo que no tenga dependientes ni lo lea la web es huérfano
(candidato a **no** migrar, ver `db/bigquery/views/_PENDIENTES_DUMP.md`).

## `sizes.sql` — perfil de tamaño (F0.4)

```sql
SELECT 'table,rows_estimate,total_bytes,total_pretty'
UNION ALL
SELECT c.relname || ',' || c.reltuples::bigint || ',' || pg_total_relation_size(c.oid)
       || ',' || pg_size_pretty(pg_total_relation_size(c.oid))
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind IN ('r','m')
ORDER BY 1;
```

## Después de generar los archivos

1. Cerrar los `TODO(dump)` de `db/bigquery/tables/*.sql` comparando con B.1.
2. Traducir los objetos listados en `db/bigquery/views/_PENDIENTES_DUMP.md`, `db/bigquery/marts/_PENDIENTES_DUMP.md`
   y `db/bigquery/functions/_PENDIENTES_DUMP.md`.
3. Verificar que las vistas ya traducidas coinciden con `pg_get_viewdef` (las `sync/*.sql` pueden haber quedado
   detrás de alguna migration aplicada sólo en Supabase: p. ej. `v_module_freshness` → `ipd_positions`).
4. `python db/bigquery/apply.py --parse-check`.
