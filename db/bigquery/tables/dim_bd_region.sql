-- Dimension afp_dim.dim_bd_region
-- Origen: Inteligencia_Mercado.dbo.DIM_BD_Region (DDL Postgres en sync/dim_classification_schema.sql).
-- Carga hoy: UPSERT por id_region -> MERGE via afp_stg (paso `core`).
CREATE TABLE IF NOT EXISTS `${project}.${dim}.dim_bd_region` (
  id_region INT64 NOT NULL,
  region    STRING
)
OPTIONS (description = 'Lookup de Region (12 valores). Espejo de public.dim_bd_region.');
