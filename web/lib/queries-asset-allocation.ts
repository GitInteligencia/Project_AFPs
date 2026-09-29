// Fuente: BigQuery (antes Supabase/PostgREST)
import { MART, query, toDateStr, toNum, toNumOrNull } from './db';
import type {
  AssetClassByAfpRow,
  AssetClassByTipoRow,
  AssetClassEvolutionRow,
  AssetClassEvolutionByAfpRow,
  LocalFiRow,
} from './types-asset-allocation';

/**
 * Distinct fecha_valor across the asset-class views (one per published period).
 * Returned as YYYY-MM-DD strings, latest first.
 *
 * Reads from v_asset_class_dates_sd (DISTINCT fecha_valor over sp_fila cuadro
 * 1+2), which is the cheap way to list periods without scanning the full
 * afp × tipo_fondo × category view.
 */
export async function getAssetAllocationDates(): Promise<string[]> {
  const data = await query<{ fecha_valor: unknown }>(
    `SELECT fecha_valor FROM ${MART}.v_asset_class_dates_sd
     WHERE fecha_valor >= DATE '2025-01-01'
     ORDER BY fecha_valor DESC`,
  );
  return data.map((r) => toDateStr(r.fecha_valor));
}

export async function getAssetClassByAfp(
  fecha: string,
): Promise<AssetClassByAfpRow[]> {
  // The view is afp × tipo_fondo × category. For Sec 02 cut by AFP we want
  // the all-funds (tipo_fondo='TOTAL') aggregate per AFP.
  const data = await query<{
    afp_nombre: string;
    pdf_category: string;
    pdf_order: unknown;
    monto_dolares: unknown;
    porcentaje: unknown;
  }>(
    `SELECT afp_nombre, pdf_category, pdf_order, monto_dolares, porcentaje
     FROM ${MART}.v_asset_class_afp_sd
     WHERE fecha_valor = DATE(@fecha) AND tipo_fondo = @tipo_fondo`,
    { fecha, tipo_fondo: 'TOTAL' },
  );
  return data.map((r) => ({
    afp: r.afp_nombre as string,
    pdf_category: r.pdf_category as string,
    pdf_order: toNum(r.pdf_order),
    monto_dolares: r.monto_dolares != null ? toNum(r.monto_dolares) : null,
    // SP exposes porcentaje on a 0-100 scale; we normalize to 0..1 here so
    // formatters (fmtPct) can treat it like every other share in the app.
    porcentaje: r.porcentaje != null ? toNum(r.porcentaje) / 100 : null,
  }));
}

export async function getAssetClassByTipo(
  fecha: string,
): Promise<AssetClassByTipoRow[]> {
  const data = await query<{
    tipo_fondo: string;
    pdf_category: string;
    pdf_order: unknown;
    monto_dolares: unknown;
    porcentaje: unknown;
  }>(
    `SELECT tipo_fondo, pdf_category, pdf_order, monto_dolares, porcentaje
     FROM ${MART}.v_asset_class_tipo_sd
     WHERE fecha_valor = DATE(@fecha)`,
    { fecha },
  );
  return data.map((r) => ({
    tipo_fondo: r.tipo_fondo as string,
    pdf_category: r.pdf_category as string,
    pdf_order: toNum(r.pdf_order),
    monto_dolares: r.monto_dolares != null ? toNum(r.monto_dolares) : null,
    porcentaje: r.porcentaje != null ? toNum(r.porcentaje) / 100 : null,
  }));
}

/**
 * Local Fixed Income breakdown by AFP × PDF bucket (Sec 02 page 2),
 * sourced from SP XML Cuadro 2 — same period as the main matrix, no lag.
 */
export async function getLocalFiByAfp(fecha: string): Promise<LocalFiRow[]> {
  const data = await query<{
    afp: string;
    fecha_reporte: unknown;
    pdf_bucket: string;
    pdf_order: unknown;
    monto_usd_mm: unknown;
  }>(
    `SELECT afp, fecha_reporte, pdf_bucket, pdf_order, monto_usd_mm
     FROM ${MART}.v_local_fi_by_afp_sd
     WHERE fecha_reporte = DATE(@fecha)`,
    { fecha },
  );
  return data.map((r) => ({
    afp: r.afp as string,
    fecha_reporte: toDateStr(r.fecha_reporte),
    pdf_bucket: r.pdf_bucket as string,
    pdf_order: toNum(r.pdf_order),
    monto_usd_mm: toNum(r.monto_usd_mm) || 0,
  }));
}

/**
 * Monthly evolution of asset class allocation per tipo_fondo (A-E + TOTAL).
 * Sourced from v_asset_class_tipo_sd (SP XML) — covers all months we've synced.
 * Returned ordered by fecha asc, then pdf_order asc.
 */
export async function getAssetClassEvolution(): Promise<
  AssetClassEvolutionRow[]
> {
  const data = await query<{
    fecha_valor: unknown;
    tipo_fondo: string;
    pdf_category: string;
    pdf_order: unknown;
    monto_dolares: unknown;
  }>(
    `SELECT fecha_valor, tipo_fondo, pdf_category, pdf_order, monto_dolares
     FROM ${MART}.v_asset_class_tipo_sd
     ORDER BY fecha_valor ASC, pdf_order ASC`,
  );
  const rows: AssetClassEvolutionRow[] = [];
  for (const r of data) {
    if (r.monto_dolares == null) continue;
    rows.push({
      fecha: toDateStr(r.fecha_valor),
      tipo_fondo: r.tipo_fondo as string,
      pdf_category: r.pdf_category as string,
      pdf_order: toNum(r.pdf_order),
      monto_dolares: toNumOrNull(r.monto_dolares) ?? 0,
    });
  }
  return rows;
}

/**
 * Monthly evolution of asset allocation per AFP (all-funds, tipo_fondo='TOTAL'),
 * including afp='TOTAL' = system. Feeds the AFP selector on the over-time chart.
 */
export async function getAssetClassEvolutionByAfp(): Promise<
  AssetClassEvolutionByAfpRow[]
> {
  const data = await query<{
    fecha_valor: unknown;
    afp_nombre: string;
    pdf_category: string;
    monto_dolares: unknown;
  }>(
    `SELECT fecha_valor, afp_nombre, pdf_category, monto_dolares
     FROM ${MART}.v_asset_class_afp_sd
     WHERE tipo_fondo = @tipo_fondo
     ORDER BY fecha_valor ASC`,
    { tipo_fondo: 'TOTAL' },
  );
  const rows: AssetClassEvolutionByAfpRow[] = [];
  for (const r of data) {
    if (r.monto_dolares == null) continue;
    rows.push({
      fecha: toDateStr(r.fecha_valor),
      afp: r.afp_nombre as string,
      pdf_category: r.pdf_category as string,
      monto_dolares: toNumOrNull(r.monto_dolares) ?? 0,
    });
  }
  return rows;
}

export type {
  AssetClassByAfpRow,
  AssetClassByTipoRow,
  AssetClassEvolutionRow,
  AssetClassEvolutionByAfpRow,
  LocalFiRow,
} from './types-asset-allocation';
export {
  AFPS_AC,
  TIPO_FONDOS_AC,
  AC_CATEGORIES,
  AC_OWUW_CATEGORIES,
  AC_SUBTOTALS,
  LOCAL_FI_BUCKETS,
  pivotByCategory,
} from './types-asset-allocation';
