-- Vista afp_mart.v_chist_classified  (traducida 1:1 de sync/v_classification_layer.sql)
-- Detalle CHIST (con desfase, por AFP) ya clasificado con atributos de fondo + flag is_alternative.
-- Base de Alternatives (v_chist_aa), Strategy (mv_strategy_afp_ow_uw).
-- Semantica NULL preservada: COALESCE(is_alt_fund,false) OR supracategory = '...' puede ser NULL si supracategory es NULL (igual que Postgres).
CREATE OR REPLACE VIEW `${project}.${mart}.v_chist_classified` AS
SELECT ca.fila_id, ca.fecha_reporte, ca.fecha, ca.afp,
       ca.tipo_de_fondo, ca.tipo_de_instrumento,
       ca.nemotecnico, ca.nombre_del_emisor, ca.nacionalidad_del_emisor,
       ca.unidades, ca.precio, ca.inversion,
       ca.supracategory, ca.tipo_valor,
       fc.fund_id, fc.manager, fc.asset_class, fc.category, fc.region,
       fc.alt_fund_type, fc.alt_strategy,
       fc.nt_asset_class, fc.nt_sub_asset_class, fc.nt_category,
       fc.nt_sub_category, fc.nt_region,
       -- alternativos: fondo con Asset_Class='Alternative' o el bucket Direct Inv. Alternativos
       (COALESCE(fc.is_alt_fund, FALSE)
        OR ca.supracategory = 'Direct Inv. Alternativos') AS is_alternative,
       fc.fondo
FROM `${project}.${raw}.chist_adjusted` ca
LEFT JOIN `${project}.${mart}.v_fund_class` fc ON fc.nemo = ca.nemotecnico;
