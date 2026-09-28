-- Vista afp_mart.v_foreign_pdf_summary_combined  (traducida 1:1 de sync/v_foreign_consolidated_switch.sql)
-- Resumen Foreign Sec 07 combinado: (1) buckets frescos de consolidated_sd, (2) fallback CHIST solo para fechas
-- que consolidated no cubre, (3) Direct Investment desde mv_sp_direct_investment_summary, (4) Private Equity consolidado.
-- !! DEPENDE de 2 objetos SIN DDL en el repo (ver db/bigquery/views/_PENDIENTES_DUMP.md y marts/_PENDIENTES_DUMP.md):
--    ${mart}.v_foreign_pdf_summary  y  ${mart}.mv_sp_direct_investment_summary. Hasta que existan en BigQuery
--    esta vista NO se puede crear (apply.py la reportara como fallo de dependencia).
-- Traducciones: x <> ALL (ARRAY[a,b]) -> x NOT IN (a,b)  (misma semantica NULL);  ::text/::varchar -> CAST AS STRING;
--   ::numeric -> CAST AS NUMERIC;  NOT IN (SELECT DISTINCT ...) se mantiene (BigQuery lo soporta).
CREATE OR REPLACE VIEW `${project}.${mart}.v_foreign_pdf_summary_combined` AS
-- (1) buckets frescos no-DI/PE desde consolidated_sd
SELECT CAST(s.fecha_reporte AS DATE) AS fecha_reporte,
       CAST(s.pdf_bucket AS STRING) AS pdf_bucket, CAST(s.pdf_em_dm AS STRING) AS pdf_em_dm,
       CAST(s.pdf_subregion AS STRING) AS pdf_subregion, CAST(s.pdf_fi_category AS STRING) AS pdf_fi_category,
       CAST(s.pdf_bucket_nt AS STRING) AS pdf_bucket_nt, CAST(s.pdf_em_dm_nt AS STRING) AS pdf_em_dm_nt,
       CAST(s.pdf_subregion_nt AS STRING) AS pdf_subregion_nt, CAST(s.pdf_fi_category_nt AS STRING) AS pdf_fi_category_nt,
       CAST(s.monto_usd_mm AS NUMERIC) AS monto_usd_mm, 'SP_XML' AS source
FROM `${project}.${mart}.mv_consolidated_foreign_pdf_summary` s
WHERE s.pdf_bucket NOT IN ('Direct Investment','Private Equity')
UNION ALL
-- (2) fallback CHIST solo para fechas que consolidated_sd no cubre (ninguna en la practica; resiliencia)
SELECT CAST(c.fecha_reporte AS DATE),
       CAST(c.pdf_bucket AS STRING), CAST(c.pdf_em_dm AS STRING), CAST(c.pdf_subregion AS STRING), CAST(c.pdf_fi_category AS STRING),
       CAST(c.pdf_bucket_nt AS STRING), CAST(c.pdf_em_dm_nt AS STRING), CAST(c.pdf_subregion_nt AS STRING), CAST(c.pdf_fi_category_nt AS STRING),
       CAST(c.monto_usd_mm AS NUMERIC), 'CHIST' AS source
FROM `${project}.${mart}.v_foreign_pdf_summary` c
WHERE c.pdf_bucket NOT IN ('Direct Investment','Private Equity')
  AND c.fecha_reporte NOT IN (SELECT DISTINCT s.fecha_reporte FROM `${project}.${mart}.mv_consolidated_foreign_pdf_summary` s
                              WHERE s.pdf_bucket NOT IN ('Direct Investment','Private Equity'))
UNION ALL
-- (3) Direct Investment a nivel instrumento (mv_sp_direct_investment_summary; las columnas _nt repiten las legacy)
SELECT CAST(d.fecha_reporte AS DATE),
       CAST(d.pdf_bucket AS STRING), CAST(d.pdf_em_dm AS STRING), CAST(d.pdf_subregion AS STRING), CAST(d.pdf_fi_category AS STRING),
       CAST(d.pdf_bucket AS STRING), CAST(d.pdf_em_dm AS STRING), CAST(d.pdf_subregion AS STRING), CAST(d.pdf_fi_category AS STRING),
       CAST(d.monto_usd_mm AS NUMERIC), 'SP_XML' AS source
FROM `${project}.${mart}.mv_sp_direct_investment_summary` d
UNION ALL
-- (4) Private Equity desde consolidated_sd
SELECT CAST(s.fecha_reporte AS DATE),
       CAST(s.pdf_bucket AS STRING), CAST(s.pdf_em_dm AS STRING), CAST(s.pdf_subregion AS STRING), CAST(s.pdf_fi_category AS STRING),
       CAST(s.pdf_bucket_nt AS STRING), CAST(s.pdf_em_dm_nt AS STRING), CAST(s.pdf_subregion_nt AS STRING), CAST(s.pdf_fi_category_nt AS STRING),
       CAST(s.monto_usd_mm AS NUMERIC), 'SP_XML' AS source
FROM `${project}.${mart}.mv_consolidated_foreign_pdf_summary` s
WHERE s.pdf_bucket = 'Private Equity';
