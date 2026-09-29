-- Mart afp_mart.mv_consolidated_foreign_pdf_summary  (traducido 1:1 de sync/v_foreign_consolidated_switch.sql)
-- Resumen Foreign Sec 07 (lado fresco consolidated_sd) por fecha_reporte x buckets legacy y nt_*.
-- Alimenta v_foreign_pdf_summary_combined (ramas 1 y 4). Debe reconstruirse tras el paso `consolidated_sd`.
CREATE OR REPLACE TABLE `${project}.${mart}.mv_consolidated_foreign_pdf_summary`
PARTITION BY DATE_TRUNC(fecha_reporte, MONTH)
CLUSTER BY pdf_bucket
OPTIONS (description = 'Resumen Foreign PDF desde consolidated_sd (snapshot). Reconstruida por el job afp-sync, paso marts.')
AS
SELECT fecha_reporte, pdf_bucket, pdf_em_dm, pdf_subregion, pdf_fi_category,
       pdf_bucket_nt, pdf_em_dm_nt, pdf_subregion_nt, pdf_fi_category_nt,
       SUM(monto_dolares) AS monto_usd_mm
FROM `${project}.${mart}.v_consolidated_foreign_pdf`
GROUP BY fecha_reporte, pdf_bucket, pdf_em_dm, pdf_subregion, pdf_fi_category,
         pdf_bucket_nt, pdf_em_dm_nt, pdf_subregion_nt, pdf_fi_category_nt;
