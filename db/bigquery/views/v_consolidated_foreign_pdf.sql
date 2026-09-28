-- Vista afp_mart.v_consolidated_foreign_pdf  (traducida 1:1 de sync/v_foreign_consolidated_switch.sql)
-- Buckets PDF Sec 07 (legacy y nueva taxonomia nt_*) sobre v_consolidated_foreign_classified.
-- Traduccion: x = ANY (ARRAY[...]) -> x IN (...); casts ::text/::varchar eliminados (todo STRING).
CREATE OR REPLACE VIEW `${project}.${mart}.v_consolidated_foreign_pdf` AS
SELECT fecha_reporte, periodo, emisor, isin, monto_dolares, fund_id, asset_class, category, region, is_sovereign,
  CASE
    WHEN fund_id IS NOT NULL AND asset_class = 'Equity' THEN 'Equity'
    WHEN fund_id IS NOT NULL AND asset_class = 'Fixed Income' THEN 'Fixed Income'
    WHEN fund_id IS NOT NULL AND asset_class = 'Alternative' THEN 'Private Equity'
    WHEN fund_id IS NOT NULL AND asset_class IN ('Balanced','AR/HF') THEN 'Other'
    WHEN fund_id IS NULL THEN 'Direct Investment'
    ELSE 'Unknown' END AS pdf_bucket,
  CASE
    WHEN region IN ('GEM','Latam','Asia Pacific','Asia Pacific ex Japan','Emerging Europe') THEN 'Emerging Markets'
    WHEN region IN ('Global','North America','Europe','Japan','Australia') THEN 'Developed Markets'
    ELSE NULL END AS pdf_em_dm,
  CASE WHEN region = 'Asia Pacific' AND asset_class = 'Equity' THEN 'Asia Pacific ex Japan' ELSE region END AS pdf_subregion,
  CASE WHEN asset_class = 'Fixed Income' THEN category ELSE NULL END AS pdf_fi_category,
  CASE
    WHEN fund_id IS NOT NULL AND nt_asset_class = 'Equity' THEN 'Equity'
    WHEN fund_id IS NOT NULL AND nt_asset_class = 'Fixed Income' THEN 'Fixed Income'
    WHEN fund_id IS NOT NULL AND nt_asset_class = 'Alternative' THEN 'Private Equity'
    WHEN fund_id IS NOT NULL THEN 'Other'
    WHEN fund_id IS NULL THEN 'Direct Investment'
    ELSE 'Unknown' END AS pdf_bucket_nt,
  CASE
    WHEN nt_region IN ('GEM','Latam','Brazil','Asia Pacific','Asia Pacific ex Japan','Emerging Europe','Middle East','RoW') THEN 'Emerging Markets'
    WHEN nt_region IN ('Global','North America','Europe','Japan','Australia') THEN 'Developed Markets'
    ELSE NULL END AS pdf_em_dm_nt,
  CASE WHEN nt_region = 'Asia Pacific' AND nt_asset_class = 'Equity' THEN 'Asia Pacific ex Japan' ELSE nt_region END AS pdf_subregion_nt,
  CASE WHEN nt_asset_class = 'Fixed Income' THEN nt_sub_category ELSE NULL END AS pdf_fi_category_nt
FROM `${project}.${mart}.v_consolidated_foreign_classified`;
