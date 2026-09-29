-- Dimension manual afp_dim.dim_sec08_top_flows (PLAN §6.2)
-- Top flujos Sec 08 cargados desde Excel/JSON legacy (load_*.py gitignorados).
-- Columnas = las que lee web/lib/queries-sec08.ts / types-sec08.ts.
-- Se carga desde db/seeds/dim_sec08_top_flows.csv (WRITE_TRUNCATE).
CREATE TABLE IF NOT EXISTS `${project}.${dim}.dim_sec08_top_flows` (
  fecha         DATE   NOT NULL,
  period_type   STRING NOT NULL,   -- 'MTD' | 'YTD' | 'LTM'
  direction     STRING NOT NULL,   -- 'inflow' | 'outflow'
  rk            INT64  NOT NULL,
  fondo         STRING NOT NULL,
  amount_usd_mm NUMERIC
  -- TODO(dump): confirmar columnas adicionales (loaded_at, ...) en db/supabase_snapshot/schema.sql
)
OPTIONS (description = 'Top inflows/outflows Sec 08 (seed manual). Espejo de public.dim_sec08_top_flows.');
