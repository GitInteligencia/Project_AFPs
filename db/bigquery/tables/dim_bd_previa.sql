-- Dimension afp_dim.dim_bd_previa
-- Origen: Inteligencia_Mercado.dbo.DIM_BD_Previa_AFPCL (sync/sync_dim_bd_previa.py, DDL en sync/dim_bd_previa_schema.sql).
--         Separador nemo -> type {FUND, DIRECT_INV}; se carga con SELECT DISTINCT (nemo unico).
-- Carga: reload completo (WRITE_TRUNCATE) en el paso `dim_bd_previa`.
-- Consumidores: v_consolidated_classified.
CREATE TABLE IF NOT EXISTS `${project}.${dim}.dim_bd_previa` (
  nemo STRING NOT NULL,
  type STRING NOT NULL   -- 'FUND' | 'DIRECT_INV'
)
OPTIONS (description = 'Separador nemo -> FUND / DIRECT_INV para consolidated_sd. Espejo de public.dim_bd_previa. PK logica (nemo).');
