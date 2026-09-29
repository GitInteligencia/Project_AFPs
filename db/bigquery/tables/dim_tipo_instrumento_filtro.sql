-- Dimension afp_dim.dim_tipo_instrumento_filtro
-- Origen: Inteligencia_Mercado.dbo.AFP_CL_DIM_TipoInstrumentoF1 (sync_sqlserver_to_supabase.py::sync_dim_tipo_instrumento_filtro).
-- Carga hoy: UPSERT por tipo_de_instrumento -> MERGE via afp_stg (paso `core`).
-- Nota: ya no la lee ninguna vista vigente (v_chist_aa dejo de usarla en fase 2); se conserva por alcance integro.
CREATE TABLE IF NOT EXISTS `${project}.${dim}.dim_tipo_instrumento_filtro` (
  tipo_de_instrumento STRING NOT NULL,   -- clave
  filtro1             STRING             -- 'Si' | 'No' (el sync hace strip)
)
OPTIONS (description = 'Filtro1 por tipo de instrumento (legacy alternatives). Espejo de public.dim_tipo_instrumento_filtro.');
