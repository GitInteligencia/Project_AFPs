-- Dimension manual afp_dim.dim_foreign_classification_overlay (PLAN §6.2)
-- Clasificacion maestra por ISIN (hoja Output_25sd del Excel legacy; sync/load_foreign_overlay.py).
-- Columnas = payload de load_foreign_overlay.py + updated_at/updated_by de web/lib/types-overlay.ts.
-- Uso: v_chist_foreign_classified, v_consolidated_foreign_classified (category/region), v_distributors_sec09 (family/manager).
-- Se carga desde db/seeds/dim_foreign_classification_overlay.csv (WRITE_TRUNCATE).
CREATE TABLE IF NOT EXISTS `${project}.${dim}.dim_foreign_classification_overlay` (
  identificador STRING NOT NULL,   -- ISIN (clave; las vistas comparan upper())
  asset_class   STRING,
  region        STRING,
  country       STRING,
  category      STRING,
  currency      STRING,
  family        STRING,            -- distribuidor (v_distributors_sec09)
  manager       STRING,
  fondo         STRING,
  fund_type     STRING,
  fund_style    STRING,
  alt_id        STRING,
  updated_at    TIMESTAMP,
  updated_by    STRING
)
OPTIONS (description = 'Overlay de clasificacion foreign por ISIN (manual, Output_25sd). Espejo de public.dim_foreign_classification_overlay.');
