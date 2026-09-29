// Fuente: BigQuery (antes Supabase/PostgREST)
import { MART, query, toDateStr, toDateStrOrNull, toNum } from './db';
import type { ModuleFreshness } from './types-freshness';

// All module/source freshness rows. Cached process-side for 60s so a page with
// a header badge + several card badges doesn't fire one round-trip per badge
// (same pattern as queries-data-sources). The underlying view computes is_behind
// against current_date at query time, so a few minutes of staleness is harmless.
let cached: { ts: number; rows: ModuleFreshness[] } | null = null;
const CACHE_TTL_MS = 60_000;

export async function getAllModuleFreshness(): Promise<ModuleFreshness[]> {
  if (cached && Date.now() - cached.ts < CACHE_TTL_MS) {
    return cached.rows;
  }
  const data = await query<{
    module_key: string;
    source_label: string;
    as_of_date: unknown;
    published_date: unknown;
    lag_kind: ModuleFreshness['lag_kind'];
    expected_lag_days: unknown;
    is_primary: unknown;
    is_behind: unknown;
  }>(
    `SELECT module_key, source_label, as_of_date, published_date, lag_kind,
            expected_lag_days, is_primary, is_behind
     FROM ${MART}.v_module_freshness`,
  );
  const rows: ModuleFreshness[] = data.map((r) => ({
    module_key: r.module_key,
    source_label: r.source_label,
    as_of_date: toDateStr(r.as_of_date),
    published_date: toDateStrOrNull(r.published_date),
    lag_kind: r.lag_kind,
    expected_lag_days: toNum(r.expected_lag_days),
    is_primary: Boolean(r.is_primary),
    is_behind: Boolean(r.is_behind),
  }));
  cached = { ts: Date.now(), rows };
  return rows;
}

// Returns the primary row (page badge) plus every source for a module (card badges).
export async function getModuleFreshness(moduleKey: string): Promise<{
  primary: ModuleFreshness | null;
  sources: ModuleFreshness[];
}> {
  const all = await getAllModuleFreshness();
  const sources = all.filter((r) => r.module_key === moduleKey);
  const primary = sources.find((r) => r.is_primary) ?? sources[0] ?? null;
  return { primary, sources };
}
