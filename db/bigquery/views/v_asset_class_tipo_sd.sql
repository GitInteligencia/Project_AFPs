-- Vista afp_mart.v_asset_class_tipo_sd  (traducida 1:1 de sync/v_asset_class_sd_alternatives.sql)
-- Asset allocation por tipo de fondo (A..E + 'TOTAL' = suma del sistema) con carve-out de Alternatives.
-- Mismas traducciones que v_asset_class_afp_sd (ILIKE -> LOWER LIKE, ANY(ARRAY) -> IN, to_char -> FORMAT_DATE, 100.0 -> NUMERIC '100').
CREATE OR REPLACE VIEW `${project}.${mart}.v_asset_class_tipo_sd` AS
WITH mapped AS (
  SELECT b.fecha, b.tipo_fondo,
    CASE
      WHEN LOWER(b.nivel_1) LIKE '%nacional%'   AND LOWER(b.glosa) LIKE '%alternativ%' THEN 'Local Alternatives'
      WHEN LOWER(b.nivel_1) LIKE '%extranjera%' AND LOWER(b.glosa) LIKE '%alternativ%' THEN 'Foreign Alternatives'
      WHEN LOWER(b.nivel_1) LIKE '%nacional%'   AND b.nivel_2 = 'RENTA VARIABLE'        THEN 'Local Equity'
      WHEN LOWER(b.nivel_1) LIKE '%nacional%'   AND b.nivel_2 = 'RENTA FIJA'            THEN 'Local Fixed Income'
      WHEN LOWER(b.nivel_1) LIKE '%nacional%'   AND b.nivel_2 = 'DERIVADOS'             THEN 'Local Derivatives'
      WHEN LOWER(b.nivel_1) LIKE '%nacional%'                                           THEN 'Local Other'
      WHEN LOWER(b.nivel_1) LIKE '%extranjera%' AND b.nivel_2 = 'RENTA VARIABLE'        THEN 'Foreign Equity'
      WHEN LOWER(b.nivel_1) LIKE '%extranjera%' AND b.nivel_2 = 'RENTA FIJA'            THEN 'Foreign Fixed Income'
      WHEN LOWER(b.nivel_1) LIKE '%extranjera%' AND b.nivel_2 = 'DERIVADOS'             THEN 'Foreign Derivatives'
      WHEN LOWER(b.nivel_1) LIKE '%extranjera%'                                         THEN 'Foreign Other'
      ELSE NULL
    END AS pdf_category,
    b.monto_usdmm
  FROM (
    SELECT fecha, tipo_fondo, nivel_1, nivel_2, glosa, monto_usdmm FROM `${project}.${raw}.sd_asset_class_tipo`
    UNION ALL
    SELECT fecha, 'TOTAL' AS tipo_fondo, nivel_1, nivel_2, glosa, monto_usdmm FROM `${project}.${raw}.sd_asset_class_tipo`
  ) b
),
leaves AS (
  SELECT fecha, tipo_fondo, pdf_category, SUM(monto_usdmm) AS monto
  FROM mapped WHERE pdf_category IS NOT NULL
  GROUP BY fecha, tipo_fondo, pdf_category
),
allcat AS (
  SELECT fecha, tipo_fondo, pdf_category, monto FROM leaves
  UNION ALL SELECT fecha, tipo_fondo, 'Total Local',        SUM(monto) FROM leaves WHERE pdf_category LIKE 'Local%'   GROUP BY fecha, tipo_fondo
  UNION ALL SELECT fecha, tipo_fondo, 'Total Foreign',      SUM(monto) FROM leaves WHERE pdf_category LIKE 'Foreign%' GROUP BY fecha, tipo_fondo
  UNION ALL SELECT fecha, tipo_fondo, 'Total Equity',       SUM(monto) FROM leaves WHERE pdf_category IN ('Local Equity','Foreign Equity')             GROUP BY fecha, tipo_fondo
  UNION ALL SELECT fecha, tipo_fondo, 'Total Fixed Income', SUM(monto) FROM leaves WHERE pdf_category IN ('Local Fixed Income','Foreign Fixed Income') GROUP BY fecha, tipo_fondo
  UNION ALL SELECT fecha, tipo_fondo, 'Total Alternatives', SUM(monto) FROM leaves WHERE pdf_category IN ('Local Alternatives','Foreign Alternatives') GROUP BY fecha, tipo_fondo
  UNION ALL SELECT fecha, tipo_fondo, 'Total Assets',       SUM(monto) FROM leaves GROUP BY fecha, tipo_fondo
),
ta AS (
  SELECT fecha, tipo_fondo, monto AS total_assets FROM allcat WHERE pdf_category = 'Total Assets'
)
SELECT a.fecha AS fecha_valor,
  FORMAT_DATE('%Y-%m', a.fecha) AS periodo,
  a.tipo_fondo,
  a.pdf_category,
  CASE a.pdf_category
    WHEN 'Local Equity' THEN 1 WHEN 'Local Fixed Income' THEN 2 WHEN 'Local Derivatives' THEN 3
    WHEN 'Local Alternatives' THEN 4 WHEN 'Local Other' THEN 5 WHEN 'Total Local' THEN 6
    WHEN 'Foreign Equity' THEN 7 WHEN 'Foreign Fixed Income' THEN 8 WHEN 'Foreign Derivatives' THEN 9
    WHEN 'Foreign Alternatives' THEN 10 WHEN 'Foreign Other' THEN 11 WHEN 'Total Foreign' THEN 12
    WHEN 'Total Equity' THEN 13 WHEN 'Total Fixed Income' THEN 14 WHEN 'Total Alternatives' THEN 15
    WHEN 'Total Assets' THEN 16 ELSE NULL
  END AS pdf_order,
  a.monto AS monto_dolares,
  CASE WHEN t.total_assets IS NULL OR t.total_assets = 0 THEN NULL
       ELSE ROUND(NUMERIC '100' * a.monto / t.total_assets, 2) END AS porcentaje
FROM allcat a
LEFT JOIN ta t ON t.fecha = a.fecha AND t.tipo_fondo = a.tipo_fondo;
