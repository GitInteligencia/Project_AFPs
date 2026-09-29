// Fuente: BigQuery (antes Supabase/PostgREST)
import { DIM, MART, query, toDateStr, toNum } from './db';
import type {
  DistributorMappingRow,
  DistributorSec09Row,
  UnmappedManagerRow,
} from './types-distributors';

export async function getDistributorMapping(): Promise<DistributorMappingRow[]> {
  const data = await query<{
    manager: string;
    distributor: string;
    is_ambiguous: unknown;
    notes: string | null;
    updated_at: unknown;
    updated_by: string | null;
  }>(
    `SELECT manager, distributor, is_ambiguous, notes, updated_at, updated_by
     FROM ${DIM}.dim_distributor_by_manager
     ORDER BY manager ASC`,
  );
  return data.map((r) => ({
    manager: r.manager as string,
    distributor: r.distributor as string,
    is_ambiguous: Boolean(r.is_ambiguous),
    notes: (r.notes as string | null) ?? null,
    updated_at: toDateStr(r.updated_at),
    updated_by: (r.updated_by as string | null) ?? null,
  }));
}

export async function getDistributorsSec09Dates(): Promise<string[]> {
  const data = await query<{ fecha_reporte: unknown }>(
    `SELECT fecha_reporte FROM ${MART}.v_distributors_sec09
     WHERE fecha_reporte >= DATE '2025-01-01'
     ORDER BY fecha_reporte DESC
     LIMIT 10000`,
  );
  const seen = new Set<string>();
  const out: string[] = [];
  for (const r of data) {
    const f = toDateStr(r.fecha_reporte);
    if (seen.has(f)) continue;
    seen.add(f);
    out.push(f);
  }
  return out;
}

type Sec09Raw = {
  fecha_reporte: unknown;
  distributor: string;
  manager: string;
  is_mapped: unknown;
  monto_usd_mm: unknown;
};

function mapSec09(r: Sec09Raw): DistributorSec09Row {
  return {
    fecha_reporte: toDateStr(r.fecha_reporte),
    distributor: r.distributor as string,
    manager: r.manager as string,
    is_mapped: Boolean(r.is_mapped),
    monto_usd_mm: toNum(r.monto_usd_mm) || 0,
  };
}

export async function getDistributorsSec09(
  fecha: string,
): Promise<DistributorSec09Row[]> {
  const data = await query<Sec09Raw>(
    `SELECT fecha_reporte, distributor, manager, is_mapped, monto_usd_mm
     FROM ${MART}.v_distributors_sec09
     WHERE fecha_reporte = DATE(@fecha)`,
    { fecha },
  );
  return data.map(mapSec09);
}

// Resolve the four PDF Sec 09 baseline fechas given a "today" date:
//   - oneYearAgo: same month-end one year back
//   - lastYearEnd: Dec 31 of previous calendar year
//   - lastMonth:  last day of previous month
//   - today:      the input
// The view returns whatever dates exist; the caller falls back to the closest
// available if a baseline isn't present.
export function distributorBaselines(fecha: string): {
  oneYearAgo: string;
  lastYearEnd: string;
  lastMonth: string;
  today: string;
} {
  const [y, m] = fecha.split('-').map(Number);
  const lastDayOfMonth = (year: number, month1Indexed: number) =>
    new Date(Date.UTC(year, month1Indexed, 0)).toISOString().slice(0, 10);
  return {
    oneYearAgo: lastDayOfMonth(y - 1, m),
    lastYearEnd: `${y - 1}-12-31`,
    lastMonth: lastDayOfMonth(y, m - 1),
    today: fecha,
  };
}

export async function getDistributorsSec09Batch(
  fechas: string[],
): Promise<DistributorSec09Row[]> {
  const unique = Array.from(new Set(fechas));
  const data = await query<Sec09Raw>(
    `SELECT fecha_reporte, distributor, manager, is_mapped, monto_usd_mm
     FROM ${MART}.v_distributors_sec09
     WHERE fecha_reporte IN UNNEST(@fechas)`,
    { fechas: unique },
    // Explicit element type: an empty array can't be inferred by the client.
    { types: { fechas: ['DATE'] } },
  );
  return data.map(mapSec09);
}

// Managers with foreign AUM > 0 on the latest fecha that have no entry in
// dim_distributor_by_manager. Surfaces the cleanup queue for the admin UI.
export async function getUnmappedManagers(): Promise<UnmappedManagerRow[]> {
  const dates = await getDistributorsSec09Dates();
  if (dates.length === 0) return [];
  const latest = dates[0];
  const rows = await getDistributorsSec09(latest);
  const unmapped = rows.filter((r) => !r.is_mapped && r.distributor === 'Unmapped');
  const byManager = new Map<string, UnmappedManagerRow>();
  for (const r of unmapped) {
    const existing = byManager.get(r.manager);
    if (existing) {
      existing.monto_usd_mm += r.monto_usd_mm;
    } else {
      // funds count is not in the view; rough approximation = 1 since the
      // view is already aggregated by (fecha, distributor, manager). For an
      // accurate funds count we'd need a separate query against
      // v_foreign_by_fund_combined; not worth the round-trip for v1.
      byManager.set(r.manager, {
        manager: r.manager,
        funds: 1,
        monto_usd_mm: r.monto_usd_mm,
      });
    }
  }
  return Array.from(byManager.values()).sort(
    (a, b) => b.monto_usd_mm - a.monto_usd_mm,
  );
}
