-- Dimension manual afp_dim.dim_valorizacion_remanente (16 filas, sin fuente SQL Server; PLAN §6.2)
-- Hoy mantenida a mano en Supabase; el sync la salta a proposito (sync_sqlserver_to_supabase.py).
-- Ya NO la lee ninguna vista vigente (v_chist_aa usa chist_adjusted.tipo_valor desde fase 2), se conserva
-- por alcance integro. Se carga desde db/seeds/dim_valorizacion_remanente.csv (WRITE_TRUNCATE).
-- El esquema NO se deduce de ningun archivo del repo:
-- TODO(dump): confirmar TODAS las columnas con db/supabase_snapshot/schema.sql (o con el CSV exportado).
CREATE TABLE IF NOT EXISTS `${project}.${dim}.dim_valorizacion_remanente` (
  tipo_de_instrumento STRING,   -- TODO(dump): hipotesis (clave legacy de clasificacion NAV/Remanente)
  clasificacion       STRING    -- TODO(dump): hipotesis ('NAV' | 'Remanente')
)
OPTIONS (description = 'Clasificacion legacy NAV/Remanente por tipo de instrumento (manual). Espejo de public.dim_valorizacion_remanente. ESQUEMA A CONFIRMAR CON DUMP.');
