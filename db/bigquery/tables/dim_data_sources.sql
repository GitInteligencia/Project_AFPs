-- Dimension manual afp_dim.dim_data_sources (PLAN §6.2)
-- Metadata de procedencia por dataset (SourceBadge). Columnas = las que lee web/lib/queries-data-sources.ts
-- y web/lib/types-data-sources.ts. apply.py puede actualizar last_loaded_at al recargar seeds.
-- Se carga desde db/seeds/dim_data_sources.csv (WRITE_TRUNCATE).
CREATE TABLE IF NOT EXISTS `${project}.${dim}.dim_data_sources` (
  dataset_key        STRING NOT NULL,
  display_name       STRING NOT NULL,
  current_source     STRING NOT NULL,   -- 'AUTO' | 'EXCEL_SEED' | 'MANUAL'
  target_source      STRING NOT NULL,   -- 'AUTO' | 'MANUAL'
  pdf_section        STRING,
  excel_seed_path    STRING,
  excel_seed_periodo STRING,
  last_loaded_at     TIMESTAMP,
  last_loaded_by     STRING,
  migration_plan     STRING,
  notes              STRING
)
OPTIONS (description = 'Metadata de procedencia/frescura por dataset (manual). Espejo de public.dim_data_sources. PK logica (dataset_key).');
