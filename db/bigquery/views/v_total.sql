-- Vista afp_mart.v_total  (traducida 1:1 de sync/mv_alternatives_materialize.sql)
-- Total alternativos (NAV + Uncalled) USD MM por fecha x AFP. Lee la tabla mv_chist_aa (snapshot de v_chist_aa).
CREATE OR REPLACE VIEW `${project}.${mart}.v_total` AS
SELECT fecha, afp, SUM(inversion_usd_mm) AS total_usd_mm
FROM `${project}.${mart}.mv_chist_aa`
GROUP BY fecha, afp;
