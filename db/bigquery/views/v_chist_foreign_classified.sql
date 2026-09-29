-- Vista afp_mart.v_chist_foreign_classified  (traducida 1:1 de sync/v_foreign_chist_switch.sql, version vigente fase 2
-- sobre chist_adjusted; la version previa en sync/nt_taxonomy_foreign_views.sql leia historial_carteras_full, hoy dropeada)
-- Detalle CHIST extranjero (nacionalidad_del_emisor='E') clasificado por fondo + overlay + direct inv + tipo instrumento SP.
-- Traducciones:
--   DISTINCT ON (h.name) ... ORDER BY h.name, CASE -> QUALIFY ROW_NUMBER() OVER (PARTITION BY h.name ORDER BY CASE ...) = 1
--   ::numeric(30,8) / (30,4) -> ROUND(CAST(x AS NUMERIC), 8 / 4);  NULL::varchar(n) -> CAST(NULL AS STRING)
--   upper() -> UPPER(); casts ::varchar/::text -> CAST(... AS STRING) (sin truncado; ver v_chist_aa.sql)
CREATE OR REPLACE VIEW `${project}.${mart}.v_chist_foreign_classified` AS
WITH fund_class AS (
  SELECT h.name AS nemo, bf.id AS fund_id, bf.fondo, bf.manager,
         bf.type AS fund_type, bf.style AS fund_style, bf.asset_class, bf.category, bf.region,
         bf.alt_fund_type, bf.alt_strategy,
         bf.nt_asset_class, bf.nt_sub_asset_class, bf.nt_category, bf.nt_sub_category, bf.nt_region
  FROM `${project}.${dim}.dim_homol_funds` h
  JOIN `${project}.${dim}.dim_bd_funds` bf ON CAST(bf.id AS STRING) = CAST(h.id AS STRING)
  QUALIFY ROW_NUMBER() OVER (PARTITION BY h.name ORDER BY
            (CASE h.source WHEN 'AFP_CL' THEN 1 WHEN 'LICS_CL' THEN 2
                           WHEN 'CARTERAS_FM_CMF' THEN 3 WHEN 'RUT_CMF' THEN 4 ELSE 5 END)) = 1
)
SELECT CAST(hc.fecha AS DATE) AS fecha, CAST(hc.fecha_reporte AS DATE) AS fecha_reporte,
       CAST(hc.afp AS STRING) AS afp, CAST(hc.tipo_de_fondo AS STRING) AS tipo_de_fondo,
       CAST(hc.tipo_de_instrumento AS STRING) AS tipo_de_instrumento,
       CAST(hc.nemotecnico AS STRING) AS nemo, CAST(hc.nombre_del_emisor AS STRING) AS nombre_del_emisor,
       CAST(NULL AS STRING) AS unidad_de_reajuste_de_moneda,
       ROUND(CAST(hc.unidades AS NUMERIC), 8) AS unidades, ROUND(CAST(hc.precio AS NUMERIC), 8) AS precio,
       ROUND(CAST(hc.inversion AS NUMERIC), 4) AS inversion, CAST(NULL AS STRING) AS grupo_economico,
       CAST(fc.fund_id AS STRING) AS fund_id, CAST(fc.fondo AS STRING) AS fondo,
       CAST(fc.manager AS STRING) AS manager, CAST(fc.fund_type AS STRING) AS fund_type,
       CAST(fc.fund_style AS STRING) AS fund_style, CAST(fc.asset_class AS STRING) AS asset_class,
       CAST(COALESCE(CAST(ov.category AS STRING), CAST(fc.category AS STRING)) AS STRING) AS category,
       CAST(COALESCE(CAST(ov.region AS STRING), CAST(fc.region AS STRING)) AS STRING) AS region,
       CAST(fc.alt_fund_type AS STRING) AS alt_fund_type, CAST(fc.alt_strategy AS STRING) AS alt_strategy,
       CAST(dil.name AS STRING) AS direct_inv_name, CAST(dil.asset_class AS STRING) AS direct_inv_asset_class,
       CAST(dil.region AS STRING) AS direct_inv_region, CAST(tisp.descripcion AS STRING) AS sp_descripcion,
       CAST(tisp.c1 AS STRING) AS sp_c1, CAST(tisp.c2 AS STRING) AS sp_c2, CAST(tisp.c3 AS STRING) AS sp_c3,
       CAST(tisp.c4 AS STRING) AS sp_c4,
       CAST(COALESCE(fc.asset_class, CAST(dil.asset_class AS STRING), CAST(tisp.c4 AS STRING)) AS STRING) AS asset_class_eff,
       CAST(COALESCE(CAST(ov.region AS STRING), fc.region, CAST(dil.region AS STRING)) AS STRING) AS region_eff,
       CAST(fc.nt_asset_class AS STRING) AS nt_asset_class, CAST(fc.nt_sub_asset_class AS STRING) AS nt_sub_asset_class,
       CAST(fc.nt_category AS STRING) AS nt_category, CAST(fc.nt_sub_category AS STRING) AS nt_sub_category,
       CAST(fc.nt_region AS STRING) AS nt_region
FROM `${project}.${raw}.chist_adjusted` hc
  LEFT JOIN fund_class fc ON fc.nemo = hc.nemotecnico
  LEFT JOIN `${project}.${dim}.dim_bd_direct_inv_lics` dil ON dil.nemo = hc.nemotecnico
  LEFT JOIN `${project}.${dim}.dim_tipo_instrumento_sp` tisp ON tisp.codigo = hc.tipo_de_instrumento
  LEFT JOIN `${project}.${dim}.dim_foreign_classification_overlay` ov ON UPPER(ov.identificador) = UPPER(hc.nemotecnico)
WHERE hc.nacionalidad_del_emisor = 'E';
