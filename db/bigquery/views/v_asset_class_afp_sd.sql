-- Vista afp_mart.v_asset_class_afp_sd  (traducida 1:1 de sync/v_asset_class_sd_alternatives.sql)
-- Asset allocation por AFP (tipo_fondo='TOTAL') con carve-out de Alternatives via glosa, subtotales y fila afp='TOTAL'.
-- Traducciones (PLAN §7):
--   x ~~* '%pat%'  (ILIKE)              -> LOWER(x) LIKE '%pat%'
--   x ~~ 'Local%'  (LIKE)               -> LIKE (identico)
--   x = ANY (ARRAY[...])                -> x IN (...)
--   to_char(fecha::timestamptz,'YYYY-MM') -> FORMAT_DATE('%Y-%m', fecha)
--   round(100.0 * a.monto / t.total_assets, 2): en Postgres 100.0 es numeric; en BigQuery seria FLOAT64,
--   por eso se usa NUMERIC '100' para mantener aritmetica NUMERIC y el mismo redondeo (half away from zero).
CREATE OR REPLACE VIEW `${project}.${mart}.v_asset_class_afp_sd` AS
WITH mapped AS (
  SELECT s.fecha, s.afp,
    CASE
      WHEN LOWER(s.nivel_1) LIKE '%nacional%'   AND LOWER(s.glosa) LIKE '%alternativ%' THEN 'Local Alternatives'
      WHEN LOWER(s.nivel_1) LIKE '%extranjera%' AND LOWER(s.glosa) LIKE '%alternativ%' THEN 'Foreign Alternatives'
      WHEN LOWER(s.nivel_1) LIKE '%nacional%'   AND s.nivel_2 = 'RENTA VARIABLE'        THEN 'Local Equity'
      WHEN LOWER(s.nivel_1) LIKE '%nacional%'   AND s.nivel_2 = 'RENTA FIJA'            THEN 'Local Fixed Income'
      WHEN LOWER(s.nivel_1) LIKE '%nacional%'   AND s.nivel_2 = 'DERIVADOS'             THEN 'Local Derivatives'
      WHEN LOWER(s.nivel_1) LIKE '%nacional%'                                           THEN 'Local Other'
      WHEN LOWER(s.nivel_1) LIKE '%extranjera%' AND s.nivel_2 = 'RENTA VARIABLE'        THEN 'Foreign Equity'
      WHEN LOWER(s.nivel_1) LIKE '%extranjera%' AND s.nivel_2 = 'RENTA FIJA'            THEN 'Foreign Fixed Income'
      WHEN LOWER(s.nivel_1) LIKE '%extranjera%' AND s.nivel_2 = 'DERIVADOS'             THEN 'Foreign Derivatives'
      WHEN LOWER(s.nivel_1) LIKE '%extranjera%'                                         THEN 'Foreign Other'
      ELSE NULL
    END AS pdf_category,
    s.monto_usdmm
  FROM `${project}.${raw}.sd_asset_class_afp` s
),
leaves AS (
  SELECT fecha, afp, pdf_category, SUM(monto_usdmm) AS monto
  FROM mapped WHERE pdf_category IS NOT NULL
  GROUP BY fecha, afp, pdf_category
),
allcat AS (
  SELECT fecha, afp, pdf_category, monto FROM leaves
  UNION ALL SELECT fecha, afp, 'Total Local',        SUM(monto) FROM leaves WHERE pdf_category LIKE 'Local%'   GROUP BY fecha, afp
  UNION ALL SELECT fecha, afp, 'Total Foreign',      SUM(monto) FROM leaves WHERE pdf_category LIKE 'Foreign%' GROUP BY fecha, afp
  UNION ALL SELECT fecha, afp, 'Total Equity',       SUM(monto) FROM leaves WHERE pdf_category IN ('Local Equity','Foreign Equity')             GROUP BY fecha, afp
  UNION ALL SELECT fecha, afp, 'Total Fixed Income', SUM(monto) FROM leaves WHERE pdf_category IN ('Local Fixed Income','Foreign Fixed Income') GROUP BY fecha, afp
  UNION ALL SELECT fecha, afp, 'Total Alternatives', SUM(monto) FROM leaves WHERE pdf_category IN ('Local Alternatives','Foreign Alternatives') GROUP BY fecha, afp
  UNION ALL SELECT fecha, afp, 'Total Assets',       SUM(monto) FROM leaves GROUP BY fecha, afp
),
allcat2 AS (
  SELECT fecha, afp, pdf_category, monto FROM allcat
  UNION ALL
  SELECT fecha, 'TOTAL' AS afp, pdf_category, SUM(monto) AS monto FROM allcat GROUP BY fecha, pdf_category
),
ta AS (
  SELECT fecha, afp, monto AS total_assets FROM allcat2 WHERE pdf_category = 'Total Assets'
)
SELECT a.fecha AS fecha_valor,
  FORMAT_DATE('%Y-%m', a.fecha) AS periodo,
  a.afp AS afp_nombre,
  'TOTAL' AS tipo_fondo,
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
FROM allcat2 a
LEFT JOIN ta t ON t.fecha = a.fecha AND t.afp = a.afp;
