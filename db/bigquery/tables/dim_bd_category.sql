-- Dimension afp_dim.dim_bd_category
-- Origen: Inteligencia_Mercado.dbo.DIM_BD_Category (DDL Postgres en sync/dim_classification_schema.sql).
-- Carga hoy: UPSERT por id_category -> MERGE via afp_stg (paso `core`).
CREATE TABLE IF NOT EXISTS `${project}.${dim}.dim_bd_category` (
  id_category INT64 NOT NULL,
  category    STRING
)
OPTIONS (description = 'Lookup de Category (20 valores). Espejo de public.dim_bd_category.');
