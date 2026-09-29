-- Dimension manual afp_dim.dim_bdchile (PLAN §6.2)
-- Dimensional Patria BDChile de acciones chilenas, cargada desde bdchile.json (excel/seed/load_bdchile.py, gitignorado).
-- Segun LINEAGE.md hoy se mantiene SOLO por company/grupo, usada por f_sec05_top40 (company_name, group_name).
-- El esquema NO esta en el repo:
-- TODO(dump): confirmar TODAS las columnas con db/supabase_snapshot/schema.sql (o con el CSV exportado).
CREATE TABLE IF NOT EXISTS `${project}.${dim}.dim_bdchile` (
  nemo        STRING,   -- TODO(dump): hipotesis (clave de join con v_chilean_stocks_gics.nemo)
  company     STRING,   -- TODO(dump): hipotesis -> f_sec05_top40.company_name
  grupo       STRING    -- TODO(dump): hipotesis -> f_sec05_top40.group_name
)
OPTIONS (description = 'Dimensional BDChile (company / grupo economico) para Sec05 (manual). Espejo de public.dim_bdchile. ESQUEMA A CONFIRMAR CON DUMP.');
