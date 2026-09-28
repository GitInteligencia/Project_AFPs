// Fuente: BigQuery (antes Supabase/PostgREST)
import { DIM, query, toDateStr, toNum } from './db';
import type { Sec08FlowRow } from './types-sec08';

export async function getSec08TopFlows(): Promise<Sec08FlowRow[]> {
  const data = await query<{
    fecha: unknown;
    period_type: string;
    direction: string;
    rk: unknown;
    fondo: string;
    amount_usd_mm: unknown;
  }>(
    `SELECT fecha, period_type, direction, rk, fondo, amount_usd_mm
     FROM ${DIM}.dim_sec08_top_flows
     ORDER BY fecha DESC, period_type ASC, direction ASC, rk ASC`,
  );
  return data.map((r) => ({
    fecha: toDateStr(r.fecha),
    period_type: r.period_type as Sec08FlowRow['period_type'],
    direction: r.direction as Sec08FlowRow['direction'],
    rk: toNum(r.rk) || 0,
    fondo: r.fondo as string,
    amount_usd_mm: toNum(r.amount_usd_mm) || 0,
  }));
}
