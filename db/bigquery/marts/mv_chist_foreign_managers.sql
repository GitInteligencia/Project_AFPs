-- Mart afp_mart.mv_chist_foreign_managers  (traducido 1:1 de sync/nt_taxonomy_foreign_views.sql, 3a)
-- Managers extranjeros lado CHIST: USD MM = inversion(numeric 30,4) / USDCLP Curncy(fecha snapshot) / 1e6.
-- Hoy solo alimenta v_chist_foreign_managers -> v_foreign_managers_combined (fechas no cubiertas por consolidated_sd).
-- Traducciones: bf.style::text = ANY (ARRAY['ETF','Passive']) -> IN;  / 1000000.0 (numeric) -> / NUMERIC '1000000';
--   sin NULLIF en fx.valor (igual que el original: un FX = 0 falla en ambos motores).
CREATE OR REPLACE TABLE `${project}.${mart}.mv_chist_foreign_managers`
PARTITION BY DATE_TRUNC(fecha_reporte, MONTH)
CLUSTER BY manager
OPTIONS (description = 'Managers extranjeros CHIST por fecha_reporte (snapshot). Reconstruida por el job afp-sync, paso marts.')
AS
SELECT f.fecha_reporte,
       f.manager,
       CASE WHEN bf.style IN ('ETF','Passive') THEN 'Passive' ELSE 'Active' END AS fund_style,
       f.asset_class,
       f.category,
       f.region,
       f.nt_asset_class,
       f.nt_sub_asset_class,
       f.nt_category,
       f.nt_sub_category,
       f.nt_region,
       SUM((f.inversion / fx.valor) / NUMERIC '1000000') AS monto_usd_mm
FROM `${project}.${mart}.v_chist_foreign_classified` f
JOIN `${project}.${raw}.tipo_cambio` fx
  ON fx.fecha = f.fecha AND fx.instrumento_codigo = 'USDCLP Curncy'
LEFT JOIN `${project}.${dim}.dim_bd_funds` bf ON CAST(bf.id AS STRING) = CAST(f.fund_id AS STRING)
WHERE f.fund_id IS NOT NULL
GROUP BY f.fecha_reporte, f.manager, bf.style, f.asset_class, f.category, f.region,
         f.nt_asset_class, f.nt_sub_asset_class, f.nt_category, f.nt_sub_category, f.nt_region;
