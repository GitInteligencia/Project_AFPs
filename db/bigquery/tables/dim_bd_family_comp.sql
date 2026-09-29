-- Dimension afp_dim.dim_bd_family_comp
-- Origen: Inteligencia_Mercado.dbo.AFP_CL_DIM_Family_Comp (115 filas curadas; DDL en sync/dim_classification_schema.sql
--         y sync/dim_family_comp_schema_sqlserver.sql). tipo: 'Moneda' | 'Peer Group'.
-- Carga hoy: UPSERT por (family_id, id) -> MERGE via afp_stg (paso `core`).
-- Consumidores: v_sp_strategy_aum, mv_strategy_afp_ow_uw.
CREATE TABLE IF NOT EXISTS `${project}.${dim}.dim_bd_family_comp` (
  family_id       INT64 NOT NULL,
  id              INT64 NOT NULL,   -- dim_bd_funds.id (INT aqui, varchar en dim_bd_funds -> las vistas castean)
  tipo            STRING,
  fund_short_name STRING
)
OPTIONS (description = 'Mapeo producto Moneda + peers por familia (sec 04). Espejo de public.dim_bd_family_comp. PK logica (family_id, id).');
