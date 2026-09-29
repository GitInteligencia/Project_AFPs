-- Dimension manual afp_dim.dim_chilean_stocks_gics_override (PLAN §6.2)
-- DDL Postgres completo en sync/chilean_stocks_gics_override.sql. Override curado emisor -> sector GICS corto
-- para cuadrar la tarjeta GICS con el PDF Sec 05. gics_sector_shortname debe coincidir EXACTO con
-- dim_ipd_gics.gics_sector_shortname ('Real Est.', no 'Real Estate').
-- Se carga desde db/seeds/dim_chilean_stocks_gics_override.csv (WRITE_TRUNCATE).
CREATE TABLE IF NOT EXISTS `${project}.${dim}.dim_chilean_stocks_gics_override` (
  emisor                STRING NOT NULL,   -- nombre_del_emisor tal como viene en CHIST
  gics_sector_shortname STRING NOT NULL,
  notes                 STRING
)
OPTIONS (description = 'Overrides emisor -> sector GICS para v_chilean_stocks_gics (manual). Espejo de public.dim_chilean_stocks_gics_override.');
