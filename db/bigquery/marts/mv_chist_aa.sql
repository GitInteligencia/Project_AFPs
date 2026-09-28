-- Mart afp_mart.mv_chist_aa  (equivale a CREATE MATERIALIZED VIEW mv_chist_aa AS SELECT * FROM v_chist_aa,
-- sync/mv_alternatives_materialize.sql). Snapshot de la base pesada de Alternatives (~60k filas).
-- Se reconstruye en el paso `marts` del job (refresh_order.txt) tras `core` y `chist_adjusted`.
-- Los 9 consumidores (v_total, v_nav, v_uncalled, v_afp_c1, v_afp_c2, v_nav_c1, v_total_c1, v_uncalled_c1, v_afp_multifondo) leen esta tabla.
-- Indices Postgres (fecha, afp) y (fecha, clasificacion) -> PARTITION BY fecha mensual + CLUSTER BY afp, clasificacion.
CREATE OR REPLACE TABLE `${project}.${mart}.mv_chist_aa`
PARTITION BY DATE_TRUNC(fecha, MONTH)
CLUSTER BY afp, clasificacion, c1
OPTIONS (description = 'Snapshot de v_chist_aa (alternativos CHIST en USD MM). Reconstruida por el job afp-sync, paso marts.')
AS
SELECT * FROM `${project}.${mart}.v_chist_aa`;
