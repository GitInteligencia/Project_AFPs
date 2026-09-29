-- Tabla espejo afp_raw.sd_asset_class_afp
-- Origen: Inteligencia_Mercado.dbo.AFP_CL_02_sd (sync/sync_sd_asset_class.py). Por AFP x tipo de fondo.
-- Carga: DELETE por fecha + append (paso `sd_asset_class`).
-- Consumidores: v_asset_class_afp_sd, v_local_fi_by_afp_sd (pendiente dump).
CREATE TABLE IF NOT EXISTS `${project}.${raw}.sd_asset_class_afp` (
  fecha       DATE   NOT NULL,
  afp         STRING,
  tipo_fondo  STRING,
  nivel_1     STRING,
  nivel_2     STRING,
  glosa       STRING,
  monto_usdmm NUMERIC
  -- TODO(dump): confirmar si existe fila_id BIGSERIAL u otras columnas en db/supabase_snapshot/schema.sql
)
PARTITION BY DATE_TRUNC(fecha, MONTH)
CLUSTER BY afp, tipo_fondo
OPTIONS (description = 'Asset allocation SP por AFP x tipo de fondo (AFP_CL_02_sd). Espejo de public.sd_asset_class_afp.');
