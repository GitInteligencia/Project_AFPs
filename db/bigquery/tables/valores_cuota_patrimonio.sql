-- Tabla espejo afp_raw.valores_cuota_patrimonio
-- Origen: Inteligencia_Mercado.dbo.AFP_CL_VC_PAT (sync/sync_sqlserver_to_supabase.py::sync_valores_cuota_patrimonio),
--         piso fijo fecha >= 2020-01-01.
-- Carga hoy: UPSERT (fecha, multifondo, afp) -> MERGE via afp_stg (paso `core`).
-- Consumidores: mv_aum, v_module_freshness, web (getOverviewDetail), v_returns_afp_tipo (pendiente dump).
CREATE TABLE IF NOT EXISTS `${project}.${raw}.valores_cuota_patrimonio` (
  fecha            DATE    NOT NULL,
  multifondo       STRING  NOT NULL,   -- A..E
  afp              STRING  NOT NULL,
  valor_cuota      NUMERIC,            -- TODO(dump): confirmar precision (numeric en Supabase)
  valor_patrimonio NUMERIC             -- CLP; mv_aum divide por tipo_cambio.valor / 1e6
)
PARTITION BY DATE_TRUNC(fecha, MONTH)
CLUSTER BY afp, multifondo
OPTIONS (description = 'Valor cuota y patrimonio diario por AFP x multifondo (SP). Espejo de public.valores_cuota_patrimonio. PK logica (fecha, multifondo, afp).');
