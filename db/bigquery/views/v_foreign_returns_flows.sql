-- Vista afp_mart.v_foreign_returns_flows  (traducida 1:1 de sync/v_foreign_flows_switch.sql)
-- Por (fecha_reporte, isin): posicion actual/previa, cambio, retorno (pos_prev x usd_ret/100) y flujo (cambio - retorno).
-- Solo pares de meses consecutivos con ambas posiciones y con retornos Bloomberg en la fecha.
-- Es la base de mv_foreign_fund_flows / mv_foreign_returns_flows_summary (pendientes de dump).
-- Traducciones:
--   date_trunc('month', f)::date - 1        -> DATE_SUB(DATE_TRUNC(f, MONTH), INTERVAL 1 DAY)
--   CROSS JOIN LATERAL (SELECT isin ... UNION SELECT isin ...) -> UNION DISTINCT de dos equi-joins (mismo conjunto de isin por par)
--   x::double precision -> CAST(x AS FLOAT64);  0::numeric -> 0 (INT64 se promueve a NUMERIC en COALESCE)
--   pdf_bucket = ANY (ARRAY[...]) -> IN (...);  upper() -> UPPER()
CREATE OR REPLACE VIEW `${project}.${mart}.v_foreign_returns_flows` AS
WITH pos AS (
  SELECT fecha_reporte, isin,
    MAX(pdf_bucket) AS pdf_bucket, MAX(pdf_em_dm) AS pdf_em_dm,
    MAX(pdf_subregion) AS pdf_subregion, MAX(pdf_fi_category) AS pdf_fi_category,
    MAX(pdf_bucket_nt) AS pdf_bucket_nt, MAX(pdf_em_dm_nt) AS pdf_em_dm_nt,
    MAX(pdf_subregion_nt) AS pdf_subregion_nt, MAX(pdf_fi_category_nt) AS pdf_fi_category_nt,
    SUM(monto_dolares) AS pos_usd
  FROM `${project}.${mart}.v_consolidated_foreign_pdf`
  WHERE pdf_bucket IN ('Equity','Fixed Income','Private Equity')
  GROUP BY fecha_reporte, isin
),
fechas AS (SELECT DISTINCT fecha_reporte FROM pos),
pares AS (
  SELECT f.fecha_reporte, DATE_SUB(DATE_TRUNC(f.fecha_reporte, MONTH), INTERVAL 1 DAY) AS fecha_prev
  FROM fechas f
  WHERE DATE_SUB(DATE_TRUNC(f.fecha_reporte, MONTH), INTERVAL 1 DAY) IN (SELECT fecha_reporte FROM fechas)
    AND f.fecha_reporte IN (SELECT DISTINCT end_date FROM `${project}.${raw}.bbg_returns`)
),
ids AS (
  SELECT p.fecha_reporte, p.fecha_prev, c.isin
  FROM pares p JOIN pos c ON c.fecha_reporte = p.fecha_reporte
  UNION DISTINCT
  SELECT p.fecha_reporte, p.fecha_prev, a.isin
  FROM pares p JOIN pos a ON a.fecha_reporte = p.fecha_prev
)
SELECT ids.fecha_reporte, ids.isin,
  COALESCE(c.pdf_bucket, a.pdf_bucket) AS pdf_bucket,
  COALESCE(c.pdf_em_dm, a.pdf_em_dm) AS pdf_em_dm,
  COALESCE(c.pdf_subregion, a.pdf_subregion) AS pdf_subregion,
  COALESCE(c.pdf_fi_category, a.pdf_fi_category) AS pdf_fi_category,
  COALESCE(c.pdf_bucket_nt, a.pdf_bucket_nt) AS pdf_bucket_nt,
  COALESCE(c.pdf_em_dm_nt, a.pdf_em_dm_nt) AS pdf_em_dm_nt,
  COALESCE(c.pdf_subregion_nt, a.pdf_subregion_nt) AS pdf_subregion_nt,
  COALESCE(c.pdf_fi_category_nt, a.pdf_fi_category_nt) AS pdf_fi_category_nt,
  COALESCE(c.pos_usd, 0) AS pos_usd,
  COALESCE(a.pos_usd, 0) AS pos_prev_usd,
  COALESCE(c.pos_usd, 0) - COALESCE(a.pos_usd, 0) AS change_usd_mm,
  CASE WHEN c.isin IS NOT NULL AND a.isin IS NOT NULL
       THEN CAST(a.pos_usd AS FLOAT64) * COALESCE(r.usd_ret, 0.0) / 100.0
       ELSE 0.0 END AS return_usd_mm,
  CAST(COALESCE(c.pos_usd, 0) - COALESCE(a.pos_usd, 0) AS FLOAT64) -
  CASE WHEN c.isin IS NOT NULL AND a.isin IS NOT NULL
       THEN CAST(a.pos_usd AS FLOAT64) * COALESCE(r.usd_ret, 0.0) / 100.0
       ELSE 0.0 END AS flow_usd_mm
FROM ids
LEFT JOIN pos c ON c.fecha_reporte = ids.fecha_reporte AND c.isin = ids.isin
LEFT JOIN pos a ON a.fecha_reporte = ids.fecha_prev AND a.isin = ids.isin
LEFT JOIN `${project}.${raw}.bbg_returns` r ON r.end_date = ids.fecha_reporte AND UPPER(r.nemo_sp) = UPPER(ids.isin);
