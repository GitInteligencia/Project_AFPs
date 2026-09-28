-- Tabla espejo afp_raw.ipd_attribution_monthly
-- Origen: calculo pandas en sync/sync_ipd_strategy.py::compute_attribution (agregado mensual por instrumento).
-- Carga: full reload (WRITE_TRUNCATE) en el paso `ipd_strategy`.
-- Consumidores: web (fetchAttributionRows).
CREATE TABLE IF NOT EXISTS `${project}.${raw}.ipd_attribution_monthly` (
  row_id           INT64,     -- BIGSERIAL en Postgres; lo asigna el pipeline (la web ordena por row_id)
  id_fund          INT64,
  mes              DATE,      -- primer dia del mes
  id_instrumento   INT64,
  instrumento      STRING,
  company          STRING,
  currency         STRING,
  avg_weight       FLOAT64,
  contrib_total    FLOAT64,   -- fraccion (0.0123 = +1.23%)
  contrib_price    FLOAT64,
  contrib_fx_carry FLOAT64,
  n_dias           INT64
)
PARTITION BY DATE_TRUNC(mes, MONTH)
CLUSTER BY id_fund
OPTIONS (description = 'Atribucion mensual por instrumento (Strategy 4.1). Espejo de public.ipd_attribution_monthly.');
