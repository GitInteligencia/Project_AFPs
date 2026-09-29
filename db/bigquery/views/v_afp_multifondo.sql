-- Vista afp_mart.v_afp_multifondo  (traducida 1:1 de sync/v_afp_multifondo.sql)
-- Alternativos por (fecha, afp, tipo_de_fondo) pivotando clasificacion -> Total / NAV / Uncalled.
-- Traduccion: sum(x) FILTER (WHERE c) -> SUM(IF(c, x, NULL))  (PLAN §7).
CREATE OR REPLACE VIEW `${project}.${mart}.v_afp_multifondo` AS
SELECT fecha, afp, tipo_de_fondo,
       SUM(inversion_usd_mm)                                            AS total_usd_mm,
       SUM(IF(clasificacion = 'NAV',       inversion_usd_mm, NULL))     AS nav_usd_mm,
       SUM(IF(clasificacion = 'Remanente', inversion_usd_mm, NULL))     AS uncalled_usd_mm
FROM `${project}.${mart}.mv_chist_aa`
GROUP BY fecha, afp, tipo_de_fondo;
