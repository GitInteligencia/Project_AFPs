-- Vista afp_mart.v_nav_c1  (traducida 1:1 de sync/mv_alternatives_materialize.sql). No la lee la web; se conserva por alcance integro.
CREATE OR REPLACE VIEW `${project}.${mart}.v_nav_c1` AS
SELECT fecha, c1, SUM(inversion_usd_mm) AS nav_usd_mm
FROM `${project}.${mart}.mv_chist_aa`
WHERE clasificacion = 'NAV' AND c1 IS NOT NULL
GROUP BY fecha, c1;
