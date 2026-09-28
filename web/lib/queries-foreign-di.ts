// Fuente: BigQuery (antes Supabase/PostgREST)
import { MART, query, toDateStr, toNum } from './db';

export type DiRow = {
  fecha_valor: string;            // YYYY-MM-DD
  asset_class: string;             // 'Fixed Income' | 'Equity'
  di_category: string | null;      // 'Sovereign' | 'Bank' | 'Corporate' | null (Equity)
  country: string | null;
  currency: string | null;
  usd_mm: number;
};

/**
 * Sec 07 pág 6 — Foreign Direct Investment detail. Sourced from SP XML Cuadro
 * 25 (no lag) intersected with Patria's manual overlay. Returns every leaf row
 * for the four periodos the PDF compares: 3yr ago, 1yr ago, prior month, today.
 *
 * Caller passes only `fecha` (current); baselines are derived to the SP "4to
 * viernes" month-end fecha_valor that lives in the view.
 */
export async function getForeignDirectInvestmentDetail(fecha: string): Promise<{
  fechas: { label: string; fecha_valor: string | null }[];
  rows: DiRow[];
}> {
  const target = derive4Baselines(fecha);
  const targetPeriodos = target
    .filter((t) => t.periodo != null)
    .map((t) => t.periodo as string);

  if (targetPeriodos.length === 0) {
    return { fechas: target.map((t) => ({ label: t.label, fecha_valor: null })), rows: [] };
  }

  const data = await query<{
    periodo: string | null;
    fecha_valor: unknown;
    asset_class: string;
    di_category: string | null;
    country: string | null;
    currency: string | null;
    usd_mm: unknown;
  }>(
    `SELECT periodo, fecha_valor, asset_class, di_category, country, currency, usd_mm
     FROM ${MART}.mv_sp_direct_investment_detail
     WHERE periodo IN UNNEST(@periodos)`,
    { periodos: targetPeriodos },
    { types: { periodos: ['STRING'] } },
  );

  const rows: DiRow[] = data.map((r) => ({
    fecha_valor: toDateStr(r.fecha_valor),
    asset_class: r.asset_class as string,
    di_category: (r.di_category as string | null) ?? null,
    country: (r.country as string | null) ?? null,
    currency: (r.currency as string | null) ?? null,
    usd_mm: toNum(r.usd_mm) || 0,
  }));

  const periodoToFechaValor = new Map<string, string>();
  for (const r of data) {
    if (r.periodo && r.fecha_valor) {
      periodoToFechaValor.set(r.periodo as string, toDateStr(r.fecha_valor));
    }
  }

  return {
    fechas: target.map((t) => ({
      label: t.label,
      fecha_valor: t.periodo ? periodoToFechaValor.get(t.periodo) ?? null : null,
    })),
    rows,
  };
}

function derive4Baselines(fecha: string): {
  label: string;
  periodo: string | null;
}[] {
  const [y, m] = fecha.split('-').map(Number);
  const periodo = (year: number, month1: number) =>
    `${year}-${month1.toString().padStart(2, '0')}`;
  const priorMonth = m === 1 ? periodo(y - 1, 12) : periodo(y, m - 1);
  return [
    { label: '3 years ago', periodo: periodo(y - 3, m) },
    { label: '1 year ago',  periodo: periodo(y - 1, m) },
    { label: '1 month ago', periodo: priorMonth },
    { label: 'Today',       periodo: periodo(y, m) },
  ];
}
