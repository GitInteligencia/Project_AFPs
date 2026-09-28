import 'server-only';
import { BigQuery, type Query } from '@google-cloud/bigquery';
import { unstable_cache } from 'next/cache';
import { connection } from 'next/server';

// BigQuery read layer for the dashboard (replaces lib/supabase-server.ts).
//
// - Auth is Application Default Credentials only (Cloud Run service account
//   in prod, `gcloud auth application-default login` locally). No key files.
// - Every query result goes through Next's Data Cache (`unstable_cache`) for
//   REVALIDATE_S seconds under the `bq` tag, so navigating between tabs/modules
//   doesn't re-run BigQuery jobs for data that changes once a month. The sync
//   job busts it via POST /api/revalidate → revalidateTag(BQ_CACHE_TAG).
// - The client is created lazily: importing this module never touches the
//   network or credentials, so `next build` works without any GCP env vars.

export const BQ_CACHE_TAG = 'bq';
const REVALIDATE_S = 300; // same TTL supabase-server.ts used

const PROJECT_ID = process.env.GCP_PROJECT_ID ?? 'pat-uat-global';
const LOCATION = process.env.BQ_LOCATION ?? 'southamerica-west1';

function datasetRef(dataset: string): string {
  return `\`${PROJECT_ID}.${dataset}\``;
}

// Fully-qualified, back-quoted dataset identifiers for string interpolation
// inside SQL text: `${MART}.v_aum` → `pat-uat-global.afp_mart`.v_aum
export const RAW = datasetRef(process.env.BQ_DATASET_RAW ?? 'afp_raw');
export const DIM = datasetRef(process.env.BQ_DATASET_DIM ?? 'afp_dim');
export const MART = datasetRef(process.env.BQ_DATASET_MART ?? 'afp_mart');

let client: BigQuery | null = null;

function getClient(): BigQuery {
  if (!client) {
    client = new BigQuery({ projectId: PROJECT_ID, location: LOCATION });
  }
  return client;
}

export type QueryParams = Record<string, unknown>;

export type QueryOptions = {
  // Explicit BigQuery types per named parameter. Only needed when the client
  // can't infer them — e.g. an empty array (`{ fechas: ['DATE'] }`) or a null.
  types?: Record<string, string | string[]>;
};

// Normalize the wrapper objects the client returns so cached rows are plain
// JSON and stable across cache hits/misses:
//   DATE/DATETIME/TIME/TIMESTAMP → their `.value` string
//   NUMERIC/BIGNUMERIC (Big instances) → decimal string (callers apply toNum)
// INT64 and FLOAT64 already arrive as JS numbers; BOOL as boolean.
function plainValue(v: unknown): unknown {
  if (v === null || v === undefined) return v;
  if (typeof v !== 'object') return v;
  if (Array.isArray(v)) return v.map(plainValue);
  const o = v as Record<string, unknown>;
  if (typeof o.value === 'string' && Object.keys(o).length === 1) return o.value;
  // big.js instances expose toFixed(); keep the exact decimal text.
  if (typeof (o as { toFixed?: unknown }).toFixed === 'function' && 'c' in o && 'e' in o && 's' in o) {
    return String(v);
  }
  const out: Record<string, unknown> = {};
  for (const [k, val] of Object.entries(o)) out[k] = plainValue(val);
  return out;
}

async function runQuery<T>(
  sql: string,
  params: QueryParams,
  types?: QueryOptions['types'],
): Promise<T[]> {
  const req: Query = { query: sql, params, location: LOCATION };
  if (types) req.types = types as Query['types'];
  try {
    const [rows] = await getClient().query(req);
    return (rows as unknown[]).map(plainValue) as T[];
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    throw new Error(
      `BigQuery query failed (project=${PROJECT_ID}, location=${LOCATION}): ${msg}\n` +
        `Check GCP_PROJECT_ID / BQ_LOCATION / BQ_DATASET_* and that Application ` +
        `Default Credentials are available (Cloud Run SA or gcloud auth application-default login).\n` +
        `SQL: ${sql.trim().slice(0, 500)}`,
    );
  }
}

/**
 * Run a parameterized BigQuery SQL query (named `@param` placeholders) and
 * return its rows, cached in Next's Data Cache for REVALIDATE_S seconds under
 * the `bq` tag. Cache key = SQL text + serialized params.
 *
 * `connection()` is awaited first so a route that reads BigQuery is never
 * prerendered at `next build` (the container image is built without GCP
 * credentials). At request time it resolves immediately; the surrounding
 * `unstable_cache` still gives the same 300 s data TTL as before.
 */
export async function query<T = Record<string, unknown>>(
  sql: string,
  params: QueryParams = {},
  options: QueryOptions = {},
): Promise<T[]> {
  await connection();
  const cached = unstable_cache(
    () => runQuery<T>(sql, params, options.types),
    [BQ_CACHE_TAG, sql, JSON.stringify(params), JSON.stringify(options.types ?? null)],
    { revalidate: REVALIDATE_S, tags: [BQ_CACHE_TAG] },
  );
  return cached();
}

/** First row of a query or null (PostgREST `.maybeSingle()` equivalent). */
export async function queryOne<T = Record<string, unknown>>(
  sql: string,
  params: QueryParams = {},
  options: QueryOptions = {},
): Promise<T | null> {
  const rows = await query<T>(sql, params, options);
  return rows[0] ?? null;
}

/**
 * BigQuery DATE/TIMESTAMP → string. Accepts the raw wrapper (`{ value }`), an
 * already-normalized string, or a Date. Returns '' for null/undefined so it
 * can stand in for the old `r.fecha as string` casts.
 */
export function toDateStr(v: unknown): string {
  return toDateStrOrNull(v) ?? '';
}

export function toDateStrOrNull(v: unknown): string | null {
  if (v === null || v === undefined) return null;
  if (typeof v === 'string') return v;
  if (v instanceof Date) return v.toISOString();
  if (typeof v === 'object' && typeof (v as { value?: unknown }).value === 'string') {
    return (v as { value: string }).value;
  }
  return String(v);
}

/**
 * BigQuery NUMERIC/BIGNUMERIC arrive as decimal strings (or Big instances),
 * INT64/FLOAT64 as numbers. Safe `Number()`: null/undefined/NaN → 0, which is
 * what the old `Number(r.x) || 0` did.
 */
export function toNum(v: unknown): number {
  if (v === null || v === undefined) return 0;
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
}

/** Like toNum but preserves null (for nullable metrics: `x != null ? Number(x) : null`). */
export function toNumOrNull(v: unknown): number | null {
  if (v === null || v === undefined) return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}
