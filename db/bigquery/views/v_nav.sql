-- Vista afp_mart.v_nav  (traducida 1:1 de sync/mv_alternatives_materialize.sql)
CREATE OR REPLACE VIEW `${project}.${mart}.v_nav` AS
SELECT fecha, afp, SUM(inversion_usd_mm) AS nav_usd_mm
FROM `${project}.${mart}.mv_chist_aa`
WHERE clasificacion = 'NAV'
GROUP BY fecha, afp;
