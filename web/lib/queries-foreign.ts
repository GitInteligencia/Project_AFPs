// Fuente: BigQuery (antes Supabase/PostgREST)
import { MART, query, toDateStr, toNum } from './db';
import type {
  ForeignSource,
  ForeignSplit,
  ForeignSummaryRow,
  ForeignTaxonomy,
} from './types-foreign';

/**
 * Distinct fecha_reporte in v_foreign_pdf_summary_combined (latest first),
 * paired with the source that owns each fecha (CHIST or SP_XML).
 */
export async function getForeignDates(): Promise<
  { fecha: string; source: ForeignSource }[]
> {
  const data = await query<{ fecha_reporte: unknown; source: string | null }>(
    `SELECT fecha_reporte, source
     FROM ${MART}.v_foreign_pdf_summary_combined
     WHERE fecha_reporte >= DATE '2025-01-01'
     ORDER BY fecha_reporte DESC
     -- ~45-53 rows per fecha; 80 months ≈ 4,000 rows. 5,000 leaves headroom.
     LIMIT 5000`,
  );
  const seen = new Set<string>();
  const out: { fecha: string; source: ForeignSource }[] = [];
  for (const r of data) {
    const fecha = toDateStr(r.fecha_reporte);
    if (seen.has(fecha)) continue;
    seen.add(fecha);
    out.push({ fecha, source: (r.source as ForeignSource) ?? 'CHIST' });
  }
  return out;
}

/**
 * Aggregated foreign breakdown for a single fecha_reporte.
 */
export async function getForeignSummary(
  fecha: string,
  taxonomy: ForeignTaxonomy = 'nt',
): Promise<ForeignSummaryRow[]> {
  const nt = taxonomy === 'nt';
  const data = await query<{
    fecha_reporte: unknown;
    pdf_bucket: string;
    pdf_em_dm: string | null;
    pdf_subregion: string | null;
    pdf_fi_category: string | null;
    pdf_bucket_nt: string | null;
    pdf_em_dm_nt: string | null;
    pdf_subregion_nt: string | null;
    pdf_fi_category_nt: string | null;
    monto_usd_mm: unknown;
    source: string | null;
  }>(
    `SELECT fecha_reporte, pdf_bucket, pdf_em_dm, pdf_subregion, pdf_fi_category,
            pdf_bucket_nt, pdf_em_dm_nt, pdf_subregion_nt, pdf_fi_category_nt,
            monto_usd_mm, source
     FROM ${MART}.v_foreign_pdf_summary_combined
     WHERE fecha_reporte = DATE(@fecha)`,
    { fecha },
  );
  return data.map((r) => ({
    fecha_reporte: toDateStr(r.fecha_reporte),
    pdf_bucket: (nt ? r.pdf_bucket_nt : r.pdf_bucket) as string,
    pdf_em_dm: ((nt ? r.pdf_em_dm_nt : r.pdf_em_dm) as string | null) ?? null,
    pdf_subregion:
      ((nt ? r.pdf_subregion_nt : r.pdf_subregion) as string | null) ?? null,
    pdf_fi_category:
      ((nt ? r.pdf_fi_category_nt : r.pdf_fi_category) as string | null) ?? null,
    monto_usd_mm: toNum(r.monto_usd_mm) || 0,
    source: (r.source as ForeignSource) ?? 'CHIST',
  }));
}

/**
 * Returns the four baseline fechas used by the Changes view, matching the SP
 * convention (month-end = last day of month). Computed via UTC Date math:
 * `new Date(Date.UTC(y, monthIndex, 0))` gives the last day of `monthIndex - 1`.
 *
 * For 2026-03-31:
 *   { mom: '2026-02-28', ytd: '2025-12-31', ltm: '2025-03-31', threeY: '2023-03-31' }
 */
function priorBaselines(fecha: string): {
  mom: string;
  threeM: string;
  sixM: string;
  ytd: string;
  ltm: string;
  threeY: string;
} {
  const [y, m] = fecha.split('-').map(Number);
  const lastDayOfMonth = (year: number, month1Indexed: number) =>
    new Date(Date.UTC(year, month1Indexed, 0)).toISOString().slice(0, 10);
  return {
    mom: lastDayOfMonth(y, m - 1),    // last day of prior month
    threeM: lastDayOfMonth(y, m - 3), // same month-end, 3m back
    sixM: lastDayOfMonth(y, m - 6),   // same month-end, 6m back
    ytd: `${y - 1}-12-31`,            // Dec of prior calendar year
    ltm: lastDayOfMonth(y - 1, m),    // same month-end, 12m back
    threeY: lastDayOfMonth(y - 3, m), // same month-end, 36m back
  };
}

/**
 * Pull start (MoM, YTD, LTM, 3Y) and end (current) foreign breakdowns in a
 * single round-trip. Caller is responsible for checking which baselines actually
 * exist in the dataset (compare against getForeignDates) — this just returns
 * empty arrays for baselines we don't have data for, which would otherwise
 * collapse to "all positive change" silently.
 */
export async function getForeignChanges(
  fecha: string,
  taxonomy: ForeignTaxonomy = 'nt',
): Promise<{
  fechaEnd: string;
  fechaMomStart: string;
  fechaThreeMStart: string;
  fechaSixMStart: string;
  fechaYtdStart: string;
  fechaLtmStart: string;
  fechaThreeYStart: string;
  endRows: ForeignSummaryRow[];
  momStartRows: ForeignSummaryRow[];
  threeMStartRows: ForeignSummaryRow[];
  sixMStartRows: ForeignSummaryRow[];
  ytdStartRows: ForeignSummaryRow[];
  ltmStartRows: ForeignSummaryRow[];
  threeYStartRows: ForeignSummaryRow[];
}> {
  const { mom, threeM, sixM, ytd, ltm, threeY } = priorBaselines(fecha);
  const [
    endRows,
    momStartRows,
    threeMStartRows,
    sixMStartRows,
    ytdStartRows,
    ltmStartRows,
    threeYStartRows,
  ] = await Promise.all([
    getForeignSummary(fecha, taxonomy),
    getForeignSummary(mom, taxonomy),
    getForeignSummary(threeM, taxonomy),
    getForeignSummary(sixM, taxonomy),
    getForeignSummary(ytd, taxonomy),
    getForeignSummary(ltm, taxonomy),
    getForeignSummary(threeY, taxonomy),
  ]);
  return {
    fechaEnd: fecha,
    fechaMomStart: mom,
    fechaThreeMStart: threeM,
    fechaSixMStart: sixM,
    fechaYtdStart: ytd,
    fechaLtmStart: ltm,
    fechaThreeYStart: threeY,
    endRows,
    momStartRows,
    threeMStartRows,
    sixMStartRows,
    ytdStartRows,
    ltmStartRows,
    threeYStartRows,
  };
}

// ============================================================================
// Return / Flow split (PDF Sec 07 pages 4-5)
// ============================================================================
//
// v_foreign_returns_flows_summary replicates the legacy Excel methodology per
// instrument and month: return = prior-month position × Bloomberg monthly USD
// total return; flow = position change − return. Scope is Equity / Fixed
// Income / Private Equity (Direct Investment excluded, as in the PDF). Window
// aggregates are sums of the monthly splits, so a window is only fully split
// when every month inside it has returns data; each window's covered/missing
// months are computed dynamically from the Bloomberg returns series.

export type ForeignChangesSplits = {
  mom: ForeignSplit;
  threeM: ForeignSplit;
  sixM: ForeignSplit;
  ytd: ForeignSplit;
  ltm: ForeignSplit;
  threeY: ForeignSplit;
};

type SplitRaw = {
  fecha_reporte: string;
  pdf_bucket: string;
  pdf_em_dm: string | null;
  pdf_subregion: string | null;
  pdf_fi_category: string | null;
  pdf_bucket_nt: string | null;
  pdf_em_dm_nt: string | null;
  pdf_subregion_nt: string | null;
  pdf_fi_category_nt: string | null;
  return_usd_mm: number;
  flow_usd_mm: number;
};

/** Month-end fechas strictly after `startExcl` and up to `endIncl`. */
function monthEndsBetween(startExcl: string, endIncl: string): string[] {
  const out: string[] = [];
  let [y, m] = startExcl.split('-').map(Number);
  for (let i = 0; i < 120; i++) {
    m += 1;
    if (m > 12) {
      m = 1;
      y += 1;
    }
    const monthEnd = new Date(Date.UTC(y, m, 0)).toISOString().slice(0, 10);
    if (monthEnd > endIncl) break;
    out.push(monthEnd);
  }
  return out;
}

function buildSplit(
  raw: SplitRaw[],
  startExcl: string,
  endIncl: string,
  taxonomy: ForeignTaxonomy,
): ForeignSplit {
  const nt = taxonomy === 'nt';
  const inWindow = raw.filter(
    (r) => r.fecha_reporte > startExcl && r.fecha_reporte <= endIncl,
  );
  const covered = [...new Set(inWindow.map((r) => r.fecha_reporte))].sort();
  const coveredSet = new Set(covered);
  const missing = monthEndsBetween(startExcl, endIncl).filter(
    (f) => !coveredSet.has(f),
  );
  const toSummary = (r: SplitRaw, usd: number): ForeignSummaryRow => ({
    fecha_reporte: r.fecha_reporte,
    pdf_bucket: (nt ? r.pdf_bucket_nt : r.pdf_bucket) ?? r.pdf_bucket,
    pdf_em_dm: (nt ? r.pdf_em_dm_nt : r.pdf_em_dm) ?? null,
    pdf_subregion: (nt ? r.pdf_subregion_nt : r.pdf_subregion) ?? null,
    pdf_fi_category: (nt ? r.pdf_fi_category_nt : r.pdf_fi_category) ?? null,
    monto_usd_mm: usd,
    source: 'SP_XML',
  });
  return {
    covered,
    missing,
    returnRows: inWindow.map((r) => toSummary(r, r.return_usd_mm)),
    flowRows: inWindow.map((r) => toSummary(r, r.flow_usd_mm)),
  };
}

/**
 * Return/Flow splits for the four Changes windows ending at `fecha`. One
 * fetch covering the widest window (3Y), sliced per window. Windows
 * whose months predate the returns series come back with empty `covered` —
 * the UI shows the un-split total there.
 */
export async function getForeignChangesSplits(
  fecha: string,
  taxonomy: ForeignTaxonomy = 'nt',
): Promise<ForeignChangesSplits> {
  const { mom, threeM, sixM, ytd, ltm, threeY } = priorBaselines(fecha);
  const data = await query<{
    fecha_reporte: unknown;
    pdf_bucket: string;
    pdf_em_dm: string | null;
    pdf_subregion: string | null;
    pdf_fi_category: string | null;
    pdf_bucket_nt: string | null;
    pdf_em_dm_nt: string | null;
    pdf_subregion_nt: string | null;
    pdf_fi_category_nt: string | null;
    return_usd_mm: unknown;
    flow_usd_mm: unknown;
  }>(
    `SELECT fecha_reporte, pdf_bucket, pdf_em_dm, pdf_subregion, pdf_fi_category,
            pdf_bucket_nt, pdf_em_dm_nt, pdf_subregion_nt, pdf_fi_category_nt,
            return_usd_mm, flow_usd_mm
     FROM ${MART}.v_foreign_returns_flows_summary
     WHERE fecha_reporte > DATE(@start_excl) AND fecha_reporte <= DATE(@end_incl)`,
    { start_excl: threeY, end_incl: fecha },
  );
  const raw: SplitRaw[] = data.map((r) => ({
    fecha_reporte: toDateStr(r.fecha_reporte),
    pdf_bucket: r.pdf_bucket as string,
    pdf_em_dm: (r.pdf_em_dm as string | null) ?? null,
    pdf_subregion: (r.pdf_subregion as string | null) ?? null,
    pdf_fi_category: (r.pdf_fi_category as string | null) ?? null,
    pdf_bucket_nt: (r.pdf_bucket_nt as string | null) ?? null,
    pdf_em_dm_nt: (r.pdf_em_dm_nt as string | null) ?? null,
    pdf_subregion_nt: (r.pdf_subregion_nt as string | null) ?? null,
    pdf_fi_category_nt: (r.pdf_fi_category_nt as string | null) ?? null,
    return_usd_mm: toNum(r.return_usd_mm) || 0,
    flow_usd_mm: toNum(r.flow_usd_mm) || 0,
  }));
  return {
    mom: buildSplit(raw, mom, fecha, taxonomy),
    threeM: buildSplit(raw, threeM, fecha, taxonomy),
    sixM: buildSplit(raw, sixM, fecha, taxonomy),
    ytd: buildSplit(raw, ytd, fecha, taxonomy),
    ltm: buildSplit(raw, ltm, fecha, taxonomy),
    threeY: buildSplit(raw, threeY, fecha, taxonomy),
  };
}

/**
 * Per-fund total USD MM as of one fecha. Used by Top Net Flows (sec 08).
 */
export type ForeignFundRow = {
  fund_id: string;
  fondo: string;
  manager: string | null;
  monto_usd_mm: number;
};

export type FundDeltaRow = {
  fund_id: string;
  fondo: string;
  manager: string | null;
  delta_usd_mm: number;
};

// PDF Sec 08 methodology — flow = Δposition − return per ISIN per month (the
// same Bloomberg-returns split behind the Sec 07 Changes pages), aggregated to
// fund level by v_foreign_fund_flows (share classes consolidated via the
// dim_homol_funds → dim_bd_funds chain). Validated vs the Mar-26 PDF: top-10
// outflows match to the decimal; inflows additionally surface funds the PDF
// omits (its flows matrix truncates at row 2000 of Output_25sd).
function topSplit(
  deltas: FundDeltaRow[],
  topN: number,
): { inflows: FundDeltaRow[]; outflows: FundDeltaRow[] } {
  const sorted = [...deltas].sort((a, b) => b.delta_usd_mm - a.delta_usd_mm);
  return {
    inflows: sorted.filter((d) => d.delta_usd_mm > 0).slice(0, topN),
    outflows: sorted.filter((d) => d.delta_usd_mm < 0).slice(-topN).reverse(),
  };
}

/**
 * Top N inflows and outflows per fund for the MoM and YTD windows ending at
 * `fecha` (PDF Sec 08). Monthly = the fund flows of `fecha`; YTD = sum of
 * monthly fund flows in the calendar year up to `fecha`. Returns empty
 * buckets when no months in the window have Bloomberg returns (e.g. the
 * latest fecha before its returns arrive, or fechas before the Bloomberg
 * returns series begins).
 */
export async function getForeignTopFlows(
  fecha: string,
  topN = 10,
): Promise<{
  fechaEnd: string;
  fechaMomStart: string;
  fechaYtdStart: string;
  mom: { inflows: FundDeltaRow[]; outflows: FundDeltaRow[] };
  ytd: { inflows: FundDeltaRow[]; outflows: FundDeltaRow[] };
}> {
  const { mom, ytd } = priorBaselines(fecha);
  // One fetch over the YTD window (it contains the MoM month).
  type Row = {
    fecha_reporte: string;
    fund_id: string;
    fondo: string;
    manager: string | null;
    flow_usd_mm: number;
  };
  const data = await query<{
    fecha_reporte: unknown;
    fund_id: unknown;
    fondo: string;
    manager: string | null;
    flow_usd_mm: unknown;
  }>(
    `SELECT fecha_reporte, fund_id, fondo, manager, flow_usd_mm
     FROM ${MART}.v_foreign_fund_flows
     WHERE fecha_reporte > DATE(@start_excl) AND fecha_reporte <= DATE(@end_incl)`,
    { start_excl: ytd, end_incl: fecha },
  );
  const rows: Row[] = data.map((r) => ({
    fecha_reporte: toDateStr(r.fecha_reporte),
    fund_id: String(r.fund_id),
    fondo: r.fondo as string,
    manager: (r.manager as string | null) ?? null,
    flow_usd_mm: toNum(r.flow_usd_mm) || 0,
  }));

  const momDeltas: FundDeltaRow[] = rows
    .filter((r) => r.fecha_reporte === fecha)
    .map((r) => ({
      fund_id: r.fund_id,
      fondo: r.fondo,
      manager: r.manager,
      delta_usd_mm: r.flow_usd_mm,
    }));

  const ytdByFund = new Map<string, FundDeltaRow>();
  for (const r of rows) {
    const cur = ytdByFund.get(r.fund_id);
    if (cur) cur.delta_usd_mm += r.flow_usd_mm;
    else
      ytdByFund.set(r.fund_id, {
        fund_id: r.fund_id,
        fondo: r.fondo,
        manager: r.manager,
        delta_usd_mm: r.flow_usd_mm,
      });
  }

  return {
    fechaEnd: fecha,
    fechaMomStart: mom,
    fechaYtdStart: ytd,
    mom: topSplit(momDeltas, topN),
    ytd: topSplit([...ytdByFund.values()], topN),
  };
}

/**
 * Per (manager, asset_class, em_dm/region/category, fund_style) row at one fecha.
 * Used by Sec 10 (Managers).
 */
export type ManagerRow = {
  manager: string;
  fund_style: 'Active' | 'Passive';
  asset_class: string | null;
  category: string | null;
  region: string | null;
  // New taxonomy (BD_Funds.xlsx) — carried through the same view chain as the
  // legacy asset_class/category/region. Null for funds the new file doesn't classify.
  nt_asset_class: string | null;
  nt_sub_asset_class: string | null;
  nt_category: string | null;
  nt_sub_category: string | null;
  nt_region: string | null;
  monto_usd_mm: number;
};

// Manager-name aliases applied at read time so the dashboard groups sub-brands
// the same way the PDF does. dim_bd_funds keeps the underlying brand intact;
// only the aggregated view re-labels them.
const MANAGER_ALIASES: Record<string, string> = {
  'x-trackers': 'Deutsche',     // DWS ETF brand; PDF Sec 10 reports under Deutsche.
};

export async function getForeignManagers(fecha: string): Promise<ManagerRow[]> {
  const data = await query<{
    manager: string | null;
    fund_style: string | null;
    asset_class: string | null;
    category: string | null;
    region: string | null;
    nt_asset_class: string | null;
    nt_sub_asset_class: string | null;
    nt_category: string | null;
    nt_sub_category: string | null;
    nt_region: string | null;
    monto_usd_mm: unknown;
  }>(
    `SELECT manager, fund_style, asset_class, category, region,
            nt_asset_class, nt_sub_asset_class, nt_category, nt_sub_category, nt_region,
            monto_usd_mm
     FROM ${MART}.v_foreign_managers_combined
     WHERE fecha_reporte = DATE(@fecha)`,
    { fecha },
  );
  return data.map((r) => {
    const rawManager = (r.manager as string) ?? 'Unknown';
    return {
      manager: MANAGER_ALIASES[rawManager] ?? rawManager,
      fund_style: (r.fund_style as 'Active' | 'Passive') ?? 'Active',
      asset_class: (r.asset_class as string | null) ?? null,
      category: (r.category as string | null) ?? null,
      region: (r.region as string | null) ?? null,
      nt_asset_class: (r.nt_asset_class as string | null) ?? null,
      nt_sub_asset_class: (r.nt_sub_asset_class as string | null) ?? null,
      nt_category: (r.nt_category as string | null) ?? null,
      nt_sub_category: (r.nt_sub_category as string | null) ?? null,
      nt_region: (r.nt_region as string | null) ?? null,
      monto_usd_mm: toNum(r.monto_usd_mm) || 0,
    };
  });
}

// ============================================================================
// Foreign Investment evolution (Total Foreign + buckets) over all fechas
// ============================================================================

export type ForeignEvolutionPoint = {
  fecha_reporte: string;
  equity: number;
  fixed_income: number;
  private_equity: number;
  direct_investment: number;
  other: number;
  total: number;
};

/**
 * One row per fecha with USD MM aggregated by bucket. Uses the combined
 * CHIST + SP XML view, so it spans CHIST historical + SP XML recent fechas.
 */
export async function getForeignEvolution(): Promise<ForeignEvolutionPoint[]> {
  const data = await query<{
    fecha_reporte: unknown;
    pdf_bucket: string;
    monto_usd_mm: unknown;
  }>(
    `SELECT fecha_reporte, pdf_bucket, monto_usd_mm
     FROM ${MART}.v_foreign_pdf_summary_combined
     ORDER BY fecha_reporte ASC
     LIMIT 20000`,
  );
  const byFecha = new Map<string, ForeignEvolutionPoint>();
  for (const r of data) {
    const fecha = toDateStr(r.fecha_reporte);
    const bucket = r.pdf_bucket as string;
    const usd = toNum(r.monto_usd_mm) || 0;
    let p = byFecha.get(fecha);
    if (!p) {
      p = {
        fecha_reporte: fecha,
        equity: 0,
        fixed_income: 0,
        private_equity: 0,
        direct_investment: 0,
        other: 0,
        total: 0,
      };
      byFecha.set(fecha, p);
    }
    if (bucket === 'Equity') p.equity += usd;
    else if (bucket === 'Fixed Income') p.fixed_income += usd;
    else if (bucket === 'Private Equity') p.private_equity += usd;
    else if (bucket === 'Direct Investment') p.direct_investment += usd;
    else p.other += usd;
    p.total += usd;
  }
  return Array.from(byFecha.values()).sort((a, b) =>
    a.fecha_reporte.localeCompare(b.fecha_reporte),
  );
}

export type { ForeignSummaryRow } from './types-foreign';
export {
  buildPdfTree,
  TOP_BUCKET_ORDER,
  FI_SUBREGION_ORDER,
  EQUITY_SUBREGION_ORDER,
  FI_CATEGORY_ORDER,
} from './types-foreign';
