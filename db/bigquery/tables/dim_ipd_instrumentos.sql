-- Dimension afp_dim.dim_ipd_instrumentos (subset TickerBBG IS NOT NULL, ~2.300 filas)
-- Origen: Inteligencia_Producto_Dev.dimensionales.BD_Instrumentos (sync/sync_inteligencia_producto.py::sync_bd_instrumentos).
-- OJO: sync_inteligencia_producto.py NO esta en los 8 pasos de main.py (ver dim_ipd_gics.sql).
-- Uso: v_chilean_stocks_gics (split_part(ticker_bbg,' ',1) = homol.bbg_ticker AND ticker_bbg LIKE '%CI Equity').
CREATE TABLE IF NOT EXISTS `${project}.${dim}.dim_ipd_instrumentos` (
  id_instrumento         INT64 NOT NULL,
  sub_id_instrumento     STRING,   -- TODO(dump): tipo
  name_instrumento       STRING,
  isin                   STRING,
  ticker_bbg             STRING,
  sedol                  STRING,
  cusip                  STRING,
  company_name           STRING,
  investment_type_code   INT64,
  issuer_type_code       INT64,
  issue_type_code        INT64,
  coupon_type_code       INT64,
  sector_gics            STRING,   -- codigo GICS como texto de entero (el sync lo convierte)
  sector_chile_type_code INT64,
  issue_country          STRING,
  risk_country           STRING,
  issue_currency         STRING,
  risk_currency          STRING,
  rank_code              INT64,
  cash_type_code         INT64,
  bank_debt_type_code    INT64,
  fund_type_code         INT64,
  yield_type             INT64,
  yield_source           STRING,
  emision_nacional       INT64,
  comentarios            STRING
)
CLUSTER BY ticker_bbg
OPTIONS (description = 'Instrumentos BD_Instrumentos con ticker Bloomberg. Espejo de public.dim_ipd_instrumentos. PK logica (id_instrumento).');
