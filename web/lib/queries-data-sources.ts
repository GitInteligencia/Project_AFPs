// Fuente: BigQuery (antes Supabase/PostgREST)
import { DIM, query, toDateStrOrNull } from './db';
import type { DataSourceRow } from './types-data-sources';

let cachedAll: { ts: number; rows: DataSourceRow[] } | null = null;
const CACHE_TTL_MS = 60_000;

// All dataset metadata. Cached process-side for 60s so that the typical page
// render with multiple <SourceBadge> doesn't fire one round-trip per badge.
export async function getAllDataSources(): Promise<DataSourceRow[]> {
  if (cachedAll && Date.now() - cachedAll.ts < CACHE_TTL_MS) {
    return cachedAll.rows;
  }
  const data = await query<{
    dataset_key: string;
    display_name: string;
    current_source: string;
    target_source: string;
    pdf_section: string | null;
    excel_seed_path: string | null;
    excel_seed_periodo: string | null;
    last_loaded_at: unknown;
    last_loaded_by: string | null;
    migration_plan: string | null;
    notes: string | null;
  }>(
    `SELECT dataset_key, display_name, current_source, target_source, pdf_section,
            excel_seed_path, excel_seed_periodo, last_loaded_at, last_loaded_by,
            migration_plan, notes
     FROM ${DIM}.dim_data_sources
     ORDER BY pdf_section ASC NULLS FIRST, dataset_key ASC`,
  );
  const rows = data.map((r) => ({
    dataset_key: r.dataset_key as string,
    display_name: r.display_name as string,
    current_source: r.current_source as DataSourceRow['current_source'],
    target_source: r.target_source as DataSourceRow['target_source'],
    pdf_section: (r.pdf_section as string | null) ?? null,
    excel_seed_path: (r.excel_seed_path as string | null) ?? null,
    excel_seed_periodo: (r.excel_seed_periodo as string | null) ?? null,
    last_loaded_at: toDateStrOrNull(r.last_loaded_at),
    last_loaded_by: (r.last_loaded_by as string | null) ?? null,
    migration_plan: (r.migration_plan as string | null) ?? null,
    notes: (r.notes as string | null) ?? null,
  }));
  cachedAll = { ts: Date.now(), rows };
  return rows;
}

export async function getDataSource(
  datasetKey: string,
): Promise<DataSourceRow | null> {
  const all = await getAllDataSources();
  return all.find((r) => r.dataset_key === datasetKey) ?? null;
}
