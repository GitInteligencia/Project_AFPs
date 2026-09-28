-- Tabla espejo afp_raw.sd_asset_class_tipo
-- Origen: Inteligencia_Mercado.dbo.AFP_CL_01_sd (sync/sync_sd_asset_class.py). Sistema por tipo de fondo,
--         ya en USD MM con taxonomia nivel_1 x nivel_2 x glosa. Ventana fecha >= 2025-01-01.
-- Carga: DELETE por fecha + append (paso `sd_asset_class`).
-- Consumidores: v_asset_class_tipo_sd, v_asset_class_dates_sd (pendiente dump), v_module_freshness.
-- Columnas = alias del SELECT del sync (no hay *_schema.sql en el repo).
CREATE TABLE IF NOT EXISTS `${project}.${raw}.sd_asset_class_tipo` (
  fecha       DATE   NOT NULL,
  tipo_fondo  STRING,          -- 'A'..'E'
  nivel_1     STRING,          -- INVERSION NACIONAL / EXTRANJERA
  nivel_2     STRING,          -- RENTA VARIABLE / RENTA FIJA / DERIVADOS / OTROS
  glosa       STRING,          -- detalle (p.ej. 'Activos Alternativos')
  monto_usdmm NUMERIC
  -- TODO(dump): confirmar si existe fila_id BIGSERIAL u otras columnas en db/supabase_snapshot/schema.sql
)
PARTITION BY DATE_TRUNC(fecha, MONTH)
CLUSTER BY tipo_fondo
OPTIONS (description = 'Asset allocation SP por tipo de fondo (AFP_CL_01_sd). Espejo de public.sd_asset_class_tipo.');
