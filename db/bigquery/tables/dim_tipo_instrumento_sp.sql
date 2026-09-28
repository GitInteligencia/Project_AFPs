-- Dimension afp_dim.dim_tipo_instrumento_sp
-- Origen: Inteligencia_Mercado.dbo.TBL_SPE_TIPOS_INSTRUMENTOS (sync_sqlserver_to_supabase.py::sync_dim_tipo_instrumento_sp).
-- Carga hoy: UPSERT por codigo -> MERGE via afp_stg (paso `core`).
-- Consumidores: v_chist_foreign_classified (join por codigo = tipo_de_instrumento).
CREATE TABLE IF NOT EXISTS `${project}.${dim}.dim_tipo_instrumento_sp` (
  codigo      STRING NOT NULL,
  descripcion STRING,
  c1          STRING,   -- Local / Foreign / Forward
  c2          STRING,   -- NAV / Remanente
  c3          STRING,   -- liquido / iliquido
  c4          STRING    -- asset class granular
)
OPTIONS (description = 'Clasificacion oficial SP por codigo de tipo de instrumento. Espejo de public.dim_tipo_instrumento_sp.');
