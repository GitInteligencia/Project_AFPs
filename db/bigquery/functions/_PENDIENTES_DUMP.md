# Table functions `f_sec05_*` pendientes de dump

Las 4 RPC de Sec 05 (Chilean Stocks) son funciones SQL `RETURNS TABLE` en Supabase cuyo cuerpo **no está en el repo**
(se reescribieron en la migración a "SQL vivo" 2026-07-01, PLAN_SQL_SINGLE_SOURCE.md fase 4). Se traducen a
`CREATE OR REPLACE TABLE FUNCTION` cuando exista `db/supabase_snapshot/schema.sql` (`pg_get_functiondef`).

Fuentes que usan (LINEAGE.md): `ipd_cartera_eom` (Pionero `id_fund=33`, MRV `id_fund=19`, `investment_type_code=2`),
`ipd_bms_membership` (IGPA 16, IGPAL 17, IGPAM 18, IGPAS 19, IPSA 20), `v_chilean_stocks_gics` (AFPs, CHIST) y
`dim_bdchile` (solo company / grupo). La web llama las 4 con el mismo parámetro `p_fecha` (`web/lib/queries-sec05.ts`) y
resuelve por separado la fecha efectiva de cada fuente (`getSec05ResolvedFechas`: última fecha `<= p_fecha` por fuente),
por lo que es esperable que cada función haga internamente `MAX(fecha) WHERE fecha <= p_fecha` por fuente.

## Firmas esperadas (nombres y columnas exactos que consume la web: `web/lib/types-sec05.ts`)

| Función | Parámetros | Columnas de salida | Notas |
|---|---|---|---|
| `f_sec05_size` | `p_fecha DATE` | `bucket STRING` ('Large' \| 'Mid' \| 'Small' \| 'No IGPA'), `pionero_pct FLOAT64`, `mrv_pct FLOAT64`, `ipsa_pct FLOAT64`, `afps_pct FLOAT64` | Size = pertenencia a IGPA Large/Mid/Small (BMS 17/18/19). Reemplazó a `f_sec05_quartile`. |
| `f_sec05_ipsa_membership` | `p_fecha DATE` | `bucket STRING` ('IPSA' \| 'NO IPSA'), `pionero_pct`, `mrv_pct`, `ipsa_pct`, `afps_pct` (FLOAT64) | Pertenencia a IPSA (BMS 20). |
| `f_sec05_concentration` | `p_fecha DATE` | `metric STRING` ('companies' \| 'top10' \| 'top20' \| 'top30'), `pionero FLOAT64`, `mrv FLOAT64`, `ipsa FLOAT64`, `afps FLOAT64` | `companies` = # emisores; `topN` = peso acumulado de los N mayores. |
| `f_sec05_top40` | `p_fecha DATE` | `rk INT64`, `nemo STRING`, `emisor STRING`, `company_name STRING`, `group_name STRING`, `size_bucket STRING`, `gics_name STRING`, `gics_chist STRING`, `monto_usd_mm NUMERIC`, `weight FLOAT64` | Consolida por emisor; el `nemo` mostrado es el de **mayor monto** de la compañía (fix 5.2, Ajustes_Dashboard.md). Devuelve 40 filas. |

La web hace `Number(x) || 0` sobre cada columna numérica y trata como `string | null` las de texto, así que los tipos
exactos (NUMERIC vs FLOAT64) no la rompen; para la paridad (§12) sí importa reproducir el tipo de Postgres:
`numeric` → NUMERIC, `double precision` → FLOAT64.

## Diferencias Postgres → BigQuery a tener en cuenta al traducir el cuerpo
- `LANGUAGE sql STABLE`, `SECURITY DEFINER`, `GRANT EXECUTE` → no aplican; permisos vía IAM sobre el dataset.
- El parámetro se usa como `p_fecha` dentro del cuerpo (mismo nombre, sin `$1`).
- `RETURNS TABLE (...)` → BigQuery infiere el esquema del `SELECT`; usar `CAST` explícitos para fijar tipos y **el mismo
  orden de columnas**.
- Sin `ORDER BY` garantizado en la salida de una table function: si la web depende del orden (`rk`), añadir el `ORDER BY`
  en la consulta que la invoca (`SELECT * FROM f_sec05_top40(@p_fecha) ORDER BY rk`) — la paridad (§12) compara "mismas filas,
  mismo orden", así que `compare_bq_vs_supabase.py` ordena por `rk`/`bucket`/`metric` antes de comparar.
- Invocación desde la web: ``SELECT * FROM `${project}.${mart}.f_sec05_size`(@p_fecha)`` con `@p_fecha` DATE parametrizado.

## Plantilla

Ver `_TEMPLATE_table_function.sql.txt` en esta carpeta (extensión `.txt` para que `apply.py` no intente aplicarla).
Al crear la función real, copiarla a `f_sec05_<nombre>.sql`, reemplazar el cuerpo y quitar los comentarios TODO.
