-- Vista afp_mart.v_afp_c2  (traducida 1:1 de sync/mv_alternatives_materialize.sql)
-- Total alternativos por fecha x AFP x region(Local/Foreign) x category x alt_fund_type x alt_strategy.
-- La web pagina ordenando por (fecha, afp, region, category, alt_fund_type, alt_strategy).
-- El alias `region` coincide con la columna `region` de mv_chist_aa; en BigQuery el GROUP BY resuelve primero el alias,
-- asi que repetir la expresion CASE (como hace Postgres) seria ambiguo: se agrupa por ORDINALES (1..6 = las 6 columnas no agregadas).
CREATE OR REPLACE VIEW `${project}.${mart}.v_afp_c2` AS
SELECT fecha, afp,
       CASE WHEN region = 'Chile' THEN 'Local' ELSE 'Foreign' END AS region,
       category, alt_fund_type, alt_strategy,
       SUM(inversion_usd_mm) AS total_usd_mm
FROM `${project}.${mart}.mv_chist_aa`
GROUP BY 1, 2, 3, 4, 5, 6;
