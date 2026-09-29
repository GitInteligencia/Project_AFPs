-- Vista afp_mart.v_contributors_market_share  (traducida 1:1 de sync/sp_cotizantes_schema.sql)
-- Market share por AUM y por # cotizantes por AFP y fecha de reporte. Usa el ultimo snapshot de cotizantes
-- publicado ANTES del mes del reporte (convencion del PDF).
-- !! DEPENDE de ${mart}.v_returns_afp_tipo, SIN DDL en el repo (ver _PENDIENTES_DUMP.md): no se puede crear hasta tenerla.
-- Traducciones:
--   LEFT JOIN LATERAL (SELECT ... WHERE ca.afp = a.afp AND ca.fecha < date_trunc('month', a.fecha) ORDER BY ca.fecha DESC LIMIT 1) c ON true
--     -> LEFT JOIN cotizantes_afp ca ON (afp igual AND ca.fecha < DATE_TRUNC(a.fecha, MONTH))
--        QUALIFY ROW_NUMBER() OVER (PARTITION BY a.fecha, a.afp ORDER BY ca.fecha DESC) = 1
--     (la fila sin match se conserva con ca.* NULL, igual que el LATERAL ON true).
--   n_cotizantes::numeric -> CAST(n_cotizantes AS NUMERIC);  aum_usd_mm * 1000.0 -> * 1000 (literal entero, no degrada tipo).
CREATE OR REPLACE VIEW `${project}.${mart}.v_contributors_market_share` AS
WITH aum_by_afp AS (
    SELECT fecha, afp, SUM(aum_usd_mm) AS aum_usd_mm
    FROM `${project}.${mart}.v_returns_afp_tipo`
    WHERE afp <> 'TOTAL'
    GROUP BY fecha, afp
),
joined AS (
    SELECT
        a.fecha AS fecha_reporte,
        a.afp,
        a.aum_usd_mm,
        ca.fecha AS fecha_cotizantes,
        ca.n_cotizantes
    FROM aum_by_afp a
    LEFT JOIN `${project}.${raw}.cotizantes_afp` ca
      ON ca.afp = a.afp
     AND ca.fecha < DATE_TRUNC(a.fecha, MONTH)
    QUALIFY ROW_NUMBER() OVER (PARTITION BY a.fecha, a.afp ORDER BY ca.fecha DESC) = 1
)
SELECT
    fecha_reporte,
    fecha_cotizantes,
    afp,
    aum_usd_mm,
    n_cotizantes,
    -- "AVG (USD M)" en el PDF = AUM_USD / # cotizantes, en miles de USD por cotizante
    CASE WHEN n_cotizantes > 0
        THEN aum_usd_mm * 1000 / n_cotizantes
    END AS avg_usd_per_cotiz,
    -- shares a nivel sistema (excluye filas sin cotizantes para cuadrar 100%)
    aum_usd_mm / NULLIF(SUM(aum_usd_mm) OVER (PARTITION BY fecha_reporte), 0)
        AS share_aum,
    CAST(n_cotizantes AS NUMERIC)
        / NULLIF(SUM(n_cotizantes) OVER (PARTITION BY fecha_reporte), 0)
        AS share_cotiz
FROM joined;
