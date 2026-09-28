// Fuente: BigQuery (antes Supabase/PostgREST)
import { MART, RAW, query, toDateStr, toNum } from './db';

export type ChileanStockIssuerRow = {
  emisor: string;
  monto_usd_mm: number;
};

export type ChileanFlowsBucket = {
  purchases: ChileanStockIssuerRow[];
  sales: ChileanStockIssuerRow[];
  totalNet: number;
};

export type ChileanStocksTopFlows = {
  fechaEnd: string;
  fechaMtdStart: string;
  fechaYtdStart: string;
  fechaLtmStart: string;
  mtd: ChileanFlowsBucket;
  ytd: ChileanFlowsBucket;
  ltm: ChileanFlowsBucket;
};

// PDF 06 methodology: pure transaction flow per emisor =
//   flow_clp = inv_curr − inv_prev × (price_curr / price_prev)
// Mathematically equivalent to (units_end − units_start) × price_end, but
// works around the LATAM (LTM) `unidades` int32 overflow (−2,147,483,648) in
// historial_carteras_full by deriving the units delta from inv & price.
//
// Data source: mv_chist_chilean_stocks_by_nemo. Only available for CHIST
// fechas (≤ Nov-25 today). For SP XML fechas the calculation is unavailable —
// the page must block transactions for those periods.
type NemoSnapshot = { nemo: string; emisor: string; inv_clp: number; price_clp: number };

async function getNemoSnapshot(fecha: string): Promise<NemoSnapshot[]> {
  const data = await query<{
    nemo: string;
    emisor: string;
    inv_clp: unknown;
    price_clp: unknown;
  }>(
    `SELECT nemo, emisor, inv_clp, price_clp
     FROM ${MART}.mv_chist_chilean_stocks_by_nemo
     WHERE fecha_reporte = DATE(@fecha)`,
    { fecha },
  );
  return data.map((r) => ({
    nemo: r.nemo as string,
    emisor: r.emisor as string,
    inv_clp: toNum(r.inv_clp) || 0,
    price_clp: toNum(r.price_clp) || 0,
  }));
}

async function getFxClpPerUsd(fecha: string): Promise<number> {
  const data = await query<{ valor: unknown }>(
    `SELECT valor FROM ${RAW}.tipo_cambio
     WHERE fecha = DATE(@fecha) AND instrumento_codigo = @instrumento_codigo
     LIMIT 1`,
    { fecha, instrumento_codigo: 'USDCLP Curncy' },
  );
  return toNum(data[0]?.valor) || 0;
}

function computeFlowsUnits(
  end: NemoSnapshot[],
  start: NemoSnapshot[],
  fxCurr: number,
  topN: number,
): ChileanFlowsBucket {
  const startByNemo = new Map(start.map((s) => [s.nemo, s]));
  const seen = new Set<string>();
  const flowsByEmisor = new Map<string, number>();
  for (const c of end) {
    seen.add(c.nemo);
    const p = startByNemo.get(c.nemo);
    let flowClp: number;
    if (!p) {
      // New position: full inv is a purchase at end price.
      flowClp = c.inv_clp;
    } else if (!p.price_clp) {
      // Defensive: fall back to plain delta if start price missing.
      flowClp = c.inv_clp - p.inv_clp;
    } else {
      // flow_clp = inv_curr − inv_prev × (price_curr / price_prev)
      const priceRatio = c.price_clp / p.price_clp;
      flowClp = c.inv_clp - p.inv_clp * priceRatio;
    }
    flowsByEmisor.set(c.emisor, (flowsByEmisor.get(c.emisor) ?? 0) + flowClp);
  }
  // Closed positions: in start but not in end.
  for (const p of start) {
    if (seen.has(p.nemo)) continue;
    flowsByEmisor.set(p.emisor, (flowsByEmisor.get(p.emisor) ?? 0) - p.inv_clp);
  }
  const fxScale = fxCurr * 1e6;
  const deltas: ChileanStockIssuerRow[] = [];
  let totalNet = 0;
  for (const [emisor, flowClp] of flowsByEmisor) {
    const usd = fxScale > 0 ? flowClp / fxScale : 0;
    deltas.push({ emisor, monto_usd_mm: usd });
    totalNet += usd;
  }
  deltas.sort((a, b) => b.monto_usd_mm - a.monto_usd_mm);
  return {
    purchases: deltas.filter((d) => d.monto_usd_mm > 0).slice(0, topN),
    sales: deltas.filter((d) => d.monto_usd_mm < 0).slice(-topN).reverse(),
    totalNet,
  };
}

/**
 * MTD/YTD/LTM top purchases & sales of chilean stocks (PDF 06).
 * Uses pure transaction-flow methodology (inv − inv_prev × price_ratio).
 * Only works when `fecha` and the baselines are inside CHIST coverage.
 * Returns empty buckets if the data isn't available, so the UI can render a
 * "not available" state instead of misleading numbers.
 */
export async function getChileanStocksTopFlows(
  fecha: string,
  topN = 10,
): Promise<ChileanStocksTopFlows> {
  const [y, m] = fecha.split('-').map(Number);
  const lastDayOfMonth = (year: number, month1Indexed: number) =>
    new Date(Date.UTC(year, month1Indexed, 0)).toISOString().slice(0, 10);
  const mtd = lastDayOfMonth(y, m - 1);
  const ytd = `${y - 1}-12-31`;
  const ltm = lastDayOfMonth(y - 1, m);

  const [end, mtdSnap, ytdSnap, ltmSnap, fxCurr] = await Promise.all([
    getNemoSnapshot(fecha),
    getNemoSnapshot(mtd),
    getNemoSnapshot(ytd),
    getNemoSnapshot(ltm),
    getFxClpPerUsd(fecha),
  ]);

  const empty = (): ChileanFlowsBucket => ({ purchases: [], sales: [], totalNet: 0 });
  return {
    fechaEnd: fecha,
    fechaMtdStart: mtd,
    fechaYtdStart: ytd,
    fechaLtmStart: ltm,
    mtd: end.length && mtdSnap.length ? computeFlowsUnits(end, mtdSnap, fxCurr, topN) : empty(),
    ytd: end.length && ytdSnap.length ? computeFlowsUnits(end, ytdSnap, fxCurr, topN) : empty(),
    ltm: end.length && ltmSnap.length ? computeFlowsUnits(end, ltmSnap, fxCurr, topN) : empty(),
  };
}

export async function getChileanStocksDates(): Promise<string[]> {
  // Source = v_chilean_stocks_gics (CHIST-bound, max ~Nov-25 today). The
  // by-issuer view goes further (SP XML covers Dec-25..Apr-26) but GICS
  // classification needs nemo-level data only CHIST has. Picking gics dates
  // here keeps the default landing fecha aligned with both cards on this
  // page; users wanting SP XML transactions can still navigate via URL.
  const data = await query<{ fecha_reporte: unknown }>(
    `SELECT fecha_reporte FROM ${MART}.v_chilean_stocks_gics
     WHERE fecha_reporte >= DATE '2025-01-01'
     ORDER BY fecha_reporte DESC
     LIMIT 5000`,
  );
  return Array.from(new Set(data.map((r) => toDateStr(r.fecha_reporte))));
}

// =====================================================================
// PDF Sec 05 — Portfolio breakdown por sector GICS
// =====================================================================

export type GicsSectorRow = {
  sector: string;        // gics_sector_shortname (e.g. "Financials")
  sectorName: string;    // gics_sector_name
  nEmisores: number;
  aumUsdMm: number;
  pct: number;
  topIssuers: { emisor: string; aumUsdMm: number }[];
};

export type GicsBreakdown = {
  fecha: string;
  totalAumUsdMm: number;
  sectors: GicsSectorRow[];
};

/**
 * Sec 05 portfolio breakdown by GICS sector. Aggregates v_chilean_stocks_gics
 * across AFP × multifondo for a given fecha. Returns sectors ranked by AUM
 * with the top 5 issuers per sector for drill-down.
 */
export async function getChileanStocksGicsBreakdown(
  fecha: string,
): Promise<GicsBreakdown> {
  // ~1,750 rows per fecha (7 AFPs × 5 multifondos × ~50 emisores); BigQuery
  // returns them in a single call.
  type Row = {
    gics_sector: string | null;
    gics_sector_name: string | null;
    emisor: string | null;
    nemo: string | null;
    monto_usd_mm: unknown;
  };
  const data = await query<Row>(
    `SELECT gics_sector, gics_sector_name, emisor, nemo, monto_usd_mm
     FROM ${MART}.v_chilean_stocks_gics
     WHERE fecha_reporte = DATE(@fecha)`,
    { fecha },
  );

  // Aggregate by sector first
  type AccSector = {
    sectorName: string;
    issuers: Map<string, number>;
    total: number;
  };
  const bySector = new Map<string, AccSector>();
  let total = 0;
  for (const r of data ?? []) {
    const sector = (r.gics_sector as string) ?? '—';
    const sectorName = (r.gics_sector_name as string) ?? '—';
    const emisor = (r.emisor as string) ?? '—';
    const amount = toNum(r.monto_usd_mm) || 0;
    if (!bySector.has(sector)) {
      bySector.set(sector, { sectorName, issuers: new Map(), total: 0 });
    }
    const acc = bySector.get(sector)!;
    acc.issuers.set(emisor, (acc.issuers.get(emisor) ?? 0) + amount);
    acc.total += amount;
    total += amount;
  }

  const sectors: GicsSectorRow[] = Array.from(bySector.entries())
    .map(([sector, acc]) => {
      const sortedIssuers = Array.from(acc.issuers.entries())
        .map(([emisor, aumUsdMm]) => ({ emisor, aumUsdMm }))
        .sort((a, b) => b.aumUsdMm - a.aumUsdMm);
      return {
        sector,
        sectorName: acc.sectorName,
        nEmisores: acc.issuers.size,
        aumUsdMm: acc.total,
        pct: total > 0 ? acc.total / total : 0,
        topIssuers: sortedIssuers.slice(0, 5),
      };
    })
    .sort((a, b) => b.aumUsdMm - a.aumUsdMm);

  return { fecha, totalAumUsdMm: total, sectors };
}
