-- Mart afp_mart.mv_aum  (traducido 1:1 de CREATE MATERIALIZED VIEW mv_aum, sync/mv_alternatives_materialize.sql)
-- AUM USD MM por AFP en fechas de cierre de mes: valor_patrimonio / FX CLFXDOOB_sindesf / 1e6.
-- Traducciones:
--   v.fecha = (date_trunc('month', v.fecha::timestamptz) + '1 mon' - '1 day')::date -> v.fecha = LAST_DAY(v.fecha, MONTH)
--   NULLIF(fx.valor, 0::numeric) -> NULLIF(fx.valor, 0);  / 1000000::numeric -> / 1000000 (NUMERIC / INT64 = NUMERIC).
--   Division NUMERIC: Postgres usa escala >= 16; BigQuery NUMERIC escala 9 -> diferencias ~1e-9 relativo (tolerancia §12).
CREATE OR REPLACE TABLE `${project}.${mart}.mv_aum`
PARTITION BY DATE_TRUNC(fecha, MONTH)
CLUSTER BY afp
OPTIONS (description = 'AUM mensual por AFP en USD MM (snapshot). Reconstruida por el job afp-sync, paso marts.')
AS
SELECT v.fecha, v.afp,
       SUM(v.valor_patrimonio / NULLIF(fx.valor, 0) / 1000000) AS aum_usd_mm
FROM `${project}.${raw}.valores_cuota_patrimonio` v
JOIN `${project}.${raw}.tipo_cambio` fx
  ON fx.fecha = v.fecha AND fx.instrumento_codigo = 'CLFXDOOB_sindesf'
WHERE v.fecha = LAST_DAY(v.fecha, MONTH)
GROUP BY v.fecha, v.afp;
