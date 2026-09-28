-- Vista afp_mart.v_fund_class  (traducida 1:1 de sync/v_classification_layer.sql)
-- nemo -> atributos de fondo (BD_FUNDS), deduplicado por prioridad de source en HOMOL:
--   AFP_CL > LICS_CL > CARTERAS_FM_CMF > RUT_CMF > resto. Una fila por nemo.
-- Traduccion: bf.id::text = h.id::text -> CAST(... AS STRING); el resto es identico.
CREATE OR REPLACE VIEW `${project}.${mart}.v_fund_class` AS
SELECT h.nemo,
       bf.id          AS fund_id,
       bf.fondo,
       bf.manager,
       bf.asset_class,
       bf.category,
       bf.region,
       bf.alt_fund_type,
       bf.alt_strategy,
       bf.nt_asset_class,
       bf.nt_sub_asset_class,
       bf.nt_category,
       bf.nt_sub_category,
       bf.nt_region,
       (bf.asset_class = 'Alternative') AS is_alt_fund
FROM (
    SELECT name AS nemo, id,
           ROW_NUMBER() OVER (PARTITION BY name ORDER BY
             CASE source WHEN 'AFP_CL' THEN 1 WHEN 'LICS_CL' THEN 2
                         WHEN 'CARTERAS_FM_CMF' THEN 3 WHEN 'RUT_CMF' THEN 4
                         ELSE 5 END) AS rn
    FROM `${project}.${dim}.dim_homol_funds`
) h
JOIN `${project}.${dim}.dim_bd_funds` bf ON CAST(bf.id AS STRING) = CAST(h.id AS STRING)
WHERE h.rn = 1;
