-- Vista afp_mart.v_foreign_managers_combined  (traducida 1:1 de sync/v_foreign_consolidated_switch.sql)
-- Managers Sec 10: lado fresco (consolidated_sd, token 'SP_XML') + CHIST solo para fechas no cubiertas.
CREATE OR REPLACE VIEW `${project}.${mart}.v_foreign_managers_combined` AS
SELECT CAST(m.fecha_reporte AS DATE) AS fecha_reporte,
       CAST(m.manager AS STRING) AS manager, CAST(m.fund_style AS STRING) AS fund_style,
       CAST(m.asset_class AS STRING) AS asset_class, CAST(m.category AS STRING) AS category, CAST(m.region AS STRING) AS region,
       CAST(m.nt_asset_class AS STRING) AS nt_asset_class, CAST(m.nt_sub_asset_class AS STRING) AS nt_sub_asset_class,
       CAST(m.nt_category AS STRING) AS nt_category, CAST(m.nt_sub_category AS STRING) AS nt_sub_category, CAST(m.nt_region AS STRING) AS nt_region,
       CAST(m.monto_usd_mm AS NUMERIC) AS monto_usd_mm, 'SP_XML' AS source
FROM `${project}.${mart}.v_consolidated_foreign_managers` m
UNION ALL
SELECT CAST(c.fecha_reporte AS DATE),
       CAST(c.manager AS STRING), CAST(c.fund_style AS STRING),
       CAST(c.asset_class AS STRING), CAST(c.category AS STRING), CAST(c.region AS STRING),
       CAST(c.nt_asset_class AS STRING), CAST(c.nt_sub_asset_class AS STRING), CAST(c.nt_category AS STRING),
       CAST(c.nt_sub_category AS STRING), CAST(c.nt_region AS STRING),
       CAST(c.monto_usd_mm AS NUMERIC), 'CHIST' AS source
FROM `${project}.${mart}.v_chist_foreign_managers` c
WHERE c.fecha_reporte NOT IN (SELECT DISTINCT m2.fecha_reporte FROM `${project}.${mart}.v_consolidated_foreign_managers` m2);
