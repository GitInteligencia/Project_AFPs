-- Vista afp_mart.v_consolidated_foreign_classified  (traducida 1:1 de sync/v_foreign_consolidated_switch.sql)
-- Lado "fresco" de Foreign: consolidated_sd source IN ('25','17+25') (cuadro 25, nemotecnico = ISIN, ya en USD MM),
-- clasificado via homol -> BD_FUNDS + overlays (region override > overlay > BD_FUNDS).
-- Traducciones: DISTINCT ON -> QUALIFY ROW_NUMBER(); to_char -> FORMAT_DATE; NULL::text -> CAST(NULL AS STRING);
--   NULLIF(TRIM(x),'')::varchar(50) -> NULLIF(TRIM(x), ''); false -> FALSE.
CREATE OR REPLACE VIEW `${project}.${mart}.v_consolidated_foreign_classified` AS
WITH fund_class AS (
  SELECT h.name AS isin,
    bf.id AS fund_id, bf.fondo, bf.manager, bf.asset_class, bf.category, bf.region,
    bf.nt_asset_class, bf.nt_sub_asset_class, bf.nt_category, bf.nt_sub_category, bf.nt_region
  FROM `${project}.${dim}.dim_homol_funds` h
  JOIN `${project}.${dim}.dim_bd_funds` bf ON CAST(bf.id AS STRING) = CAST(h.id AS STRING)
  QUALIFY ROW_NUMBER() OVER (PARTITION BY h.name ORDER BY (CASE h.source
      WHEN 'AFP_CL' THEN 1 WHEN 'LICS_CL' THEN 2
      WHEN 'CARTERAS_FM_CMF' THEN 3 WHEN 'RUT_CMF' THEN 4 ELSE 5 END)) = 1
),
agg AS (
  SELECT fecha AS fecha_reporte, nemotecnico AS isin, SUM(monto_usdmm) AS monto_dolares
  FROM `${project}.${raw}.consolidated_sd`
  WHERE source IN ('25','17+25')
  GROUP BY fecha, nemotecnico
)
SELECT
  FORMAT_DATE('%Y-%m', e.fecha_reporte)                                       AS periodo,
  e.fecha_reporte,
  CAST(NULL AS STRING)                                                        AS emisor,   -- consolidated_sd no tiene glosa
  e.isin,
  e.monto_dolares,
  fc.fund_id, fc.fondo, fc.manager, fc.asset_class,
  COALESCE(NULLIF(TRIM(ov.category), ''), fc.category)                        AS category,
  COALESCE(ovr.region, NULLIF(TRIM(ov.region), ''), fc.region)                AS region,
  FALSE                                                                       AS is_sovereign,
  fc.nt_asset_class, fc.nt_sub_asset_class, fc.nt_category, fc.nt_sub_category, fc.nt_region
FROM agg e
LEFT JOIN fund_class fc ON fc.isin = e.isin
LEFT JOIN `${project}.${dim}.dim_foreign_region_override` ovr ON ovr.fund_id = CAST(fc.fund_id AS STRING)
LEFT JOIN `${project}.${dim}.dim_foreign_classification_overlay` ov ON UPPER(ov.identificador) = UPPER(e.isin)
WHERE e.monto_dolares > 0;
