-- Tabla espejo afp_raw.ipd_rentabilidades
-- Origen: Inteligencia_Producto.dbo.TBL_RENTABILIDADES_SERIES (sync/sync_ipd_strategy.py::read_rentabilidades).
--         Agrupacion '<id_fund>-<id_serie>-<bm_ticker>-<currency>' ya parseada en 3 columnas.
-- Carga: full reload (WRITE_TRUNCATE) en el paso `ipd_strategy`.
-- Consumidores: web (getFundReturns).
CREATE TABLE IF NOT EXISTS `${project}.${raw}.ipd_rentabilidades` (
  row_id      INT64,     -- BIGSERIAL en Postgres; opcional
  id_fund     INT64,
  id_serie    INT64,
  bm_ticker   STRING,
  quiebre     STRING,    -- 'Serie' | 'Benchmark'
  currency    STRING,    -- 'USD' | 'CLP'
  fecha       DATE,
  fecha_data  DATE,
  valor_cuota FLOAT64,
  patrimonio  FLOAT64,
  dtd         FLOAT64,
  mtd         FLOAT64,
  ytd         FLOAT64,
  itd         FLOAT64,
  y1          FLOAT64,
  y2          FLOAT64,
  y3          FLOAT64,
  y5          FLOAT64,
  alpha_1y    FLOAT64,
  beta_1y     FLOAT64,
  sharpe_1y   FLOAT64,
  te_1y       FLOAT64,
  ir_1y       FLOAT64
  -- TODO(dump): confirmar tipos (numeric vs double) de las metricas en db/supabase_snapshot/schema.sql
)
PARTITION BY DATE_TRUNC(fecha, MONTH)
CLUSTER BY id_fund, quiebre, currency
OPTIONS (description = 'Series de rentabilidad oficiales por fondo/benchmark IPD. Espejo de public.ipd_rentabilidades.');
