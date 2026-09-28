-- Vista afp_mart.v_consolidated_foreign_managers  (traducida 1:1 de sync/v_foreign_consolidated_switch.sql)
-- Managers extranjeros (lado fresco consolidated_sd), fund_style Passive si dim_bd_funds.style IN ('ETF','Passive').
CREATE OR REPLACE VIEW `${project}.${mart}.v_consolidated_foreign_managers` AS
SELECT e.fecha_reporte, e.manager,
  CASE WHEN bf.style IN ('ETF','Passive') THEN 'Passive' ELSE 'Active' END AS fund_style,
  e.asset_class, e.category, e.region,
  e.nt_asset_class, e.nt_sub_asset_class, e.nt_category, e.nt_sub_category, e.nt_region,
  SUM(e.monto_dolares) AS monto_usd_mm
FROM `${project}.${mart}.v_consolidated_foreign_classified` e
LEFT JOIN `${project}.${dim}.dim_bd_funds` bf ON CAST(bf.id AS STRING) = CAST(e.fund_id AS STRING)
WHERE e.fund_id IS NOT NULL
GROUP BY e.fecha_reporte, e.manager, bf.style, e.asset_class, e.category, e.region,
         e.nt_asset_class, e.nt_sub_asset_class, e.nt_category, e.nt_sub_category, e.nt_region;
