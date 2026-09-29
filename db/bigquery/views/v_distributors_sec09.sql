-- Vista afp_mart.v_distributors_sec09  (traducida 1:1 de sync/v_distributors_swap_and_orphan_drops.sql = version APLICADA)
-- NOTA: sync/v_distributors_to_sql_source.sql contiene otra version (distribuidor desde dim_bd_funds.distributor) marcada
-- "PREPARADO, NO APLICADO"; NO se traduce. La vigente resuelve distribuidor = dim_foreign_classification_overlay.family.
-- Traducciones: bool_or() -> LOGICAL_OR();  o.family IS NOT NULL AS is_mapped se mantiene;  ::text eliminados.
CREATE OR REPLACE VIEW `${project}.${mart}.v_distributors_sec09` AS
WITH base AS (
  SELECT s.fecha_reporte, s.isin, s.fund_id, s.fondo AS fondo_bd, s.manager AS manager_bd,
         s.monto_dolares AS monto_usd_mm
  FROM `${project}.${mart}.v_consolidated_foreign_classified` s
  WHERE s.monto_dolares > 0 AND s.isin IS NOT NULL
),
resolved AS (
  SELECT b.fecha_reporte, b.isin,
    COALESCE(o.family, 'Unmapped') AS distributor,
    COALESCE(o.manager, CAST(b.manager_bd AS STRING), '(no manager)') AS manager,
    o.family IS NOT NULL AS is_mapped,
    b.monto_usd_mm
  FROM base b
  LEFT JOIN `${project}.${dim}.dim_foreign_classification_overlay` o ON o.identificador = b.isin
)
SELECT fecha_reporte, distributor, manager,
       LOGICAL_OR(is_mapped) AS is_mapped, SUM(monto_usd_mm) AS monto_usd_mm
FROM resolved GROUP BY fecha_reporte, distributor, manager;
