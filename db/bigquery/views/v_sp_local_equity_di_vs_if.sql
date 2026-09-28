-- Vista afp_mart.v_sp_local_equity_di_vs_if  (traducida 1:1 de sync/v_strategy_local_equity_switch.sql)
-- Local Equity: inversion directa (consolidated_sd source '09') vs fondos (source '17', asset_class Equity & region Chile),
-- en CLP bn con USDCLP de fin de mes. Intermedia de v_local_equity_di_vs_if_combined (pendiente de dump).
-- Traducciones:
--   to_char(fecha,'YYYY-MM') -> FORMAT_DATE('%Y-%m', fecha);  first_value() OVER (...) con DISTINCT se mantiene;
--   x / 1000.0 (numeric en Postgres) -> x / NUMERIC '1000' para no degradar a FLOAT64;  0::numeric -> 0.
--   En `direct`, periodo se deriva de la columna agrupada fecha (BigQuery lo permite).
CREATE OR REPLACE VIEW `${project}.${mart}.v_sp_local_equity_di_vs_if` AS
WITH fx AS (
  SELECT DISTINCT FORMAT_DATE('%Y-%m', fecha) AS periodo,
    FIRST_VALUE(valor) OVER (PARTITION BY FORMAT_DATE('%Y-%m', fecha) ORDER BY fecha DESC) AS usdclp
  FROM `${project}.${raw}.tipo_cambio` WHERE instrumento_codigo = 'USDCLP Curncy'
),
direct AS (
  SELECT fecha AS fecha_reporte, FORMAT_DATE('%Y-%m', fecha) AS periodo, SUM(monto_usdmm) AS direct_usd_mm
  FROM `${project}.${raw}.consolidated_sd` WHERE source = '09' GROUP BY fecha
),
funds AS (
  SELECT cs.fecha AS fecha_reporte,
    SUM(CASE WHEN bf.asset_class = 'Equity' AND bf.region = 'Chile' THEN cs.monto_usdmm ELSE 0 END) AS funds_usd_mm,
    SUM(CASE WHEN bf.nt_asset_class = 'Equity' AND bf.nt_region = 'Chile' THEN cs.monto_usdmm ELSE 0 END) AS funds_usd_mm_nt
  FROM `${project}.${raw}.consolidated_sd` cs
  JOIN `${project}.${dim}.dim_homol_funds` h ON h.name = cs.nemotecnico AND h.source = 'AFP_CL'
  JOIN `${project}.${dim}.dim_bd_funds` bf ON CAST(bf.id AS STRING) = CAST(h.id AS STRING)
  WHERE cs.source = '17' GROUP BY cs.fecha
)
SELECT d.fecha_reporte,
  d.direct_usd_mm * fx.usdclp / NUMERIC '1000' AS direct_clp_bn,
  COALESCE(f.funds_usd_mm * fx.usdclp / NUMERIC '1000', 0) AS funds_clp_bn,
  COALESCE(f.funds_usd_mm_nt * fx.usdclp / NUMERIC '1000', 0) AS funds_clp_bn_nt
FROM direct d
LEFT JOIN funds f ON f.fecha_reporte = d.fecha_reporte
LEFT JOIN fx ON fx.periodo = d.periodo;
