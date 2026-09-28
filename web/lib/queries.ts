// Fuente: BigQuery (antes Supabase/PostgREST)
import { MART, RAW, query, queryOne, toDateStr, toNum } from './db';
import {
  AFPS,
  C1_CATEGORIES,
  type AfpC1Row,
  type AfpName,
  type C1Name,
  type EvolutionPoint,
  type MultifondoRow,
  type OverviewRow,
} from './dimensions';

export async function getAvailableDates(limit = 60): Promise<string[]> {
  // v_total = cartera (CHIST) dates, the binding constraint — v_aum reaches
  // further back/forward but NAV/Uncalled only exist where carteras do.
  const data = await query<{ fecha: unknown }>(
    `SELECT fecha FROM ${MART}.v_total
     WHERE fecha >= DATE '2025-01-01'
     ORDER BY fecha DESC
     LIMIT @lim`,
    { lim: limit * AFPS.length },
  );
  return Array.from(new Set(data.map((r) => toDateStr(r.fecha))));
}

export async function getOverview(fecha: string): Promise<OverviewRow[]> {
  const [aumRows, navRows, uncRows, totRows] = await Promise.all([
    query<{ afp: string; aum_usd_mm: unknown }>(
      `SELECT afp, aum_usd_mm FROM ${MART}.v_aum WHERE fecha = DATE(@fecha)`,
      { fecha },
    ),
    query<{ afp: string; nav_usd_mm: unknown }>(
      `SELECT afp, nav_usd_mm FROM ${MART}.v_nav WHERE fecha = DATE(@fecha)`,
      { fecha },
    ),
    query<{ afp: string; uncalled_usd_mm: unknown }>(
      `SELECT afp, uncalled_usd_mm FROM ${MART}.v_uncalled WHERE fecha = DATE(@fecha)`,
      { fecha },
    ),
    query<{ afp: string; total_usd_mm: unknown }>(
      `SELECT afp, total_usd_mm FROM ${MART}.v_total WHERE fecha = DATE(@fecha)`,
      { fecha },
    ),
  ]);
  const map = new Map<string, OverviewRow>();
  const ensure = (afp: string) => {
    let row = map.get(afp);
    if (!row) {
      row = { afp, aum: 0, nav: 0, uncalled: 0, total: 0 };
      map.set(afp, row);
    }
    return row;
  };
  for (const r of aumRows) ensure(r.afp).aum = toNum(r.aum_usd_mm) || 0;
  for (const r of navRows) ensure(r.afp).nav = toNum(r.nav_usd_mm) || 0;
  for (const r of uncRows) ensure(r.afp).uncalled = toNum(r.uncalled_usd_mm) || 0;
  for (const r of totRows) ensure(r.afp).total = toNum(r.total_usd_mm) || 0;

  return [...map.values()]
    .filter((r) => r.aum + r.nav + r.uncalled + r.total > 0)
    .sort((a, b) => b.total - a.total);
}

// Per-multifondo (A–E) breakdown for every AFP, keyed by AFP name. Powers the
// expandable Summary AFP rows. NAV/Uncalled/Total come from v_afp_multifondo
// (aggregates mv_chist_aa to ~40 rows/date). AUM by multifondo isn't in that
// view, so it's derived here from valores_cuota_patrimonio + the date's FX rate
// (CLFXDOOB_sindesf), mirroring how mv_aum computes AFP-level AUM.
export async function getOverviewDetail(
  fecha: string,
): Promise<Record<string, MultifondoRow[]>> {
  const [mfRows, fxRow, patRows] = await Promise.all([
    query<{
      afp: string;
      tipo_de_fondo: string;
      nav_usd_mm: unknown;
      uncalled_usd_mm: unknown;
      total_usd_mm: unknown;
    }>(
      `SELECT afp, tipo_de_fondo, nav_usd_mm, uncalled_usd_mm, total_usd_mm
       FROM ${MART}.v_afp_multifondo
       WHERE fecha = DATE(@fecha)`,
      { fecha },
    ),
    queryOne<{ valor: unknown }>(
      `SELECT valor FROM ${RAW}.tipo_cambio
       WHERE fecha = DATE(@fecha) AND instrumento_codigo = @instrumento_codigo
       LIMIT 1`,
      { fecha, instrumento_codigo: 'CLFXDOOB_sindesf' },
    ),
    query<{ afp: string; multifondo: string; valor_patrimonio: unknown }>(
      `SELECT afp, multifondo, valor_patrimonio
       FROM ${RAW}.valores_cuota_patrimonio
       WHERE fecha = DATE(@fecha)`,
      { fecha },
    ),
  ]);

  const fx = toNum(fxRow?.valor) || 0;

  // AUM (USD MM) per afp+multifondo from the cuota/patrimonio table.
  const aumByKey = new Map<string, number>();
  if (fx > 0) {
    for (const r of patRows) {
      const key = `${r.afp}|${r.multifondo}`;
      const aum = (toNum(r.valor_patrimonio) || 0) / fx / 1_000_000;
      aumByKey.set(key, (aumByKey.get(key) ?? 0) + aum);
    }
  }

  const byAfp: Record<string, MultifondoRow[]> = {};
  for (const r of mfRows) {
    const afp = r.afp as string;
    const mf = r.tipo_de_fondo as string;
    (byAfp[afp] ??= []).push({
      multifondo: mf,
      nav: toNum(r.nav_usd_mm) || 0,
      uncalled: toNum(r.uncalled_usd_mm) || 0,
      total: toNum(r.total_usd_mm) || 0,
      aum: aumByKey.get(`${afp}|${mf}`) ?? 0,
    });
  }
  for (const rows of Object.values(byAfp)) {
    rows.sort((a, b) => a.multifondo.localeCompare(b.multifondo));
  }
  return byAfp;
}

export async function getNavByAfpC1(fecha: string): Promise<AfpC1Row[]> {
  const data = await query<{ afp: string; c1: string; total_usd_mm: unknown }>(
    `SELECT afp, c1, total_usd_mm FROM ${MART}.v_afp_c1 WHERE fecha = DATE(@fecha)`,
    { fecha },
  );

  const afpSet = new Set<string>(AFPS);
  const byAfp = new Map<string, AfpC1Row>();
  for (const r of data) {
    const afp = r.afp as string;
    if (!afpSet.has(afp)) continue;
    if (!byAfp.has(afp)) {
      const empty: AfpC1Row = { afp } as AfpC1Row;
      for (const c of C1_CATEGORIES) empty[c] = 0;
      byAfp.set(afp, empty);
    }
    if ((C1_CATEGORIES as readonly string[]).includes(r.c1 as string)) {
      byAfp.get(afp)![r.c1 as C1Name] = toNum(r.total_usd_mm) || 0;
    }
  }
  return [...byAfp.values()]
    .filter((row) => C1_CATEGORIES.some((c) => row[c] > 0))
    .sort((a, b) => AFPS.indexOf(a.afp as AfpName) - AFPS.indexOf(b.afp as AfpName));
}

export async function getEvolution(): Promise<{
  totals: EvolutionPoint[];
  aums: EvolutionPoint[];
}> {
  const [totalRows, aumRows] = await Promise.all([
    query<{ fecha: unknown; afp: string; total_usd_mm: unknown }>(
      `SELECT fecha, afp, total_usd_mm FROM ${MART}.v_total ORDER BY fecha ASC`,
    ),
    query<{ fecha: unknown; afp: string; aum_usd_mm: unknown }>(
      `SELECT fecha, afp, aum_usd_mm FROM ${MART}.v_aum ORDER BY fecha ASC`,
    ),
  ]);

  const afpSet = new Set<string>(AFPS);

  function pivot(
    rows: { fecha: string; afp: string; value: number }[],
  ): EvolutionPoint[] {
    const byFecha = new Map<string, EvolutionPoint>();
    for (const r of rows) {
      if (!afpSet.has(r.afp)) continue;
      if (!byFecha.has(r.fecha)) byFecha.set(r.fecha, { fecha: r.fecha });
      byFecha.get(r.fecha)![r.afp as AfpName] = r.value || 0;
    }
    return [...byFecha.values()].sort((a, b) => a.fecha.localeCompare(b.fecha));
  }

  return {
    totals: pivot(
      totalRows.map((r) => ({
        fecha: toDateStr(r.fecha),
        afp: r.afp as string,
        value: toNum(r.total_usd_mm) || 0,
      })),
    ),
    aums: pivot(
      aumRows.map((r) => ({
        fecha: toDateStr(r.fecha),
        afp: r.afp as string,
        value: toNum(r.aum_usd_mm) || 0,
      })),
    ),
  };
}
