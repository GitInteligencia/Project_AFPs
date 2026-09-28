-- Dimension manual afp_dim.dim_foreign_region_override (PLAN §6.2)
-- Override manual de region por fund_id, validado vs PDF Sec 07 (sync/sp_foreign_apply_overlay.sql).
-- Uso: LEFT JOIN dim_foreign_region_override ovr ON ovr.fund_id = fc.fund_id::text  (fund_id es TEXT).
-- Se carga desde db/seeds/dim_foreign_region_override.csv (WRITE_TRUNCATE).
CREATE TABLE IF NOT EXISTS `${project}.${dim}.dim_foreign_region_override` (
  fund_id STRING NOT NULL,   -- dim_bd_funds.id como texto
  region  STRING NOT NULL
  -- TODO(dump): confirmar columnas adicionales (notes, updated_at, updated_by) en db/supabase_snapshot/schema.sql
)
OPTIONS (description = 'Override manual de region por fondo para Foreign (manual). Espejo de public.dim_foreign_region_override.');
