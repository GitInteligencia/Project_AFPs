-- Dimension afp_dim.dim_homol_funds
-- Origen: Inteligencia_Mercado.dbo.DIM_HOMOL_FUNDS_INTMDO, sources AFP_CL / LICS_CL / CARTERAS_FM_CMF / RUT_CMF / RENTABILIDADES
--         (sync_sqlserver_to_supabase.py::sync_dim_homol_funds).
-- Carga hoy: UPSERT por (name, source) -> MERGE via afp_stg (paso `core`).
-- Consumidores: v_fund_class y todos los fund_class CTE (dedupe por prioridad de source).
CREATE TABLE IF NOT EXISTS `${project}.${dim}.dim_homol_funds` (
  name   STRING NOT NULL,   -- nemo / ISIN / ticker / RUT segun source
  id     STRING,            -- dim_bd_funds.id. TODO(dump): confirmar tipo (las vistas comparan id::text = id::text)
  source STRING NOT NULL
)
CLUSTER BY name
OPTIONS (description = 'Homologacion identificador -> fondo (BD_FUNDS). Espejo de public.dim_homol_funds. PK logica (name, source).');
