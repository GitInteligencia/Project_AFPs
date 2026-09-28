# Marts (`mv_*`) pendientes de dump

Matviews de Supabase **sin `CREATE MATERIALIZED VIEW` en `sync/*.sql`** (solo aparecen en `REFRESH` o en LINEAGE.md).
Se traducen a `CREATE OR REPLACE TABLE ${project}.${mart}.mv_x PARTITION BY … CLUSTER BY … AS SELECT …` cuando exista
`db/supabase_snapshot/schema.sql` (F0). Al crearlas, descomentar su línea en `refresh_order.txt`.

| Matview | Columnas que la web / otras vistas esperan | Fuente (LINEAGE.md / comentarios en sync) | Notas para la traducción |
|---|---|---|---|
| `mv_returns_afp_tipo` | ver `v_returns_afp_tipo` en `views/_PENDIENTES_DUMP.md` | `v_cuota_month_end` + `v_daily_flows` sobre `valores_cuota_patrimonio` + `tipo_cambio` | Base de Market Share. Cuota de cierre de mes, retornos MoM/YTD/LTM CLP y USD, flujos = Δpatrimonio − retorno. Incluye filas `afp='TOTAL'` y `tipo_fondo='TOTAL'` (la web filtra `afp <> 'TOTAL'`). |
| `mv_foreign_fund_flows` | `fecha_reporte`, `fund_id`, `fondo`, `manager`, `flow_usd_mm` | `v_foreign_returns_flows` (traducida) agregada a fondo vía `dim_homol_funds → dim_bd_funds` (share classes consolidadas) | Ver comentario "PDF Sec 08 methodology" en `web/lib/queries-foreign.ts`. |
| `mv_foreign_returns_flows_summary` | `fecha_reporte`, `pdf_bucket`, `pdf_em_dm`, `pdf_subregion`, `pdf_fi_category`, `pdf_bucket_nt`, `pdf_em_dm_nt`, `pdf_subregion_nt`, `pdf_fi_category_nt`, `return_usd_mm`, `flow_usd_mm` | `v_foreign_returns_flows` (traducida), `GROUP BY` los 9 buckets con `SUM(return_usd_mm)`, `SUM(flow_usd_mm)` | Hipótesis fuerte (misma forma que `mv_consolidated_foreign_pdf_summary`); confirmar. |
| `mv_sp_direct_investment_summary` | `fecha_reporte`, `pdf_bucket`, `pdf_em_dm`, `pdf_subregion`, `pdf_fi_category`, `monto_usd_mm` (rama 3 de `v_foreign_pdf_summary_combined`) | `v_sp_direct_investment_detail` (traducida) | Hipótesis: `pdf_bucket='Direct Investment'`, `pdf_em_dm` por `region` (mismas listas EM/DM), `pdf_subregion=region`, `pdf_fi_category=di_category`, `fecha_reporte=fecha_valor`, `SUM(usd_mm)`. **Bloquea** `v_foreign_pdf_summary_combined`. |
| `mv_foreign_pdf_summary` | mismas 9 columnas de buckets + `monto_usd_mm` (rama 2 CHIST de `v_foreign_pdf_summary_combined`) | `v_chist_foreign_pdf` (pendiente) sobre `v_chist_foreign_classified` (traducida) + `tipo_cambio` USDCLP; `WHERE pdf_bucket <> 'Excluded Derivatives'` | Fallback CHIST "none in practice" según `sync/v_foreign_consolidated_switch.sql`. **Bloquea** `v_foreign_pdf_summary_combined` (junto con la anterior). |
| `mv_foreign_latam_monthly` | `fecha_reporte`, `pdf_bucket`, `style_group` ('Active'/'ETF'/'Passive'), `monto_usd_mm` | `v_foreign_latam_monthly` (pendiente) ← históricamente `historial_carteras_full` + `tipo_cambio` + overlays; hoy debe leer `chist_adjusted` (tabla dropeada) | Sec 07 pág. 9 "Latam Evolution" (`web/lib/queries-foreign-latam.ts`). |
| `mv_chist_chilean_stocks_by_nemo` | `fecha_reporte`, `nemo`, `emisor`, `inv_clp`, `price_clp` | `chist_adjusted` acciones nacionales (`tipo_de_instrumento='ACC'`), migrada en PLAN_SQL_SINGLE_SOURCE.md ("✅") | Tarjeta Transactions de /chilean-stocks (`web/lib/queries-chilean-stocks.ts`). Probable: `SUM(inversion) AS inv_clp`, precio agregado por nemo. |
| `mv_chist_foreign_by_fund` | — (no la lee la web) | `v_chist_foreign_classified` | Solo aparece en `REFRESH` (`sync/v_foreign_chist_switch.sql`). Verificar en `deps.csv` si tiene dependientes; si no, **no migrar**. |
| `mv_chist_foreign_units_by_nemo` | — (no la lee la web) | `v_chist_foreign_classified` | Ídem. |

Al traducir, seguir la guía PLAN §7 y el patrón de los marts ya escritos (cabecera en español con el archivo Postgres de
origen, `PARTITION BY DATE_TRUNC(<fecha>, MONTH)`, `CLUSTER BY` las claves de filtro de la web).
