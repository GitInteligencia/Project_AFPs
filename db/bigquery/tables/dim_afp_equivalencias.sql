-- Dimension afp_dim.dim_afp_equivalencias
-- Origen: Inteligencia_Mercado.dbo.AFP_CL_DIM_EQUIVALENCIAS (sync/sync_sqlserver_to_supabase.py::sync_dim_afp_equivalencias).
-- Carga hoy: UPSERT por `original` -> MERGE via afp_stg (paso `core`). Sin particion (dimension chica).
CREATE TABLE IF NOT EXISTS `${project}.${dim}.dim_afp_equivalencias` (
  original  STRING NOT NULL,   -- clave
  reemplazo STRING
)
OPTIONS (description = 'Equivalencias de nombres de AFP. Espejo de public.dim_afp_equivalencias. PK logica (original).');
