// Fuente: BigQuery (antes Supabase/PostgREST)
import { DIM, RAW, query, queryOne, toDateStr, toDateStrOrNull, toNum, toNumOrNull } from './db';

// Ajustes_Dashboard 4.1/4.2 — cartera, contribuidores del retorno y rentabilidad
// por fondo Moneda de cada familia. Fuente: sync/sync_ipd_strategy.py
// (Inteligencia_Producto TBL_IPA_V2 + TBL_RENTABILIDADES_SERIES, agregado
// mensual precalculado — el diario nunca toca la base analítica).

export type IpdFundRef = {
  id_fund: number;
  fund_label: string;
  rent_id_fund: number | null;
};

export type AttributionRow = {
  id_instrumento: number;
  instrumento: string | null;
  company: string | null;
  currency: string | null;
  avg_weight: number;
  contrib_total: number; // fraction (0.0123 = +1.23%)
  contrib_price: number;
  contrib_fx_carry: number;
};

export type AttributionPeriod = {
  months: string[]; // YYYY-MM covered, ascending
  rows: AttributionRow[]; // all instruments, sorted by contrib_total desc
  ret_calc: number; // compounded Σ-contribution return of the period
  ret_serie: number | null; // official share-class return (null if any month missing)
  residual: number | null; // ret_serie - ret_calc (income / cash & other)
};

export type FundAttribution = {
  id_fund: number;
  lastMes: string; // YYYY-MM
  month: AttributionPeriod;
  quarter: AttributionPeriod;
};

export type CarteraRow = {
  id_instrumento: number;
  instrumento: string | null;
  company: string | null;
  currency: string | null;
  source: string | null;
  mval_usd: number;
  weight: number;
};

export type FundCartera = {
  id_fund: number;
  fecha: string;
  nav_usd: number;
  rows: CarteraRow[]; // sorted by |weight| desc
};

export type FundReturnPoint = {
  fecha: string; // EOM
  mtd: number | null;
  ytd: number | null;
  y1: number | null;
  patrimonio: number | null;
  bm_mtd: number | null;
  bm_ytd: number | null;
  bm_y1: number | null;
};

export type FundReturns = {
  id_fund: number;
  currency: string; // USD, o CLP cuando el fondo no tiene serie USD (MDLAT)
  bm_ticker: string | null;
  series: FundReturnPoint[]; // ascending by fecha
};

export async function getStrategyIpdFunds(
  family_id: number,
): Promise<IpdFundRef[]> {
  const data = await query<{
    id_fund: unknown;
    fund_label: string;
    rent_id_fund: unknown;
  }>(
    `SELECT id_fund, fund_label, rent_id_fund
     FROM ${DIM}.dim_strategy_ipd_funds
     WHERE family_id = @family_id
     ORDER BY id_fund ASC`,
    { family_id },
  );
  return data.map((r) => ({
    id_fund: toNum(r.id_fund),
    fund_label: r.fund_label as string,
    rent_id_fund: toNumOrNull(r.rent_id_fund),
  }));
}

function compound(rets: Array<number | null>): number | null {
  let acc = 1;
  for (const r of rets) {
    if (r == null) return null;
    acc *= 1 + r;
  }
  return acc - 1;
}

async function fetchAttributionRows(
  id_fund: number,
  meses: string[], // YYYY-MM-01 date strings
): Promise<Map<string, AttributionRow & { n: number }>> {
  const acc = new Map<string, AttributionRow & { n: number }>();
  const data = await query<{
    id_instrumento: unknown;
    instrumento: string | null;
    company: string | null;
    currency: string | null;
    avg_weight: unknown;
    contrib_total: unknown;
    contrib_price: unknown;
    contrib_fx_carry: unknown;
  }>(
    `SELECT id_instrumento, instrumento, company, currency, avg_weight,
            contrib_total, contrib_price, contrib_fx_carry
     FROM ${RAW}.ipd_attribution_monthly
     WHERE id_fund = @id_fund AND mes IN UNNEST(@meses)
     ORDER BY row_id ASC`,
    { id_fund, meses },
    { types: { meses: ['DATE'] } },
  );
  for (const r of data) {
    const key = String(r.id_instrumento);
    const prev = acc.get(key);
    const row = {
      id_instrumento: toNum(r.id_instrumento),
      instrumento: (r.instrumento as string | null) ?? null,
      company: (r.company as string | null) ?? null,
      currency: (r.currency as string | null) ?? null,
      avg_weight: toNum(r.avg_weight) || 0,
      contrib_total: toNum(r.contrib_total) || 0,
      contrib_price: toNum(r.contrib_price) || 0,
      contrib_fx_carry: toNum(r.contrib_fx_carry) || 0,
    };
    if (!prev) {
      acc.set(key, { ...row, n: 1 });
    } else {
      prev.avg_weight += row.avg_weight;
      prev.contrib_total += row.contrib_total;
      prev.contrib_price += row.contrib_price;
      prev.contrib_fx_carry += row.contrib_fx_carry;
      prev.n += 1;
    }
  }
  for (const v of acc.values()) v.avg_weight /= v.n;
  return acc;
}

export async function getFundAttribution(
  id_fund: number,
): Promise<FundAttribution | null> {
  // últimos 3 meses disponibles del fondo
  const mdata = await query<{
    mes: unknown;
    ret_month: unknown;
    ret_serie: unknown;
    residual: unknown;
  }>(
    `SELECT mes, ret_month, ret_serie, residual
     FROM ${RAW}.ipd_attribution_fund_month
     WHERE id_fund = @id_fund
     ORDER BY mes DESC
     LIMIT 3`,
    { id_fund },
  );
  if (mdata.length === 0) return null;
  const monthsDesc = mdata.map((r) => ({
    mes: toDateStr(r.mes).slice(0, 10),
    ret_month: toNum(r.ret_month) || 0,
    ret_serie: r.ret_serie == null ? null : toNumOrNull(r.ret_serie),
  }));

  const buildPeriod = async (
    slice: typeof monthsDesc,
  ): Promise<AttributionPeriod> => {
    const meses = slice.map((m) => m.mes).sort();
    const rowsMap = await fetchAttributionRows(id_fund, meses);
    const rows = Array.from(rowsMap.values())
      .map(({ n: _n, ...row }) => row)
      .sort((a, b) => b.contrib_total - a.contrib_total);
    const ret_calc = compound(slice.map((m) => m.ret_month)) ?? 0;
    const ret_serie = compound(slice.map((m) => m.ret_serie));
    return {
      months: meses.map((m) => m.slice(0, 7)),
      rows,
      ret_calc,
      ret_serie,
      residual: ret_serie == null ? null : ret_serie - ret_calc,
    };
  };

  const [month, quarter] = await Promise.all([
    buildPeriod(monthsDesc.slice(0, 1)),
    buildPeriod(monthsDesc),
  ]);
  return {
    id_fund,
    lastMes: monthsDesc[0].mes.slice(0, 7),
    month,
    quarter,
  };
}

export async function getFundCartera(
  id_fund: number,
): Promise<FundCartera | null> {
  const latest = await queryOne<{ fecha: unknown }>(
    `SELECT fecha FROM ${RAW}.ipd_cartera_eom
     WHERE id_fund = @id_fund
     ORDER BY fecha DESC
     LIMIT 1`,
    { id_fund },
  );
  const fecha = toDateStrOrNull(latest?.fecha) ?? undefined;
  if (!fecha) return null;

  const data = await query<{
    id_instrumento: unknown;
    instrumento: string | null;
    company: string | null;
    currency: string | null;
    source: string | null;
    mval_usd: unknown;
    weight: unknown;
  }>(
    `SELECT id_instrumento, instrumento, company, currency, source, mval_usd, weight
     FROM ${RAW}.ipd_cartera_eom
     WHERE id_fund = @id_fund AND fecha = DATE(@fecha)
     ORDER BY row_id ASC`,
    { id_fund, fecha },
  );
  const rows: CarteraRow[] = data.map((r) => ({
    id_instrumento: toNum(r.id_instrumento),
    instrumento: (r.instrumento as string | null) ?? null,
    company: (r.company as string | null) ?? null,
    currency: (r.currency as string | null) ?? null,
    source: (r.source as string | null) ?? null,
    mval_usd: toNum(r.mval_usd) || 0,
    weight: toNum(r.weight) || 0,
  }));
  const nav_usd = rows.reduce((s, r) => s + r.mval_usd, 0);
  rows.sort((a, b) => Math.abs(b.weight) - Math.abs(a.weight));
  return { id_fund, fecha, nav_usd, rows };
}

export async function getFundReturns(
  rent_id_fund: number,
): Promise<FundReturns | null> {
  const data = await query<{
    currency: string;
    quiebre: string;
    bm_ticker: string | null;
    fecha: unknown;
    mtd: unknown;
    ytd: unknown;
    y1: unknown;
    patrimonio: unknown;
  }>(
    `SELECT currency, quiebre, bm_ticker, fecha, mtd, ytd, y1, patrimonio
     FROM ${RAW}.ipd_rentabilidades
     WHERE id_fund = @id_fund
     ORDER BY fecha ASC
     LIMIT 2000`,
    { id_fund: rent_id_fund },
  );
  if (data.length === 0) return null;

  // preferir USD; MDLAT (13) solo publica serie CLP
  const currencies = new Set(data.map((r) => r.currency as string));
  const currency = currencies.has('USD') ? 'USD' : 'CLP';
  const rows = data.filter((r) => r.currency === currency);

  // solo fechas de fin de mes (la tabla trae cortes semanales intercalados)
  const isEom = (f: string) => {
    const d = new Date(`${f}T00:00:00Z`);
    const next = new Date(d);
    next.setUTCDate(next.getUTCDate() + 1);
    return next.getUTCDate() === 1;
  };

  const byFecha = new Map<string, FundReturnPoint>();
  let bm_ticker: string | null = null;
  for (const r of rows) {
    const fecha = toDateStr(r.fecha).slice(0, 10);
    if (!isEom(fecha)) continue;
    let p = byFecha.get(fecha);
    if (!p) {
      p = {
        fecha,
        mtd: null, ytd: null, y1: null, patrimonio: null,
        bm_mtd: null, bm_ytd: null, bm_y1: null,
      };
      byFecha.set(fecha, p);
    }
    const num = (v: unknown) => (v == null ? null : toNumOrNull(v));
    if (r.quiebre === 'Serie') {
      // varias series comparten cuota/retorno; la última gana (valores idénticos)
      p.mtd = num(r.mtd);
      p.ytd = num(r.ytd);
      p.y1 = num(r.y1);
      p.patrimonio = num(r.patrimonio);
    } else if (r.quiebre === 'Benchmark') {
      p.bm_mtd = num(r.mtd);
      p.bm_ytd = num(r.ytd);
      p.bm_y1 = num(r.y1);
      bm_ticker = (r.bm_ticker as string | null) ?? bm_ticker;
    }
  }
  const series = Array.from(byFecha.values()).sort((a, b) =>
    a.fecha.localeCompare(b.fecha),
  );
  if (series.length === 0) return null;
  return { id_fund: rent_id_fund, currency, bm_ticker, series };
}
