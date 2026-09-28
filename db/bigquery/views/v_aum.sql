-- Vista afp_mart.v_aum  (traducida 1:1 de sync/mv_alternatives_materialize.sql)
-- AUM total (USD MM) por fecha de cierre de mes x AFP. Lee la tabla mv_aum (snapshot).
CREATE OR REPLACE VIEW `${project}.${mart}.v_aum` AS
SELECT fecha, afp, aum_usd_mm
FROM `${project}.${mart}.mv_aum`;
