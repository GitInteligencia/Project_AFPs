-- Mart afp_mart.mv_sp_direct_investment_detail  (matview referenciada en sync/v_foreign_di_switch.sql: "front DI card")
-- Snapshot de v_sp_direct_investment_detail. La web (queries-foreign-di.ts) lee
-- periodo, fecha_valor, asset_class, di_category, country, currency, usd_mm, todas presentes en la vista.
-- TODO(dump): confirmar con schema.sql que la matview es exactamente SELECT * FROM v_sp_direct_investment_detail
--   (no hay DDL del CREATE MATERIALIZED VIEW en el repo, solo su REFRESH).
CREATE OR REPLACE TABLE `${project}.${mart}.mv_sp_direct_investment_detail`
PARTITION BY DATE_TRUNC(fecha_valor, MONTH)
CLUSTER BY periodo, asset_class
OPTIONS (description = 'Snapshot de v_sp_direct_investment_detail (DI extranjera por ISIN). Reconstruida por el job afp-sync, paso marts.')
AS
SELECT * FROM `${project}.${mart}.v_sp_direct_investment_detail`;
