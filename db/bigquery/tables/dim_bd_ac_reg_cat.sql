-- Dimension afp_dim.dim_bd_ac_reg_cat
-- Origen: Inteligencia_Mercado.dbo.DIM_BD_AC_Reg_Cat (DDL Postgres en sync/dim_classification_schema.sql).
-- Carga hoy: UPSERT por supra_id -> MERGE via afp_stg (paso `core`).
CREATE TABLE IF NOT EXISTS `${project}.${dim}.dim_bd_ac_reg_cat` (
  supra_id    INT64 NOT NULL,
  asset_class STRING,
  region      STRING,
  category    STRING
)
OPTIONS (description = 'Cross Asset_Class x Region x Category (estrategia sec 04). Espejo de public.dim_bd_ac_reg_cat.');
