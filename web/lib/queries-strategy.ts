// Fuente: BigQuery (antes Supabase/PostgREST)
import { DIM, MART, query, queryOne, toDateStr, toDateStrOrNull, toNum } from './db';

export type StrategyFamily = {
  family_id: number;
  family_name: string;
  family_short_name: string | null;
};

export type StrategyFundPoint = {
  fund_short_name: string;
  fondo_largo: string | null;
  manager: string | null;
  monto_usd_mm: number;
  market_share_pct: number;
};

export type StrategyTimePoint = {
  periodo: string;       // YYYY-MM
  fund_short_name: string;
  monto_usd_mm: number;
  market_share_pct: number;
};

export type StrategyDetail = {
  family: StrategyFamily;
  periodo: string;        // YYYY-MM (snapshot date)
  snapshot: StrategyFundPoint[]; // pie/table data, sorted by AUM desc
  timeSeries: StrategyTimePoint[]; // all periodos × funds for line charts
  totalUsdMm: number;
};

// 1.4 — per-AFP positioning in our (Moneda) funds for a family, with over/underweight
// vs the system average. Lagged world (CHIST), separate from the fresh strategy AUM.
export type StrategyAfpOwUwRow = {
  afp: string;
  our_usd_mm: number;
  afp_aum_usd_mm: number;
  weight: number; // fraction of the AFP's book in this family's Moneda funds
  sys_avg: number; // system-wide weight (same across rows of a family/fecha)
  ow_uw: number; // weight - sys_avg (fraction; ×100 = percentage points)
};

export async function getStrategyAfpOwUw(
  family_id: number,
): Promise<{ fecha: string; rows: StrategyAfpOwUwRow[] } | null> {
  // Latest CHIST report date available for this family.
  const latest = await queryOne<{ fecha_reporte: unknown }>(
    `SELECT fecha_reporte FROM ${MART}.mv_strategy_afp_ow_uw
     WHERE family_id = @family_id
     ORDER BY fecha_reporte DESC
     LIMIT 1`,
    { family_id },
  );
  const fecha = toDateStrOrNull(latest?.fecha_reporte) ?? undefined;
  if (!fecha) return null;

  const data = await query<{
    afp: string;
    our_usd_mm: unknown;
    afp_aum_usd_mm: unknown;
    weight: unknown;
    sys_avg: unknown;
    ow_uw: unknown;
  }>(
    `SELECT afp, our_usd_mm, afp_aum_usd_mm, weight, sys_avg, ow_uw
     FROM ${MART}.mv_strategy_afp_ow_uw
     WHERE family_id = @family_id AND fecha_reporte = DATE(@fecha)`,
    { family_id, fecha },
  );

  const rows = data
    .map((r) => ({
      afp: r.afp as string,
      our_usd_mm: toNum(r.our_usd_mm) || 0,
      afp_aum_usd_mm: toNum(r.afp_aum_usd_mm) || 0,
      weight: toNum(r.weight) || 0,
      sys_avg: toNum(r.sys_avg) || 0,
      ow_uw: toNum(r.ow_uw) || 0,
    }))
    .sort((a, b) => b.weight - a.weight);
  return { fecha, rows };
}

export async function getStrategyFamilies(): Promise<StrategyFamily[]> {
  // Pull from dim_bd_family directly (some families like 11 Local Equity DI/IF
  // have no comps and therefore don't appear in v_sp_strategy_aum).
  const data = await query<{
    family_id: unknown;
    family_name: string;
    family_short_name: string | null;
  }>(
    `SELECT family_id, family_name, family_short_name
     FROM ${DIM}.dim_bd_family
     ORDER BY family_id ASC`,
  );
  return data.map((r) => ({
    family_id: toNum(r.family_id),
    family_name: r.family_name as string,
    family_short_name: (r.family_short_name as string | null) ?? null,
  }));
}

export type LocalEquityPoint = {
  fecha_reporte: string;
  direct_clp_bn: number;
  // funds_clp_bn renders the new taxonomy by default (nt_asset_class='Equity'
  // AND nt_region='Chile'); funds_clp_bn_legacy keeps the old dim_bd_funds
  // membership. For the Chilean-equity-fund universe both coincide today.
  funds_clp_bn: number;
  funds_clp_bn_legacy: number;
  total_clp_bn: number;
  source: 'CHIST' | 'SP_XML';
};

export async function getLocalEquityDates(): Promise<string[]> {
  const data = await query<{ fecha_reporte: unknown }>(
    `SELECT fecha_reporte FROM ${MART}.v_local_equity_di_vs_if_combined
     ORDER BY fecha_reporte DESC
     LIMIT 2000`,
  );
  return Array.from(new Set(data.map((r) => toDateStr(r.fecha_reporte))));
}

export async function getLocalEquityHistory(): Promise<LocalEquityPoint[]> {
  const data = await query<{
    fecha_reporte: unknown;
    direct_clp_bn: unknown;
    funds_clp_bn: unknown;
    funds_clp_bn_nt: unknown;
    total_clp_bn: unknown;
    total_clp_bn_nt: unknown;
    source: string | null;
  }>(
    `SELECT fecha_reporte, direct_clp_bn, funds_clp_bn, funds_clp_bn_nt,
            total_clp_bn, total_clp_bn_nt, source
     FROM ${MART}.v_local_equity_di_vs_if_combined
     ORDER BY fecha_reporte ASC`,
  );
  return data.map((r) => ({
    fecha_reporte: toDateStr(r.fecha_reporte),
    direct_clp_bn: toNum(r.direct_clp_bn) || 0,
    funds_clp_bn: toNum(r.funds_clp_bn_nt) || 0,
    funds_clp_bn_legacy: toNum(r.funds_clp_bn) || 0,
    total_clp_bn: toNum(r.total_clp_bn_nt) || 0,
    source: (r.source as 'CHIST' | 'SP_XML') ?? 'CHIST',
  }));
}

export async function getStrategyDates(family_id: number): Promise<string[]> {
  const data = await query<{ periodo: string }>(
    `SELECT periodo FROM ${MART}.v_sp_strategy_aum
     WHERE family_id = @family_id
       AND monto_dolares IS NOT NULL
       AND periodo >= @periodo_min
     ORDER BY periodo DESC`,
    { family_id, periodo_min: '2025-01' },
  );
  return Array.from(new Set(data.map((r) => r.periodo as string)));
}

/**
 * @param rollupAfter If set, only the top-N funds (by AUM at `periodo`) are
 *  kept individually; everything else is collapsed into a single "Other" entry
 *  for both snapshot and time series. Matches the PDF page 9 "Top 10 HY"
 *  presentation.
 */
export async function getStrategyDetail(
  family_id: number,
  periodo: string,
  rollupAfter?: number,
): Promise<StrategyDetail | null> {
  // v_sp_strategy_aum carries full history (~169 periodos) × every fund; we
  // need the full set anyway for the time series. BigQuery returns it in one
  // call (no 1000-row page cap to work around).
  const data = await query<Record<string, unknown>>(
    `SELECT family_id, family_name, family_short_name, fund_short_name, fondo_largo,
            manager, periodo, monto_dolares, market_share_pct
     FROM ${MART}.v_sp_strategy_aum
     WHERE family_id = @family_id
     ORDER BY periodo ASC`,
    { family_id },
  );
  if (data.length === 0) return null;

  const family: StrategyFamily = {
    family_id,
    family_name: data[0].family_name as string,
    family_short_name: (data[0].family_short_name as string | null) ?? null,
  };

  // Snapshot rows for the requested periodo (sorted by AUM desc).
  const snapshot: StrategyFundPoint[] = data
    .filter((r) => r.periodo === periodo && r.monto_dolares != null)
    .map((r) => ({
      fund_short_name: r.fund_short_name as string,
      fondo_largo: (r.fondo_largo as string | null) ?? null,
      manager: (r.manager as string | null) ?? null,
      monto_usd_mm: toNum(r.monto_dolares) || 0,
      market_share_pct: toNum(r.market_share_pct) || 0,
    }))
    .sort((a, b) => b.monto_usd_mm - a.monto_usd_mm);

  // Time series rows (all periodos with data for this family).
  const timeSeries: StrategyTimePoint[] = data
    .filter((r) => r.monto_dolares != null)
    .map((r) => ({
      periodo: r.periodo as string,
      fund_short_name: r.fund_short_name as string,
      monto_usd_mm: toNum(r.monto_dolares) || 0,
      market_share_pct: toNum(r.market_share_pct) || 0,
    }))
    .sort((a, b) => a.periodo.localeCompare(b.periodo));

  const totalUsdMm = snapshot.reduce((s, p) => s + p.monto_usd_mm, 0);

  // Optional top-N + Other rollup. Determines top funds from the snapshot;
  // funds not in top-N collapse to a single "Other" series across all periods.
  if (rollupAfter && snapshot.length > rollupAfter) {
    const topFunds = new Set(
      snapshot.slice(0, rollupAfter).map((p) => p.fund_short_name),
    );
    const otherSnapshot = snapshot.filter((p) => !topFunds.has(p.fund_short_name));
    const otherUsd = otherSnapshot.reduce((s, p) => s + p.monto_usd_mm, 0);
    const otherPct = otherSnapshot.reduce((s, p) => s + p.market_share_pct, 0);
    const newSnapshot: StrategyFundPoint[] = [
      ...snapshot.slice(0, rollupAfter),
      {
        fund_short_name: 'Other',
        fondo_largo: `Other (${otherSnapshot.length} funds combined)`,
        manager: null,
        monto_usd_mm: otherUsd,
        market_share_pct: otherPct,
      },
    ];
    // Time series: keep top funds individually, sum the rest into "Other" per periodo.
    const tsByPeriodo = new Map<string, { top: StrategyTimePoint[]; other: { usd: number; pct: number } }>();
    for (const r of timeSeries) {
      let bucket = tsByPeriodo.get(r.periodo);
      if (!bucket) {
        bucket = { top: [], other: { usd: 0, pct: 0 } };
        tsByPeriodo.set(r.periodo, bucket);
      }
      if (topFunds.has(r.fund_short_name)) {
        bucket.top.push(r);
      } else {
        bucket.other.usd += r.monto_usd_mm;
        bucket.other.pct += r.market_share_pct;
      }
    }
    const newTimeSeries: StrategyTimePoint[] = [];
    for (const [periodoKey, bucket] of tsByPeriodo) {
      newTimeSeries.push(...bucket.top);
      if (bucket.other.usd > 0 || bucket.other.pct > 0) {
        newTimeSeries.push({
          periodo: periodoKey,
          fund_short_name: 'Other',
          monto_usd_mm: bucket.other.usd,
          market_share_pct: bucket.other.pct,
        });
      }
    }
    newTimeSeries.sort((a, b) => a.periodo.localeCompare(b.periodo));
    return {
      family,
      periodo,
      snapshot: newSnapshot,
      timeSeries: newTimeSeries,
      totalUsdMm,
    };
  }

  return { family, periodo, snapshot, timeSeries, totalUsdMm };
}
