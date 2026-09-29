-- Tabla espejo afp_raw.bbg_returns
-- Origen: Inteligencia_Mercado.dbo.AFP_CL_BBG_Returns (sync/sync_bbg_returns.py,
--         DDL Postgres en sync/bbg_returns_schema.sql). Retorno mensual USD por fondo (nemo_sp), en %.
-- Carga: DELETE por end_date + append (paso `bbg_returns`).
-- Consumidores: v_foreign_returns_flows, v_module_freshness.
CREATE TABLE IF NOT EXISTS `${project}.${raw}.bbg_returns` (
  fila_id     INT64,            -- BIGSERIAL en Postgres; opcional en BigQuery
  start_date  DATE   NOT NULL,
  end_date    DATE   NOT NULL,
  nemo_sp     STRING NOT NULL,
  isin_ticker STRING,
  usd_ret     FLOAT64           -- porcentaje (las vistas dividen por 100)
)
PARTITION BY DATE_TRUNC(end_date, MONTH)
CLUSTER BY nemo_sp
OPTIONS (description = 'Retornos mensuales USD Bloomberg por fondo. Espejo de public.bbg_returns.');
