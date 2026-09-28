-- Dimension manual afp_dim.dim_direct_investment_overlay (PLAN §6.2)
-- Overlay ISIN -> clasificacion de inversion directa extranjera (sync/load_di_overlay.py desde di_overlay.json;
--         columnas del INSERT en sync/v_foreign_di_switch.sql).
-- Uso: v_sp_direct_investment_detail (DISTINCT ON upper(identificador)), v_distributors_to_sql_source (no aplicado).
-- Se carga desde db/seeds/dim_direct_investment_overlay.csv (WRITE_TRUNCATE).
CREATE TABLE IF NOT EXISTS `${project}.${dim}.dim_direct_investment_overlay` (
  identificador STRING NOT NULL,   -- ISIN
  emisor_norm   STRING,
  asset_class   STRING,            -- 'Fixed Income' | 'Equity'
  region        STRING,
  country       STRING,
  di_category   STRING,            -- 'Sovereign' | 'Bank' | 'Corporate'
  currency      STRING,
  loaded_at     TIMESTAMP
)
OPTIONS (description = 'Overlay de inversion directa extranjera por ISIN (manual). Espejo de public.dim_direct_investment_overlay.');
