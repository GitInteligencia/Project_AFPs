-- Mart afp_mart.mv_strategy_afp_ow_uw  (traducido 1:1 de sync/mv_strategy_afp_ow_uw.sql)
-- Posicionamiento por AFP en los fondos Moneda de cada familia (CHIST, desfasado) y over/underweight vs sistema.
-- Depende de v_chist_classified (vista), tipo_cambio, dim_bd_family_comp y v_aum (-> mv_aum): va DESPUES de mv_aum.
-- Traducciones:
--   id::text -> CAST(id AS STRING);  c.inversion (FLOAT64) / NULLIF(fx.valor,0) / 1000000.0 -> FLOAT64 (igual que double/numeric en PG)
--   x::numeric(20,4) -> ROUND(CAST(x AS NUMERIC), 4);  x::numeric -> CAST(x AS NUMERIC)
CREATE OR REPLACE TABLE `${project}.${mart}.mv_strategy_afp_ow_uw`
PARTITION BY DATE_TRUNC(fecha_reporte, MONTH)
CLUSTER BY family_id, afp
OPTIONS (description = 'OW/UW por AFP en fondos Moneda por familia (snapshot CHIST). Reconstruida por el job afp-sync, paso marts.')
AS
WITH moneda AS (
  SELECT DISTINCT family_id, CAST(id AS STRING) AS fund_id
  FROM `${project}.${dim}.dim_bd_family_comp`
  WHERE tipo = 'Moneda'
),
holdings AS (
  SELECT c.fecha_reporte, m.family_id, c.afp,
         SUM(c.inversion / NULLIF(fx.valor, 0) / 1000000.0) AS our_usd_mm
  FROM `${project}.${mart}.v_chist_classified` c
  JOIN moneda m ON m.fund_id = c.fund_id
  LEFT JOIN `${project}.${raw}.tipo_cambio` fx
    ON fx.fecha = c.fecha_reporte
   AND fx.instrumento_codigo = 'CLFXDOOB_sindesf'
  GROUP BY c.fecha_reporte, m.family_id, c.afp
),
fam_fecha AS (
  SELECT DISTINCT fecha_reporte, family_id FROM holdings
),
base AS (
  SELECT ff.fecha_reporte, ff.family_id, a.afp,
         a.aum_usd_mm,
         COALESCE(h.our_usd_mm, 0) AS our_usd_mm
  FROM fam_fecha ff
  JOIN `${project}.${mart}.v_aum` a ON a.fecha = ff.fecha_reporte
  LEFT JOIN holdings h
    ON h.fecha_reporte = ff.fecha_reporte
   AND h.family_id = ff.family_id
   AND h.afp = a.afp
),
sysavg AS (
  SELECT fecha_reporte, family_id,
         SUM(our_usd_mm) / NULLIF(SUM(aum_usd_mm), 0) AS sys_avg
  FROM base
  GROUP BY fecha_reporte, family_id
)
SELECT b.fecha_reporte,
       b.family_id,
       b.afp,
       ROUND(CAST(b.our_usd_mm AS NUMERIC), 4)                                   AS our_usd_mm,
       ROUND(CAST(b.aum_usd_mm AS NUMERIC), 4)                                   AS afp_aum_usd_mm,
       CAST(b.our_usd_mm / NULLIF(b.aum_usd_mm, 0) AS NUMERIC)                   AS weight,
       CAST(s.sys_avg AS NUMERIC)                                                AS sys_avg,
       CAST(b.our_usd_mm / NULLIF(b.aum_usd_mm, 0) - s.sys_avg AS NUMERIC)       AS ow_uw
FROM base b
JOIN sysavg s ON s.fecha_reporte = b.fecha_reporte AND s.family_id = b.family_id;
