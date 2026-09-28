-- Tabla espejo afp_raw.chist_adjusted
-- Origen: Inteligencia_Mercado.dbo.AFP_CL_CHIST_ADJUSTED (sync/sync_chist_adjusted.py,
--         DDL Postgres en sync/chist_adjusted_schema.sql). Detalle por AFP x instrumento CON desfase,
--         ventana 2025+, excluye supracategorias Direct Inv. RF Nacional / Derivados / Disponible Nacional.
-- tipo_valor: 'Valorizacion' (NAV) | 'Remanente' (uncalled).
-- Carga: DELETE por fecha + append (paso `chist_adjusted`); despues se reconstruyen los marts.
-- Consumidores: v_chist_classified, v_chist_foreign_classified, v_chilean_stocks_gics, v_module_freshness.
CREATE TABLE IF NOT EXISTS `${project}.${raw}.chist_adjusted` (
  fila_id                 INT64,     -- BIGSERIAL en Postgres; lo asigna el pipeline si se necesita (v_chist_classified lo expone)
  fecha_reporte           DATE,      -- fecha de reporte (la que usan las vistas como `fecha` de negocio)
  fecha                   DATE NOT NULL,   -- fecha snapshot de la cartera
  afp                     STRING,
  tipo_de_fondo           STRING,
  tipo_de_instrumento     STRING,
  nemotecnico             STRING,
  nombre_del_emisor       STRING,
  nacionalidad_del_emisor STRING,    -- 'N' | 'E'
  unidades                INT64,
  precio                  FLOAT64,   -- double precision en Postgres
  inversion               FLOAT64,   -- CLP, double precision en Postgres (las vistas castean a NUMERIC)
  supracategory           STRING,
  tipo_valor              STRING
)
PARTITION BY DATE_TRUNC(fecha, MONTH)
CLUSTER BY afp, tipo_de_fondo, supracategory, nemotecnico
OPTIONS (description = 'Detalle de cartera CHIST ajustado, por AFP x instrumento, 2025+. Espejo de public.chist_adjusted.');
