-- Vista afp_mart.v_chist_foreign_managers  (traducida 1:1 de sync/nt_taxonomy_foreign_views.sql, 3b)
-- Wrapper sobre la tabla mv_chist_foreign_managers (snapshot CHIST de managers extranjeros).
CREATE OR REPLACE VIEW `${project}.${mart}.v_chist_foreign_managers` AS
SELECT fecha_reporte, manager, fund_style, asset_class, category, region,
       nt_asset_class, nt_sub_asset_class, nt_category, nt_sub_category, nt_region,
       monto_usd_mm
FROM `${project}.${mart}.mv_chist_foreign_managers`;
