// Fuente: BigQuery (antes Supabase/PostgREST)
import { MART, query, toDateStr, toNum } from './db';
import {
  ALT_AFPS,
  INFRA_STRATEGIES,
  LOCAL_KEYS,
  PD_STRATEGIES,
  PE_STRATEGIES,
  RA_KEYS,
  RE_STRATEGIES,
  pivotSeries,
  type AfpDetailSeries,
  type AfpOrSystem,
  type SeriesPoint,
} from './types-alternatives';
import { C1_CATEGORIES } from './dimensions';

type C2Row = {
  fecha: string;
  afp: string;
  region: 'Local' | 'Foreign';
  alt_strategy: string | null;
  total_usd_mm: number | null;
};

// v_afp_c2 unfiltered (SYSTEM view) is several thousand rows; BigQuery returns
// the whole result set in one call, so no pagination is needed. Ordering by
// the view's full GROUP BY key is kept for deterministic output.
async function fetchAllC2(afp: AfpOrSystem): Promise<C2Row[]> {
  const where = afp !== 'SYSTEM' ? 'WHERE afp = @afp' : '';
  const rows = await query<{
    fecha: unknown;
    afp: string;
    region: 'Local' | 'Foreign';
    alt_strategy: string | null;
    total_usd_mm: unknown;
  }>(
    `SELECT fecha, afp, region, alt_strategy, total_usd_mm
     FROM ${MART}.v_afp_c2
     ${where}
     ORDER BY fecha ASC, afp ASC, region ASC, category ASC, alt_fund_type ASC, alt_strategy ASC`,
    afp !== 'SYSTEM' ? { afp } : {},
  );
  return rows.map((r) => ({
    fecha: toDateStr(r.fecha),
    afp: r.afp,
    region: r.region,
    alt_strategy: r.alt_strategy ?? null,
    total_usd_mm: r.total_usd_mm == null ? null : toNum(r.total_usd_mm),
  }));
}

// Total Alternatives (NAV + Uncalled) by C1 category, full history.
export async function getTotalC1Evolution(): Promise<SeriesPoint[]> {
  const data = await query<{ fecha: unknown; c1: string; total_usd_mm: unknown }>(
    `SELECT fecha, c1, total_usd_mm FROM ${MART}.v_total_c1 ORDER BY fecha ASC`,
  );
  return pivotSeries(
    data.map((r) => ({
      fecha: toDateStr(r.fecha),
      key: r.c1 as string,
      value: toNum(r.total_usd_mm) || 0,
    })),
    C1_CATEGORIES,
  );
}

// NAV and Uncalled by AFP plus the system-level NAV-vs-Uncalled split.
export async function getNavUncalledEvolution(): Promise<{
  navByAfp: SeriesPoint[];
  uncalledByAfp: SeriesPoint[];
  navVsUncalled: SeriesPoint[];
}> {
  const [navData, uncData] = await Promise.all([
    query<{ fecha: unknown; afp: string; nav_usd_mm: unknown }>(
      `SELECT fecha, afp, nav_usd_mm FROM ${MART}.v_nav ORDER BY fecha ASC`,
    ),
    query<{ fecha: unknown; afp: string; uncalled_usd_mm: unknown }>(
      `SELECT fecha, afp, uncalled_usd_mm FROM ${MART}.v_uncalled ORDER BY fecha ASC`,
    ),
  ]);

  const navRows = navData.map((r) => ({
    fecha: toDateStr(r.fecha),
    key: r.afp as string,
    value: toNum(r.nav_usd_mm) || 0,
  }));
  const uncRows = uncData.map((r) => ({
    fecha: toDateStr(r.fecha),
    key: r.afp as string,
    value: toNum(r.uncalled_usd_mm) || 0,
  }));

  const sumByFecha = (rows: { fecha: string; value: number }[], key: string) =>
    rows.map((r) => ({ fecha: r.fecha, key, value: r.value }));

  return {
    navByAfp: pivotSeries(navRows, ALT_AFPS),
    uncalledByAfp: pivotSeries(uncRows, ALT_AFPS),
    navVsUncalled: pivotSeries(
      [...sumByFecha(navRows, 'NAV'), ...sumByFecha(uncRows, 'Uncalled')],
      ['NAV', 'Uncalled'],
    ),
  };
}

// The five evolution charts of one *_Detail PDF page (or SYSTEM = all AFPs).
// Buckets follow the legacy workbook: strategy + region define the bucket,
// Alt_Fund_Type is aggregated over, Infrastructure/Real Estate are roll-ups.
export async function getAfpDetail(afp: AfpOrSystem): Promise<AfpDetailSeries> {
  const c1Where = afp !== 'SYSTEM' ? 'WHERE afp = @afp' : '';
  const c1q = query<{ fecha: unknown; afp: string; c1: string; total_usd_mm: unknown }>(
    `SELECT fecha, afp, c1, total_usd_mm
     FROM ${MART}.v_afp_c1
     ${c1Where}
     ORDER BY fecha ASC`,
    afp !== 'SYSTEM' ? { afp } : {},
  );

  const [c1Rows, c2Rows] = await Promise.all([c1q, fetchAllC2(afp)]);

  const byC1 = pivotSeries(
    c1Rows.map((r) => ({
      fecha: toDateStr(r.fecha),
      key: r.c1 as string,
      value: toNum(r.total_usd_mm) || 0,
    })),
    C1_CATEGORIES,
  );

  const foreign = c2Rows.filter((r) => r.region === 'Foreign');
  const local = c2Rows.filter((r) => r.region === 'Local');
  const toRow = (r: C2Row, key: string) => ({
    fecha: r.fecha,
    key,
    value: Number(r.total_usd_mm) || 0,
  });

  const raKey = (s: string | null) =>
    (INFRA_STRATEGIES as readonly string[]).includes(s ?? '')
      ? 'Infrastructure'
      : (RE_STRATEGIES as readonly string[]).includes(s ?? '')
        ? 'Real Estate'
        : null;

  const localKey = (s: string | null): string => {
    if ((PE_STRATEGIES as readonly string[]).includes(s ?? ''))
      return 'Local Private Equity';
    if ((PD_STRATEGIES as readonly string[]).includes(s ?? ''))
      return 'Local Private Debt';
    if ((INFRA_STRATEGIES as readonly string[]).includes(s ?? ''))
      return 'Local Infrastructure';
    if (raKey(s) === 'Real Estate') return 'Local Real Estate';
    return 'Local Other Alternative';
  };

  return {
    byC1,
    foreignPE: pivotSeries(
      foreign.map((r) => toRow(r, r.alt_strategy ?? '')),
      PE_STRATEGIES,
    ),
    foreignPD: pivotSeries(
      foreign.map((r) => toRow(r, r.alt_strategy ?? '')),
      PD_STRATEGIES,
    ),
    foreignRA: pivotSeries(
      foreign
        .filter((r) => raKey(r.alt_strategy))
        .map((r) => toRow(r, raKey(r.alt_strategy)!)),
      RA_KEYS,
    ),
    local: pivotSeries(
      local.map((r) => toRow(r, localKey(r.alt_strategy))),
      LOCAL_KEYS,
    ),
  };
}
