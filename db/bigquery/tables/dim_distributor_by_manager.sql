-- Dimension manual afp_dim.dim_distributor_by_manager (PLAN §6.2)
-- Mapeo manager -> distribuidor local (admin UI de Distributors). Columnas = las que lee
-- web/lib/queries-distributors.ts::getDistributorMapping y web/lib/types-distributors.ts.
-- Se carga desde db/seeds/dim_distributor_by_manager.csv (WRITE_TRUNCATE).
CREATE TABLE IF NOT EXISTS `${project}.${dim}.dim_distributor_by_manager` (
  manager      STRING NOT NULL,
  distributor  STRING NOT NULL,
  is_ambiguous BOOL,
  notes        STRING,
  updated_at   TIMESTAMP,
  updated_by   STRING
)
OPTIONS (description = 'Mapeo manager -> distribuidor (manual, admin UI). Espejo de public.dim_distributor_by_manager. PK logica (manager).');
