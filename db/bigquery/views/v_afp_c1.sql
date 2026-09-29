-- Vista afp_mart.v_afp_c1  (traducida 1:1 de sync/mv_alternatives_materialize.sql)
-- Total alternativos por fecha x AFP x c1 (Private Equity / Private Debt / Real Asset / Other Alternative / Local).
CREATE OR REPLACE VIEW `${project}.${mart}.v_afp_c1` AS
SELECT fecha, afp, c1, SUM(inversion_usd_mm) AS total_usd_mm
FROM `${project}.${mart}.mv_chist_aa`
WHERE c1 IS NOT NULL
GROUP BY fecha, afp, c1;
