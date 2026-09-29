-- Tabla espejo afp_raw.ipd_cartera_eom
-- Origen: Inteligencia_Producto.dbo.TBL_IPA_V2 + BD_INSTRUMENTOS (sync/sync_ipd_strategy.py::build_cartera_eom).
--         Cartera de fin de mes por fondo Moneda (13,17,28,34,52,59,68) + Pionero(33)/MRV(19) para Sec05.
-- Carga: full reload (WRITE_TRUNCATE) en el paso `ipd_strategy`.
-- Consumidores: web (getFundCartera, getSec05ResolvedFechas), f_sec05_* (pendiente dump), v_module_freshness.
-- Columnas = orden exacto del DataFrame `cartera` del sync.
CREATE TABLE IF NOT EXISTS `${project}.${raw}.ipd_cartera_eom` (
  row_id               INT64,     -- BIGSERIAL en Postgres (la web ordena por row_id al paginar); lo asigna el pipeline
  id_fund              INT64,
  fecha                DATE,
  id_instrumento       INT64,
  instrumento          STRING,
  company              STRING,
  currency             STRING,
  source               STRING,    -- 'DERIVADOS', 'CASH APPRAISAL', ...
  investment_type_code INT64,     -- 2 = equity
  qty                  FLOAT64,
  local_price          FLOAT64,
  mval_usd             FLOAT64,
  weight               FLOAT64
)
PARTITION BY DATE_TRUNC(fecha, MONTH)
CLUSTER BY id_fund
OPTIONS (description = 'Cartera EOM por fondo IPD (Strategy 4.1 + Sec05). Espejo de public.ipd_cartera_eom.');
