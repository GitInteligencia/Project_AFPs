-- Vista afp_mart.v_sp_strategy_aum  (traducida 1:1 de sync/v_strategy_switch.sql, version vigente sobre v_consolidated_classified)
-- AUM por fondo de cada familia (Moneda + peers) y market share % dentro de la familia por periodo.
-- Traducciones: cc.fund_id::integer -> CAST(cc.fund_id AS INT64);  to_char -> FORMAT_DATE;
--   round(100::numeric * x / NULLIF(sum() OVER (...), 0::numeric), 2) -> ROUND(NUMERIC '100' * x / NULLIF(SUM() OVER (...), 0), 2)
--   bf.id::text = fc.id::text -> CAST(... AS STRING);  fa.fund_id = fc.id (INT64 = INT64).
CREATE OR REPLACE VIEW `${project}.${mart}.v_sp_strategy_aum` AS
WITH fund_aum AS (
  SELECT CAST(cc.fund_id AS INT64)          AS fund_id,
         FORMAT_DATE('%Y-%m', cc.fecha)     AS periodo,
         cc.fecha                           AS fecha_valor,
         SUM(cc.monto_usdmm)                AS monto_dolares
  FROM `${project}.${mart}.v_consolidated_classified` cc
  WHERE cc.fund_id IS NOT NULL
  GROUP BY cc.fund_id, cc.fecha
)
SELECT fc.family_id, fam.family_name, fam.family_short_name,
       fc.tipo, fc.fund_short_name, bf.fondo AS fondo_largo, bf.manager,
       fa.periodo, fa.fecha_valor, fa.monto_dolares,
       ROUND(NUMERIC '100' * fa.monto_dolares
             / NULLIF(SUM(fa.monto_dolares) OVER (PARTITION BY fc.family_id, fa.periodo), 0), 2) AS market_share_pct
FROM `${project}.${dim}.dim_bd_family_comp` fc
JOIN `${project}.${dim}.dim_bd_family` fam ON fam.family_id = fc.family_id
LEFT JOIN `${project}.${dim}.dim_bd_funds` bf ON CAST(bf.id AS STRING) = CAST(fc.id AS STRING)
LEFT JOIN fund_aum fa ON fa.fund_id = fc.id;
