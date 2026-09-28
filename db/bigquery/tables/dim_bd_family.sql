-- Dimension afp_dim.dim_bd_family
-- Origen: Inteligencia_Mercado.dbo.DIM_BD_Family (DDL Postgres en sync/dim_classification_schema.sql).
-- Carga hoy: UPSERT por family_id -> MERGE via afp_stg (paso `core`).
-- Consumidores: v_sp_strategy_aum, web (getStrategyFamilies).
CREATE TABLE IF NOT EXISTS `${project}.${dim}.dim_bd_family` (
  family_id         INT64 NOT NULL,
  family_name       STRING,
  family_short_name STRING
)
OPTIONS (description = 'Familias / estrategias core de Moneda. Espejo de public.dim_bd_family.');
