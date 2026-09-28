-- Tabla espejo afp_raw.consolidated_sd
-- Origen: Inteligencia_Mercado.dbo.AFP_CL_09_17_25_sd_consolidated (sync/sync_consolidated_sd.py,
--         DDL Postgres en sync/consolidated_sd_schema.sql). Nivel sistema, sin desfase, historia 2012-05+.
-- source = cuadro SP de origen: '09'/'17' nacional, '25' extranjero, '17+25' ambos.
-- Carga: DELETE por fecha + append (paso `consolidated_sd`).
-- Consumidores: v_consolidated_classified, v_consolidated_foreign_classified, v_sp_direct_investment_detail,
--               v_sp_local_equity_di_vs_if, v_module_freshness.
CREATE TABLE IF NOT EXISTS `${project}.${raw}.consolidated_sd` (
  fila_id        INT64,             -- BIGSERIAL en Postgres; en BigQuery lo asigna el pipeline (opcional, solo trazabilidad)
  fecha          DATE   NOT NULL,
  tipo_fondo     STRING NOT NULL,   -- A..E
  nemotecnico    STRING NOT NULL,   -- ISIN para source 25
  source         STRING,            -- '09' | '17' | '25' | '17+25'
  lim_nac_usdmm  NUMERIC,
  lim_extr_usdmm NUMERIC,
  monto_usdmm    NUMERIC
)
PARTITION BY DATE_TRUNC(fecha, MONTH)
CLUSTER BY tipo_fondo, source, nemotecnico
OPTIONS (description = 'Cartera consolidada SP sin desfase (cuadros 09/17/25), nivel sistema. Espejo de public.consolidated_sd.');
