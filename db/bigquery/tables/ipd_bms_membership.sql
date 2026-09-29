-- Tabla espejo afp_raw.ipd_bms_membership
-- Origen: Inteligencia_Producto.dbo.TBL_BMS_Exposicion + BD_INSTRUMENTOS (sync/sync_ipd_strategy.py::read_bms_membership).
--         Constituyentes de indices S&P (IGPA 16, IGPAL 17, IGPAM 18, IGPAS 19, IPSA 20), EOM + ultima fecha.
-- Carga: full reload (WRITE_TRUNCATE) en el paso `ipd_strategy`.
-- Consumidores: f_sec05_* (pendiente dump), web (getSec05ResolvedFechas).
CREATE TABLE IF NOT EXISTS `${project}.${raw}.ipd_bms_membership` (
  row_id         INT64,     -- BIGSERIAL en Postgres; opcional
  fecha          DATE,
  id_bm          INT64,
  id_instrumento INT64,
  ticker         STRING,
  company        STRING,
  weight         FLOAT64    -- mval / total del indice en la fecha
)
PARTITION BY DATE_TRUNC(fecha, MONTH)
CLUSTER BY id_bm
OPTIONS (description = 'Composicion de indices S&P Chile (Sec05). Espejo de public.ipd_bms_membership.');
