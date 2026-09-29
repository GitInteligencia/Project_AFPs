-- Vista afp_mart.v_consolidated_classified  (traducida 1:1 de sync/v_classification_layer.sql)
-- Detalle consolidado (sin desfase, nivel sistema) clasificado: previa_type FUND/DIRECT_INV + atributos de fondo.
-- Base de v_sp_strategy_aum.
CREATE OR REPLACE VIEW `${project}.${mart}.v_consolidated_classified` AS
SELECT cs.fila_id, cs.fecha, cs.tipo_fondo, cs.nemotecnico, cs.source,
       cs.lim_nac_usdmm, cs.lim_extr_usdmm, cs.monto_usdmm,
       p.type AS previa_type,
       fc.fund_id, fc.manager, fc.asset_class, fc.category, fc.region,
       fc.alt_fund_type, fc.alt_strategy,
       fc.nt_asset_class, fc.nt_sub_asset_class, fc.nt_category,
       fc.nt_sub_category, fc.nt_region,
       COALESCE(fc.is_alt_fund, FALSE) AS is_alt_fund
FROM `${project}.${raw}.consolidated_sd` cs
LEFT JOIN `${project}.${dim}.dim_bd_previa` p  ON p.nemo  = cs.nemotecnico
LEFT JOIN `${project}.${mart}.v_fund_class`  fc ON fc.nemo = cs.nemotecnico;
