-- Vista afp_mart.v_uncalled  (traducida 1:1 de sync/mv_alternatives_materialize.sql)
CREATE OR REPLACE VIEW `${project}.${mart}.v_uncalled` AS
SELECT fecha, afp, SUM(inversion_usd_mm) AS uncalled_usd_mm
FROM `${project}.${mart}.mv_chist_aa`
WHERE clasificacion = 'Remanente'
GROUP BY fecha, afp;
