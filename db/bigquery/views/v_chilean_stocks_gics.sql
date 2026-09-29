-- Vista afp_mart.v_chilean_stocks_gics  (traducida de sync/v_chilean_stocks_switch.sql, version vigente sobre chist_adjusted;
-- la version previa en sync/chilean_stocks_gics_override.sql leia historial_carteras_full)
-- Acciones nacionales (tipo_de_instrumento='ACC') por fecha_reporte x AFP x multifondo x nemo x emisor con sector GICS
-- (dim_chilean_ticker_homol -> dim_ipd_instrumentos -> dim_ipd_gics) + override dim_chilean_stocks_gics_override, en USD MM (USDCLP Curncy).
-- Traducciones:
--   split_part(ticker,' ',1) -> SPLIT(ticker, ' ')[SAFE_OFFSET(0)];  ~~ -> LIKE
--   Los 2 subqueries correlacionados con ORDER BY ... LIMIT 1 dentro del SUM (FX exacto de la fecha, si no el ultimo FX <= fecha)
--   NO son soportados por BigQuery -> se de-correlacionan en las CTE fx_exacto / fx_asof (misma semantica: 1 FX por fecha_reporte).
--   tipo_cambio tiene PK logica (fecha, instrumento_codigo), por lo que "= fecha ORDER BY fecha DESC LIMIT 1" es 1 fila.
--   inversion (FLOAT64) / 1000000 / usd_clp (NUMERIC) -> FLOAT64, igual que double/numeric en Postgres.
CREATE OR REPLACE VIEW `${project}.${mart}.v_chilean_stocks_gics` AS
WITH fx AS (
  SELECT fecha, valor AS usd_clp
  FROM `${project}.${raw}.tipo_cambio`
  WHERE instrumento_codigo = 'USDCLP Curncy'
),
fechas AS (
  SELECT DISTINCT fecha_reporte
  FROM `${project}.${raw}.chist_adjusted`
  WHERE tipo_de_instrumento = 'ACC'
),
fx_asof AS (
  -- ultimo FX con fecha <= fecha_reporte  (equivale a: SELECT usd_clp FROM fx WHERE fx.fecha <= ch.fecha_reporte ORDER BY fx.fecha DESC LIMIT 1)
  SELECT f.fecha_reporte, x.usd_clp
  FROM fechas f
  JOIN fx x ON x.fecha <= f.fecha_reporte
  QUALIFY ROW_NUMBER() OVER (PARTITION BY f.fecha_reporte ORDER BY x.fecha DESC) = 1
),
fx_res AS (
  -- COALESCE(FX exacto de la fecha, FX as-of)
  SELECT f.fecha_reporte, COALESCE(e.usd_clp, a.usd_clp) AS usd_clp
  FROM fechas f
  LEFT JOIN fx e ON e.fecha = f.fecha_reporte
  LEFT JOIN fx_asof a ON a.fecha_reporte = f.fecha_reporte
)
SELECT ch.fecha_reporte, ch.afp, ch.tipo_de_fondo AS multifondo,
       ch.nemotecnico AS nemo, ch.nombre_del_emisor AS emisor,
       i.company_name, i.ticker_bbg,
       g.gics_sector AS gics_sub_industry_code,
       COALESCE(o.gics_sector_shortname, g.gics_sector_shortname) AS gics_sector,
       COALESCE(o.gics_sector_shortname, g.gics_sector_name) AS gics_sector_name,
       g.gics_industry_group_name AS gics_industry_group,
       g.gics_industry_name AS gics_industry,
       SUM(ch.inversion / 1000000 / r.usd_clp) AS monto_usd_mm,
       SUM(ch.inversion / 1000000) AS monto_clp_mm,
       SUM(ch.unidades) AS unidades
FROM `${project}.${raw}.chist_adjusted` ch
  JOIN `${project}.${dim}.dim_chilean_ticker_homol` h ON h.nemo = ch.nemotecnico
  JOIN `${project}.${dim}.dim_ipd_instrumentos` i
    ON SPLIT(i.ticker_bbg, ' ')[SAFE_OFFSET(0)] = h.bbg_ticker AND i.ticker_bbg LIKE '%CI Equity'
  LEFT JOIN `${project}.${dim}.dim_ipd_gics` g ON g.sector_gics = i.sector_gics
  LEFT JOIN `${project}.${dim}.dim_chilean_stocks_gics_override` o ON o.emisor = ch.nombre_del_emisor
  LEFT JOIN fx_res r ON r.fecha_reporte = ch.fecha_reporte
WHERE ch.tipo_de_instrumento = 'ACC'
GROUP BY ch.fecha_reporte, ch.afp, ch.tipo_de_fondo, ch.nemotecnico, ch.nombre_del_emisor,
         i.company_name, i.ticker_bbg, g.gics_sector,
         (COALESCE(o.gics_sector_shortname, g.gics_sector_shortname)),
         (COALESCE(o.gics_sector_shortname, g.gics_sector_name)),
         g.gics_industry_group_name, g.gics_industry_name;
