-- Vista afp_mart.v_sp_direct_investment_detail  (traducida 1:1 de sync/v_foreign_di_switch.sql, version vigente sobre consolidated_sd)
-- Detalle de inversion directa extranjera: consolidated_sd cuadro 25 x overlay dim_direct_investment_overlay (match por ISIN).
-- El nombre "sp_" se conserva (cosmetico). mv_sp_direct_investment_detail es su snapshot (tabla).
-- Traducciones: DISTINCT ON (upper(identificador)) ORDER BY upper(identificador)
--   -> QUALIFY ROW_NUMBER() OVER (PARTITION BY UPPER(identificador) ORDER BY UPPER(identificador)) = 1 (desempate arbitrario, como en Postgres);
--   to_char -> FORMAT_DATE; NULL::text -> CAST(NULL AS STRING).
CREATE OR REPLACE VIEW `${project}.${mart}.v_sp_direct_investment_detail` AS
WITH agg AS (
  SELECT fecha, nemotecnico, SUM(monto_usdmm) AS usd_mm
  FROM `${project}.${raw}.consolidated_sd`
  WHERE source IN ('25','17+25')
  GROUP BY fecha, nemotecnico
),
ov AS (
  SELECT UPPER(identificador) AS id,
         asset_class, di_category, country, region, currency
  FROM `${project}.${dim}.dim_direct_investment_overlay`
  QUALIFY ROW_NUMBER() OVER (PARTITION BY UPPER(identificador) ORDER BY UPPER(identificador)) = 1
)
SELECT
  FORMAT_DATE('%Y-%m', a.fecha) AS periodo,
  a.fecha AS fecha_valor,
  CAST(a.nemotecnico AS STRING) AS nemotecnico,
  CAST(NULL AS STRING) AS glosa,
  CAST(ov.asset_class AS STRING) AS asset_class, CAST(ov.di_category AS STRING) AS di_category,
  CAST(ov.country AS STRING) AS country, CAST(ov.region AS STRING) AS region, CAST(ov.currency AS STRING) AS currency,
  CAST(a.usd_mm AS NUMERIC) AS usd_mm
FROM agg a
JOIN ov ON ov.id = UPPER(a.nemotecnico);
