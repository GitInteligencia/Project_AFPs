-- Tabla operacional afp_ops.run_log
-- La escribe el Cloud Run Job (main.py) al terminar cada paso del pipeline, via sync/bq_io.log_run.
-- Sin equivalente en Supabase. Sirve para auditoria de corridas, apoyo opcional de
-- v_module_freshness (PLAN F2.6) y alertas.
-- El esquema DEBE coincidir con RUN_LOG_DDL en sync/bq_io.py (si la tabla no existe, bq_io la crea con ese mismo esquema).
CREATE TABLE IF NOT EXISTS `${project}.${ops}.run_log` (
  run_id      STRING,     -- agrupa los pasos de una misma corrida de main.py (env AFP_RUN_ID o uuid)
  step        STRING,     -- cotizantes | core | sd_asset_class | consolidated_sd | chist_adjusted | bbg_returns | dim_bd_previa | ipd_strategy
  started_at  TIMESTAMP,
  finished_at TIMESTAMP,
  duration_s  FLOAT64,
  rc          INT64,      -- return code del paso (0 = OK)
  status      STRING,     -- OK / FAIL / SKIP
  rows        INT64,      -- filas escritas (si el paso lo reporta)
  extra       JSON,       -- detalle libre: ventana, comando, mensaje de error, etc.
  host        STRING,     -- hostname / revision del contenedor
  inserted_at TIMESTAMP
)
PARTITION BY DATE(started_at)
CLUSTER BY step
OPTIONS (description = 'Bitacora de ejecucion del pipeline afp-sync (un registro por paso y corrida).');
