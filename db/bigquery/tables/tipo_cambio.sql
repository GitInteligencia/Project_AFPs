-- Tabla espejo afp_raw.tipo_cambio
-- Origen: DW_MONEDA.dbo.TBL_RENTABILIDADES_DW (sync/sync_sqlserver_to_supabase.py::sync_tipo_cambio).
-- Series: 'CLFXDOOB_sindesf' (dolar observado BCCh) y 'USDCLP Curncy' (Bloomberg).
-- Carga hoy: UPSERT (fecha, instrumento_codigo) -> en BigQuery MERGE via afp_stg (paso `core`).
-- Consumidores: mv_aum, v_chist_aa, mv_chist_foreign_managers, v_chilean_stocks_gics,
--               v_sp_local_equity_di_vs_if, mv_strategy_afp_ow_uw, web (getOverviewDetail, getFxClpPerUsd).
CREATE TABLE IF NOT EXISTS `${project}.${raw}.tipo_cambio` (
  fecha              DATE    NOT NULL,
  instrumento_codigo STRING  NOT NULL,
  valor              NUMERIC            -- TODO(dump): confirmar precision/escala con db/supabase_snapshot/schema.sql (hoy numeric; las vistas hacen NULLIF(valor, 0::numeric))
)
PARTITION BY DATE_TRUNC(fecha, MONTH)
CLUSTER BY instrumento_codigo
OPTIONS (description = 'Tipos de cambio diarios (CLFXDOOB_sindesf, USDCLP Curncy). Espejo de public.tipo_cambio. PK logica (fecha, instrumento_codigo).');
