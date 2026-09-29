-- Vista afp_mart.v_module_freshness  (traducida de sync/v_module_freshness_add_strategy_afp_owuw.sql, ultima version en el repo)
-- Frescura por modulo/fuente: as_of_date = MAX(fecha) de cada tabla base; is_behind = as_of < hoy - expected_lag_days.
-- Traducciones:
--   NULL::date -> CAST(NULL AS DATE);  true/false -> TRUE/FALSE;
--   (CURRENT_DATE - lag::double precision * '1 day'::interval)::date -> DATE_SUB(CURRENT_DATE(), INTERVAL expected_lag_days DAY)
-- TODO(dump): la fila 'chilean_stocks' / 'Pionero/MRV (IPD)' leia ipd_positions, tabla DROPEADA el 2026-07-01
--   (PLAN_SQL_SINGLE_SOURCE.md fase 4). La version viva en Supabase debe apuntar a otra fuente; aqui se usa
--   MAX(fecha) de ipd_cartera_eom (reemplazo funcional de ipd_positions para Pionero/MRV). Confirmar con schema.sql.
-- Opcional (PLAN F2.6): si se prefiere, published_date/as_of_date pueden apoyarse en ${ops}.run_log; no se hace aqui (1:1).
CREATE OR REPLACE VIEW `${project}.${mart}.v_module_freshness` AS
WITH src AS (
  SELECT 'foreign' AS module_key, 'Holdings (CHIST)' AS source_label,
         (SELECT MAX(fecha_reporte) FROM `${project}.${raw}.chist_adjusted`) AS as_of_date,
         CAST(NULL AS DATE) AS published_date, 'deliberate' AS lag_kind, 150 AS expected_lag_days, TRUE AS is_primary
  UNION ALL SELECT 'foreign', 'Cartera agregada (SP)', (SELECT MAX(fecha) FROM `${project}.${raw}.consolidated_sd`), CAST(NULL AS DATE), 'sp_agg', 70, FALSE
  UNION ALL SELECT 'foreign', 'Retornos (Bloomberg)', (SELECT MAX(end_date) FROM `${project}.${raw}.bbg_returns`), CAST(NULL AS DATE), 'bbg', 90, FALSE
  UNION ALL SELECT 'alternatives', 'Holdings (CHIST)', (SELECT MAX(fecha_reporte) FROM `${project}.${raw}.chist_adjusted`), CAST(NULL AS DATE), 'deliberate', 150, TRUE
  UNION ALL SELECT 'market_share', 'Patrimonio/Cuota', (SELECT MAX(fecha) FROM `${project}.${raw}.valores_cuota_patrimonio`), CAST(NULL AS DATE), 'fast', 30, TRUE
  UNION ALL SELECT 'market_share', 'Cotizantes', (SELECT MAX(fecha) FROM `${project}.${raw}.cotizantes_afp`), CAST(NULL AS DATE), 'sp_agg', 75, FALSE
  UNION ALL SELECT 'asset_allocation', 'Cartera agregada (SP, _sd)', (SELECT MAX(fecha) FROM `${project}.${raw}.sd_asset_class_tipo`), CAST(NULL AS DATE), 'sp_agg', 70, TRUE
  UNION ALL SELECT 'strategy', 'Estrategias (SP)', (SELECT MAX(fecha) FROM `${project}.${raw}.consolidated_sd`), CAST(NULL AS DATE), 'sp_agg', 70, TRUE
  UNION ALL SELECT 'strategy', 'Local Equity DI (CHIST)', (SELECT MAX(fecha_reporte) FROM `${project}.${raw}.chist_adjusted`), CAST(NULL AS DATE), 'deliberate', 150, FALSE
  UNION ALL SELECT 'strategy', 'Posicionamiento AFP (CHIST)', (SELECT MAX(fecha_reporte) FROM `${project}.${raw}.chist_adjusted`), CAST(NULL AS DATE), 'deliberate', 150, FALSE
  UNION ALL SELECT 'chilean_stocks', 'Holdings (CHIST)', (SELECT MAX(fecha_reporte) FROM `${project}.${raw}.chist_adjusted`), CAST(NULL AS DATE), 'deliberate', 150, TRUE
  UNION ALL SELECT 'chilean_stocks', 'Pionero/MRV (IPD)', (SELECT MAX(fecha) FROM `${project}.${raw}.ipd_cartera_eom`), CAST(NULL AS DATE), 'ipd', 60, FALSE
  UNION ALL SELECT 'distributors', 'Holdings (CHIST)', (SELECT MAX(fecha_reporte) FROM `${project}.${raw}.chist_adjusted`), CAST(NULL AS DATE), 'deliberate', 150, TRUE
  UNION ALL SELECT 'managers', 'Holdings (CHIST)', (SELECT MAX(fecha_reporte) FROM `${project}.${raw}.chist_adjusted`), CAST(NULL AS DATE), 'deliberate', 150, TRUE
)
SELECT module_key, source_label, as_of_date, published_date, lag_kind, expected_lag_days, is_primary,
       as_of_date < DATE_SUB(CURRENT_DATE(), INTERVAL expected_lag_days DAY) AS is_behind
FROM src;
