# Vistas pendientes de dump

Vistas leídas por la web (o intermedias de ellas) **sin DDL en `sync/*.sql`**. Se traducen cuando exista
`db/supabase_snapshot/schema.sql` (F0, `pg_get_viewdef`). Las columnas listadas son las que la web consume
(`web/lib/queries-*.ts`, `web/lib/types-*.ts`); el dump puede traer más, se conservan todas.

## Leídas directamente por la web

| Vista | Columnas que la web usa | Filtros / orden que aplica la web | Cadena (LINEAGE.md) | Estado |
|---|---|---|---|---|
| `v_returns_afp_tipo` | `fecha`, `afp`, `tipo_fondo`, `aum_usd_mm`, `aum_clp_bn`, `ret_mom_clp`, `ret_ytd_clp`, `ret_ltm_clp`, `ret_mom_usd`, `ret_ytd_usd`, `ret_ltm_usd`, `valor_cuota`, `fx_clp_per_usd`, `flow_mom_usd_mm`, `flow_ytd_usd_mm`, `flow_ltm_usd_mm` | `fecha >= '2025-01-01'`, `eq fecha`, order `fecha`; 7 AFP + `TOTAL` × A–E + `TOTAL` (42 filas/fecha) | `v_returns_afp_tipo → mv_returns_afp_tipo → v_cuota_month_end + v_daily_flows → valores_cuota_patrimonio, tipo_cambio` | **dump**. También la necesita `v_contributors_market_share` (ya traducida). |
| `v_asset_class_dates_sd` | `fecha_valor` | `fecha_valor >= '2025-01-01'`, order desc | `sd_asset_class_tipo` | **dump** (trivial). Propuesta a confirmar: `SELECT DISTINCT fecha AS fecha_valor FROM ${raw}.sd_asset_class_tipo`. |
| `v_local_fi_by_afp_sd` | `afp`, `fecha_reporte`, `pdf_bucket`, `pdf_order`, `monto_usd_mm` | `eq fecha_reporte` | `sd_asset_class_afp` | **dump**. Buckets esperados (`types-asset-allocation.ts::LOCAL_FI_BUCKETS`): Central Bank, Treasury, Banks, Corporates, Fixed-term Deposit, Other. El mapeo `glosa → bucket` y `pdf_order` solo están en Supabase. |
| `v_local_equity_di_vs_if_combined` | `fecha_reporte`, `direct_clp_bn`, `funds_clp_bn`, `funds_clp_bn_nt`, `total_clp_bn`, `total_clp_bn_nt`, `source` ('CHIST'\|'SP_XML') | order `fecha_reporte` | rama CHIST (≤ 2026-01, históricamente `historial_carteras_full`, hoy dropeada → debe leer `chist_adjusted`) `UNION ALL` rama fresca `v_sp_local_equity_di_vs_if` (**ya traducida**) | **dump** (la rama CHIST y el `total_*`). |
| `v_foreign_returns_flows_summary` | `fecha_reporte`, `pdf_bucket`, `pdf_em_dm`, `pdf_subregion`, `pdf_fi_category`, `pdf_bucket_nt`, `pdf_em_dm_nt`, `pdf_subregion_nt`, `pdf_fi_category_nt`, `return_usd_mm`, `flow_usd_mm` | `fecha_reporte > 3Y AND <= fecha`, paginado | `→ mv_foreign_returns_flows_summary → v_foreign_returns_flows` (**ya traducida**) | **dump** (probable wrapper `SELECT * FROM mv_…`). |
| `v_foreign_fund_flows` | `fecha_reporte`, `fund_id`, `fondo`, `manager`, `flow_usd_mm` | `fecha_reporte > ytd AND <= fecha`, paginado | `→ mv_foreign_fund_flows → v_foreign_returns_flows` (**ya traducida**) + `dim_homol_funds`/`dim_bd_funds` | **dump**. |

## Intermedias sin DDL (referenciadas por vistas ya traducidas o por las de arriba)

| Vista | Quién la referencia | Fuente esperada | Notas |
|---|---|---|---|
| `v_foreign_pdf_summary` | `v_foreign_pdf_summary_combined` (rama 2, fallback CHIST — **bloquea su creación en BigQuery**) | `mv_foreign_pdf_summary` (pendiente) | Columnas: las 9 de buckets + `monto_usd_mm`, `fecha_reporte`. |
| `v_chist_foreign_pdf` | `mv_foreign_pdf_summary`, `v_foreign_latam_monthly` (según comentario en `sync/v_foreign_chist_switch.sql`) | `v_chist_foreign_classified` (**ya traducida**) | Misma lógica de buckets que `v_consolidated_foreign_pdf` pero con FX USDCLP sobre `inversion` CLP y bucket `'Excluded Derivatives'`. |
| `v_foreign_latam_monthly` | `mv_foreign_latam_monthly` (pendiente) | `v_chist_foreign_pdf`/`v_chist_foreign_classified` + `dim_bd_funds.style` | Columnas: `fecha_reporte`, `pdf_bucket`, `style_group`, `monto_usd_mm`. |
| `v_cuota_month_end`, `v_daily_flows` | `mv_returns_afp_tipo` (pendiente) | `valores_cuota_patrimonio`, `tipo_cambio` | Matemática de cuota/flujos de Market Share. |

## Vistas que NO hay que migrar (dropeadas en Supabase según las migrations del repo)

`v_sp_cartera_fondo`, `v_sp_cartera_afp`, `v_sp_emisor_nacional`, `v_sp_fi_local`, `v_sp_extranjero_grupo`,
`v_sp_emisor_extranjero`, `v_sp_foreign_classified`, `v_sp_foreign_pdf`, `v_sp_foreign_managers`, `v_sp_foreign_pdf_summary`,
`v_sp_foreign_by_fund`, `v_foreign_by_fund_combined`, `v_chilean_stocks_by_issuer_combined`, `v_sp_asset_class_*`, `v_sp_aum_afp`,
`v_sp_chilean_stocks_by_issuer`, `v_sp_local_equity_di_vs_if` (¡esta sí está vigente, ver arriba, no confundir con las `v_sp_*` dropeadas!),
`v_local_fi_by_afp`, `v_sp_extranjero_grupo` (todas sobre las tablas `sp_*` dropeadas en `sync/v_freshness_repoint_and_reclaim.sql`).
Confirmar con `deps.csv` que no reaparecen.

## Cómo cerrar cada pendiente
1. `pg_get_viewdef('public.<vista>', true)` desde `schema.sql`.
2. Traducir con la guía PLAN §7 (y el patrón de las vistas ya traducidas en esta carpeta: cabecera en español,
   archivo Postgres de origen, lista de traducciones no obvias).
3. Referencias: `${project}.${raw}.x`, `${project}.${dim}.x`, `${project}.${mart}.x`.
4. `python db/bigquery/apply.py --parse-check` y luego `--dry-run` contra el proyecto.
5. Añadir el objeto a la paridad (`validation/objects.py`) si no estaba.
