-- Dimension manual afp_dim.dim_strategy_ipd_funds (PLAN §6.2)
-- Mapping estatico family_id -> ID_Fund IPD (migration strategy_41_42_ipd_tables; LINEAGE.md).
-- Columnas = las que lee web/lib/queries-strategy-attribution.ts::getStrategyIpdFunds (+ family_id como filtro).
-- Se carga desde db/seeds/dim_strategy_ipd_funds.csv (WRITE_TRUNCATE).
CREATE TABLE IF NOT EXISTS `${project}.${dim}.dim_strategy_ipd_funds` (
  family_id    INT64  NOT NULL,   -- dim_bd_family.family_id
  id_fund      INT64  NOT NULL,   -- TBL_IPA_V2.ID_Fund (posiciones)
  fund_label   STRING NOT NULL,
  rent_id_fund INT64              -- ID_Fund de la serie de rentabilidad (p.ej. MLCC 68 -> 55); NULL si no hay
  -- TODO(dump): confirmar columnas adicionales / orden en db/supabase_snapshot/schema.sql
)
OPTIONS (description = 'Fondos IPD por familia de estrategia (manual). Espejo de public.dim_strategy_ipd_funds.');
