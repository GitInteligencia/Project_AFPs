-- Tabla espejo afp_raw.ipd_attribution_fund_month
-- Origen: sync/sync_ipd_strategy.py (retorno mensual compuesto por fondo + reconciliacion vs serie oficial).
-- Carga: full reload (WRITE_TRUNCATE) en el paso `ipd_strategy`.
-- Consumidores: web (getFundAttribution).
CREATE TABLE IF NOT EXISTS `${project}.${raw}.ipd_attribution_fund_month` (
  id_fund   INT64,
  mes       DATE,
  ret_month FLOAT64,   -- compuesto de contribuciones diarias
  nav_eom   FLOAT64,
  ret_serie FLOAT64,   -- MTD oficial USD (NULL si el fondo no tiene serie USD, p.ej. MDLAT)
  residual  FLOAT64    -- ret_serie - ret_month
)
PARTITION BY DATE_TRUNC(mes, MONTH)
CLUSTER BY id_fund
OPTIONS (description = 'Retorno mensual por fondo IPD y residual vs serie oficial. Espejo de public.ipd_attribution_fund_month.');
