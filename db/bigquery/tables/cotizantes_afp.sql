-- Tabla espejo afp_raw.cotizantes_afp
-- Origen: Inteligencia_Mercado.dbo.AFP_CL_Cotizantes (sync/sync_sp_sqlserver_to_supabase.py,
--         DDL Postgres en sync/sp_cotizantes_schema.sql). PK logica: (fecha, afp).
-- Carga: DELETE fecha >= ventana + append (paso `cotizantes`). Solo las 7 AFP (sin fila TOTAL).
-- Consumidores: v_contributors_market_share, v_module_freshness.
CREATE TABLE IF NOT EXISTS `${project}.${raw}.cotizantes_afp` (
  fecha        DATE   NOT NULL,   -- ultimo dia del periodo (p.ej. 2026-02-28)
  afp          STRING NOT NULL,   -- CAPITAL/CUPRUM/HABITAT/MODELO/PLANVITAL/PROVIDA/UNO
  n_cotizantes INT64  NOT NULL
)
PARTITION BY DATE_TRUNC(fecha, MONTH)
CLUSTER BY afp
OPTIONS (description = 'Cotizantes mensuales por AFP (SP). Espejo de public.cotizantes_afp. PK logica (fecha, afp).');
