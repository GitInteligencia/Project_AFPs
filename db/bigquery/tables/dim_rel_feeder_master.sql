-- Dimension afp_dim.dim_rel_feeder_master
-- Origen: Inteligencia_Mercado.dbo.DIM_Rel_Feeder_Master (sync_sqlserver_to_supabase.py::sync_dim_rel_feeder_master).
-- Carga hoy: UPSERT por feeder_id -> MERGE via afp_stg (paso `core`). No la lee ninguna vista vigente.
CREATE TABLE IF NOT EXISTS `${project}.${dim}.dim_rel_feeder_master` (
  feeder_id INT64 NOT NULL,   -- TODO(dump): confirmar tipo (INT vs varchar) en db/supabase_snapshot/schema.sql
  master_id INT64             -- TODO(dump): idem
)
OPTIONS (description = 'Relacion feeder -> master fund. Espejo de public.dim_rel_feeder_master.');
