-- Dimension manual afp_dim.dim_chilean_ticker_homol (75 filas; PLAN §6.2, hueco conocido en LINEAGE.md)
-- Homologacion nemotecnico chileno -> ticker Bloomberg (sin sufijo ' CI Equity').
-- Uso (sync/v_chilean_stocks_switch.sql): JOIN dim_chilean_ticker_homol h ON h.nemo = ch.nemotecnico
--      JOIN dim_ipd_instrumentos i ON split_part(i.ticker_bbg,' ',1) = h.bbg_ticker
-- Se carga desde db/seeds/dim_chilean_ticker_homol.csv (WRITE_TRUNCATE).
CREATE TABLE IF NOT EXISTS `${project}.${dim}.dim_chilean_ticker_homol` (
  nemo       STRING NOT NULL,   -- nemotecnico CHIST (p.ej. 'SQM-B')
  bbg_ticker STRING NOT NULL    -- ticker Bloomberg sin sufijo (p.ej. 'SQM/B')
  -- TODO(dump): confirmar columnas adicionales (notes, updated_at, ...) en db/supabase_snapshot/schema.sql
)
OPTIONS (description = 'Homologacion nemo -> ticker BBG para acciones chilenas (manual). Espejo de public.dim_chilean_ticker_homol.');
