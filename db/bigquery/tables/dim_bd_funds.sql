-- Dimension afp_dim.dim_bd_funds (universo completo de fondos, ~5.000 filas)
-- Origen: Inteligencia_Mercado.dbo.DIM_BD_FUNDS_2_INTMDO (sync_sqlserver_to_supabase.py::sync_dim_bd_funds).
--         Columnas nt_* = nueva taxonomia (New_*), antes cargadas desde BD_Funds.xlsx (sync/dim_bd_funds_nt_schema.sql).
--         distributor agregado en sync/v_distributors_to_sql_source.sql (varchar(120)).
-- Carga hoy: UPSERT por id -> MERGE via afp_stg (paso `core`).
-- `id` es varchar en Supabase (ver sync/dim_family_comp_schema_sqlserver.sql); las vistas comparan por CAST(... AS STRING).
CREATE TABLE IF NOT EXISTS `${project}.${dim}.dim_bd_funds` (
  id                 STRING NOT NULL,   -- clave (varchar en Supabase)
  run_ticker         STRING,
  fondo              STRING,
  manager            STRING,
  type               STRING,
  style              STRING,            -- 'ETF' | 'Passive' | ... (fund_style Passive/Active en las vistas)
  asset_class        STRING,
  category           STRING,
  region             STRING,
  alt_fund_type      STRING,
  alt_strategy       STRING,
  nt_asset_class     STRING,
  nt_sub_asset_class STRING,
  nt_category        STRING,
  nt_sub_category    STRING,
  nt_region          STRING,
  distributor        STRING
)
CLUSTER BY id
OPTIONS (description = 'Universo de fondos BD_FUNDS con taxonomia legacy y nueva (nt_*). Espejo de public.dim_bd_funds. PK logica (id).');
