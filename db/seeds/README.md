# `db/seeds/` — tablas manuales de Supabase versionadas

Las tablas de `afp_dim` que **no tienen fuente en SQL Server** (PLAN_MIGRACION_GCP.md §1.3.2 y §6.2) se exportan
desde Supabase a CSV, se versionan aquí y se cargan a BigQuery con `apply.py`. Editar el CSV en un PR sustituye a
editar la tabla en el panel de Supabase (gana trazabilidad).

## Tablas (11 de §6.2)

| CSV | Tabla BigQuery | DDL | Uso |
|---|---|---|---|
| `dim_valorizacion_remanente.csv` | `afp_dim.dim_valorizacion_remanente` | `db/bigquery/tables/dim_valorizacion_remanente.sql` (esquema a confirmar) | legacy Alternatives (sin consumidores vigentes) |
| `dim_chilean_ticker_homol.csv` | `afp_dim.dim_chilean_ticker_homol` | `…/dim_chilean_ticker_homol.sql` | `v_chilean_stocks_gics` (nemo → ticker BBG) |
| `dim_chilean_stocks_gics_override.csv` | `afp_dim.dim_chilean_stocks_gics_override` | `…/dim_chilean_stocks_gics_override.sql` | `v_chilean_stocks_gics` |
| `dim_foreign_region_override.csv` | `afp_dim.dim_foreign_region_override` | `…/dim_foreign_region_override.sql` | `v_consolidated_foreign_classified` |
| `dim_distributor_by_manager.csv` | `afp_dim.dim_distributor_by_manager` | `…/dim_distributor_by_manager.sql` | admin Distributors (web) |
| `dim_strategy_ipd_funds.csv` | `afp_dim.dim_strategy_ipd_funds` | `…/dim_strategy_ipd_funds.sql` | Strategy 4.1/4.2 (web) |
| `dim_sec08_top_flows.csv` | `afp_dim.dim_sec08_top_flows` | `…/dim_sec08_top_flows.sql` | Sec 08 (web) |
| `dim_bdchile.csv` | `afp_dim.dim_bdchile` | `…/dim_bdchile.sql` (esquema a confirmar) | `f_sec05_top40` (company / grupo) |
| `dim_direct_investment_overlay.csv` | `afp_dim.dim_direct_investment_overlay` | `…/dim_direct_investment_overlay.sql` | `v_sp_direct_investment_detail` |
| `dim_foreign_classification_overlay.csv` | `afp_dim.dim_foreign_classification_overlay` | `…/dim_foreign_classification_overlay.sql` | Foreign (category/region) y Distributors (family/manager) |
| `dim_data_sources.csv` | `afp_dim.dim_data_sources` | `…/dim_data_sources.sql` | `SourceBadge` (web); `apply.py` actualiza `last_loaded_at` al recargar |

Extra (`--extra`): `dim_ipd_gics.csv`, `dim_ipd_instrumentos.csv`. Las carga `sync/sync_inteligencia_producto.py`,
que **no** forma parte de los 8 pasos de `main.py`; `v_chilean_stocks_gics` las necesita, así que hasta que el
pipeline las incluya se tratan como seed.

## Exportar (F0, y otra vez antes del corte F6)

```bash
pip install supabase pandas python-dotenv
# .env con SUPABASE_URL y SUPABASE_SERVICE_ROLE_KEY (mismas variables que el sync)
python db/seeds/export_from_supabase.py --extra
```

Genera `<tabla>.csv` (UTF-8, cabecera, `NULL` → celda vacía, orden estable por la clave lógica) y `_manifest.json`
con filas/columnas/timestamp. Paginación de 1 000 filas (tope PostgREST). Sale con `rc != 0` si alguna tabla falla.

Revisar el manifest contra `LINEAGE.md` (p. ej. `dim_chilean_ticker_homol` = 75 filas, `dim_valorizacion_remanente` = 16).

## Cargar a BigQuery

```bash
python db/bigquery/apply.py --only tables,seeds            # crea las tablas si faltan y hace WRITE_TRUNCATE de cada CSV
python db/bigquery/apply.py --only seeds --dry-run         # solo informa qué cargaría
```

- Esquema: `apply.py` lo toma de `db/bigquery/tables/<tabla>.sql` (vía sqlglot); si no hay DDL usa `autodetect`.
- Los CSV deben tener **las mismas columnas que el DDL** (nombre y orden). Si el export trae columnas que el DDL no
  conoce (marcadas `TODO(dump)` en el .sql), actualizar primero el DDL.
- Celda vacía = `NULL` para todos los tipos (comportamiento por defecto del load CSV de BigQuery).
- `dim_data_sources.last_loaded_at` / `last_loaded_by='apply.py'` se actualizan para los `dataset_key` recargados.

## Mantenimiento posterior

1. Editar el CSV en una rama → PR (revisión del dato) → merge.
2. El workflow `deploy-bq.yml` (F5) corre `apply.py --only seeds` (idempotente, reemplaza la tabla completa).
3. No editar las tablas de `afp_dim` a mano en la consola: el próximo deploy las pisa con el CSV.

`_manifest.json` y los CSV se versionan; **no** contienen credenciales ni datos personales.
