-- Dimension afp_dim.dim_bd_asset_class
-- Origen: Inteligencia_Mercado.dbo.DIM_BD_Asset_Class (DDL Postgres en sync/dim_classification_schema.sql).
-- Carga hoy: UPSERT por id_asset_class -> MERGE via afp_stg (paso `core`).
CREATE TABLE IF NOT EXISTS `${project}.${dim}.dim_bd_asset_class` (
  id_asset_class INT64 NOT NULL,
  asset_class    STRING
)
OPTIONS (description = 'Lookup de Asset_Class (9 valores). Espejo de public.dim_bd_asset_class.');
