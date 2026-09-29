-- Vista afp_mart.v_chist_aa  (traducida 1:1 de sync/v_alternatives_switch.sql, version vigente fase 2)
-- Base de Alternatives: detalle CHIST de alternativos (is_alternative) en USD MM con FX CLFXDOOB_sindesf.
-- mv_chist_aa es el snapshot (tabla) de esta vista; los 8 consumidores leen mv_chist_aa.
-- Traduccion de casts (PLAN §7):
--   ::varchar(N)      -> CAST(... AS STRING)            (Postgres truncaria silenciosamente a N chars; no se reproduce)
--   ::numeric(30,4)   -> ROUND(CAST(... AS NUMERIC), 4)  (misma escala; NUMERIC BigQuery = 38,9)
--   ::numeric(20,6)   -> ROUND(CAST(... AS NUMERIC), 6)
--   inversion(double) / NULLIF(valor numeric,0) / 1000000.0 -> FLOAT64 en ambos motores; luego CAST AS NUMERIC.
CREATE OR REPLACE VIEW `${project}.${mart}.v_chist_aa` AS
SELECT CAST(ca.fecha_reporte AS DATE)                                                  AS fecha,
       CAST(ca.fecha AS DATE)                                                          AS fecha_snapshot,
       CAST(ca.afp AS STRING)                                                          AS afp,
       CAST(ca.tipo_de_fondo AS STRING)                                                AS tipo_de_fondo,
       CAST(ca.tipo_de_instrumento AS STRING)                                          AS tipo_de_instrumento,
       CAST(ca.nemotecnico AS STRING)                                                  AS nemotecnico_del_instrumento,
       CAST(ca.nemotecnico AS STRING)                                                  AS nuevo_nemo,
       CAST(ca.nombre_del_emisor AS STRING)                                            AS nombre_del_emisor,
       ROUND(CAST(ca.inversion AS NUMERIC), 4)                                         AS inversion,
       CAST(CASE WHEN ca.tipo_valor = 'Remanente' THEN 'Remanente' ELSE 'NAV' END AS STRING) AS clasificacion,
       CAST(ca.fund_id AS STRING)                                                      AS fund_id,
       CAST(ca.fondo AS STRING)                                                        AS fondo,
       CAST(ca.manager AS STRING)                                                      AS manager,
       CAST(ca.region AS STRING)                                                       AS region,
       CAST(ca.category AS STRING)                                                     AS category,
       CAST(ca.alt_fund_type AS STRING)                                                AS alt_fund_type,
       CAST(ca.alt_strategy AS STRING)                                                 AS alt_strategy,
       CAST(CASE WHEN ca.region = 'Chile' THEN 'Local' ELSE ca.category END AS STRING) AS c1,
       ROUND(CAST(fx.valor AS NUMERIC), 6)                                             AS valor_tipo_cambio,
       CAST(ca.inversion / NULLIF(fx.valor, 0) / 1000000.0 AS NUMERIC)                 AS inversion_usd_mm
FROM `${project}.${mart}.v_chist_classified` ca
LEFT JOIN `${project}.${raw}.tipo_cambio` fx
       ON fx.fecha = ca.fecha_reporte
      AND fx.instrumento_codigo = 'CLFXDOOB_sindesf'
WHERE ca.is_alternative;
