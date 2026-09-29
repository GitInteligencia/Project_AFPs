-- Dimension afp_dim.dim_bd_direct_inv_lics
-- Origen: Inteligencia_Mercado.dbo.DIM_BD_Direct_Inv_LICS (DDL Postgres en sync/dim_classification_schema.sql).
-- Carga hoy: UPSERT por nemo -> MERGE via afp_stg (paso `core`).
-- Consumidores: v_chist_foreign_classified.
CREATE TABLE IF NOT EXISTS `${project}.${dim}.dim_bd_direct_inv_lics` (
  nemo        STRING NOT NULL,
  asset_class STRING,
  region      STRING,
  name        STRING
)
OPTIONS (description = 'Inversiones directas con NEMO + asset class + region. Espejo de public.dim_bd_direct_inv_lics.');
