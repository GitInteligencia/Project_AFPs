// Fuente: BigQuery (antes Supabase/PostgREST)
import { MART, query, toDateStr, toNum } from './db';

export type LatamMonthPoint = {
  fecha_reporte: string; // YYYY-MM-DD
  eq_active: number;
  eq_etf: number;
  eq_passive: number;
  eq_di: number;
  fi_funds: number;
  fi_di: number;
  total_foreign: number;
};

/**
 * Sec 07 pág 9 "Latam Evolution" series. One row per fecha_reporte with the
 * Equity / FI / Direct-Investment USD MM splits the PDF charts plot, plus
 * Total Foreign for the % charts. All in USD MM at USDCLP Curncy.
 */
export async function getLatamEvolution(): Promise<LatamMonthPoint[]> {
  const [latamRows, totalRows] = await Promise.all([
    query<{
      fecha_reporte: unknown;
      pdf_bucket: string;
      style_group: string;
      monto_usd_mm: unknown;
    }>(
      `SELECT fecha_reporte, pdf_bucket, style_group, monto_usd_mm
       FROM ${MART}.mv_foreign_latam_monthly
       ORDER BY fecha_reporte ASC`,
    ),
    query<{ fecha_reporte: unknown; monto_usd_mm: unknown }>(
      `SELECT fecha_reporte, monto_usd_mm
       FROM ${MART}.v_foreign_pdf_summary_combined
       ORDER BY fecha_reporte ASC
       LIMIT 5000`,
    ),
  ]);

  const byFecha = new Map<string, LatamMonthPoint>();
  function point(fecha: string): LatamMonthPoint {
    let p = byFecha.get(fecha);
    if (!p) {
      p = {
        fecha_reporte: fecha,
        eq_active: 0,
        eq_etf: 0,
        eq_passive: 0,
        eq_di: 0,
        fi_funds: 0,
        fi_di: 0,
        total_foreign: 0,
      };
      byFecha.set(fecha, p);
    }
    return p;
  }

  for (const r of latamRows) {
    const fecha = toDateStr(r.fecha_reporte);
    const bucket = r.pdf_bucket as string;
    const style = r.style_group as string;
    const usd = toNum(r.monto_usd_mm) || 0;
    const p = point(fecha);
    if (bucket === 'Equity') {
      if (style === 'Active') p.eq_active += usd;
      else if (style === 'ETF') p.eq_etf += usd;
      else if (style === 'Passive') p.eq_passive += usd;
    } else if (bucket === 'Fixed Income') {
      p.fi_funds += usd;
    } else if (bucket === 'Direct Investment') {
      // PDF page 9 splits DI into FI side only (Sovereign/Bank/Corp are FI).
      // Tiny Equity DI (~$52 MM, see pág 6) we lump into eq_di for symmetry.
      // We don't have an Eq-vs-FI flag inside Direct Investment at this view
      // level, so default to fi_di (dominant) and refine later if needed.
      p.fi_di += usd;
    }
  }

  for (const r of totalRows) {
    const fecha = toDateStr(r.fecha_reporte);
    const p = point(fecha);
    p.total_foreign += toNum(r.monto_usd_mm) || 0;
  }

  return Array.from(byFecha.values()).sort((a, b) =>
    a.fecha_reporte.localeCompare(b.fecha_reporte),
  );
}
