-- Dimension afp_dim.dim_ipd_gics
-- Origen: Inteligencia_Producto_Dev.dimensionales.BD_GICS (sync/sync_inteligencia_producto.py::sync_bd_gics).
-- OJO: sync_inteligencia_producto.py NO esta en los 8 pasos de main.py -> hoy es de facto una tabla
--      cuasi-manual. v_chilean_stocks_gics la necesita (JOIN por sector_gics). Se exporta como seed extra
--      (export_from_supabase.py --extra) hasta que el pipeline la incluya.
CREATE TABLE IF NOT EXISTS `${project}.${dim}.dim_ipd_gics` (
  sector_gics              STRING NOT NULL,   -- clave; TODO(dump): confirmar tipo (dim_ipd_instrumentos.sector_gics es texto de entero)
  gics_sector              STRING,            -- TODO(dump): tipo (codigo)
  gics_sector_name         STRING,
  gics_industry_group      STRING,            -- TODO(dump): tipo (codigo)
  gics_industry_group_name STRING,
  gics_industry            STRING,            -- TODO(dump): tipo (codigo)
  gics_industry_name       STRING,
  gics_sub_industry        STRING,            -- TODO(dump): tipo (codigo)
  gics_sub_industry_name   STRING,
  gics_sector_shortname    STRING,            -- 'Real Est.', 'Financials', ...
  description              STRING,
  gics_sector_shortname_2  STRING
)
OPTIONS (description = 'Taxonomia GICS (BD_GICS de Inteligencia_Producto). Espejo de public.dim_ipd_gics. PK logica (sector_gics).');
