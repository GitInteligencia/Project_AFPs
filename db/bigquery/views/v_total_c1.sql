-- Vista afp_mart.v_total_c1  (traducida 1:1 de sync/mv_alternatives_materialize.sql)
CREATE OR REPLACE VIEW `${project}.${mart}.v_total_c1` AS
SELECT fecha, c1, SUM(inversion_usd_mm) AS total_usd_mm
FROM `${project}.${mart}.mv_chist_aa`
WHERE c1 IS NOT NULL
GROUP BY fecha, c1;
