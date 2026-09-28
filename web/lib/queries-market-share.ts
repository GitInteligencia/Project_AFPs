// Fuente: BigQuery (antes Supabase/PostgREST)
import { MART, query, toDateStr, toDateStrOrNull, toNum, toNumOrNull } from './db';
import type {
  AumRow,
  ContributorsRow,
  CuotaPoint,
  FlowsRow,
  ReturnsRow,
} from './types-market-share';

/**
 * Distinct dates in v_returns_afp_tipo (one per month, latest first).
 * Range covers 2020-01 to most recent month-end of valor_cuota_patrimonio.
 */
export async function getMarketShareDates(): Promise<string[]> {
  const data = await query<{ fecha: unknown }>(
    `SELECT fecha FROM ${MART}.v_returns_afp_tipo
     WHERE fecha >= DATE '2025-01-01'
     ORDER BY fecha DESC
     -- 7 AFPs × 6 tipo_fondo = 42 rows per fecha. 100 months × 42 = 4200.
     LIMIT 5000`,
  );
  return Array.from(new Set(data.map((r) => toDateStr(r.fecha))));
}

export async function getAumByAfpTipo(fecha: string): Promise<AumRow[]> {
  const data = await query<{
    afp: string;
    tipo_fondo: string;
    aum_usd_mm: unknown;
    aum_clp_bn: unknown;
  }>(
    `SELECT afp, tipo_fondo, aum_usd_mm, aum_clp_bn
     FROM ${MART}.v_returns_afp_tipo
     WHERE fecha = DATE(@fecha)`,
    { fecha },
  );
  return data.map((r) => ({
    afp: r.afp as string,
    tipo_fondo: r.tipo_fondo as string,
    aum_usd_mm: toNum(r.aum_usd_mm) || 0,
    aum_clp_bn: toNum(r.aum_clp_bn) || 0,
  }));
}

export async function getReturnsByAfpTipo(fecha: string): Promise<ReturnsRow[]> {
  const data = await query<{
    afp: string;
    tipo_fondo: string;
    ret_mom_clp: unknown;
    ret_ytd_clp: unknown;
    ret_ltm_clp: unknown;
    ret_mom_usd: unknown;
    ret_ytd_usd: unknown;
    ret_ltm_usd: unknown;
  }>(
    `SELECT afp, tipo_fondo, ret_mom_clp, ret_ytd_clp, ret_ltm_clp,
            ret_mom_usd, ret_ytd_usd, ret_ltm_usd
     FROM ${MART}.v_returns_afp_tipo
     WHERE fecha = DATE(@fecha)`,
    { fecha },
  );
  return data.map((r) => ({
    afp: r.afp as string,
    tipo_fondo: r.tipo_fondo as string,
    ret_mom_clp: r.ret_mom_clp != null ? toNumOrNull(r.ret_mom_clp) : null,
    ret_ytd_clp: r.ret_ytd_clp != null ? toNumOrNull(r.ret_ytd_clp) : null,
    ret_ltm_clp: r.ret_ltm_clp != null ? toNumOrNull(r.ret_ltm_clp) : null,
    ret_mom_usd: r.ret_mom_usd != null ? toNumOrNull(r.ret_mom_usd) : null,
    ret_ytd_usd: r.ret_ytd_usd != null ? toNumOrNull(r.ret_ytd_usd) : null,
    ret_ltm_usd: r.ret_ltm_usd != null ? toNumOrNull(r.ret_ltm_usd) : null,
  }));
}

/**
 * Month-end cuota + FX per AFP × tipo_fondo across the available window. Small
 * (~7 afp × 6 tipo × months). Feeds the custom date-range return on the Returns
 * table — returns for any two month-ends are computed client-side from this.
 */
export async function getCuotaSeries(): Promise<CuotaPoint[]> {
  const data = await query<{
    fecha: unknown;
    afp: string;
    tipo_fondo: string;
    valor_cuota: unknown;
    fx_clp_per_usd: unknown;
  }>(
    `SELECT fecha, afp, tipo_fondo, valor_cuota, fx_clp_per_usd
     FROM ${MART}.v_returns_afp_tipo
     WHERE fecha >= DATE '2025-01-01'
     ORDER BY fecha ASC`,
  );
  return data.map((r) => ({
    fecha: toDateStr(r.fecha),
    afp: r.afp as string,
    tipo_fondo: r.tipo_fondo as string,
    valor_cuota: r.valor_cuota != null ? toNumOrNull(r.valor_cuota) : null,
    fx_clp_per_usd:
      r.fx_clp_per_usd != null ? toNumOrNull(r.fx_clp_per_usd) : null,
  }));
}

export async function getFlowsByAfpTipo(fecha: string): Promise<FlowsRow[]> {
  const data = await query<{
    afp: string;
    tipo_fondo: string;
    flow_mom_usd_mm: unknown;
    flow_ytd_usd_mm: unknown;
    flow_ltm_usd_mm: unknown;
  }>(
    `SELECT afp, tipo_fondo, flow_mom_usd_mm, flow_ytd_usd_mm, flow_ltm_usd_mm
     FROM ${MART}.v_returns_afp_tipo
     WHERE fecha = DATE(@fecha)`,
    { fecha },
  );
  return data.map((r) => ({
    afp: r.afp as string,
    tipo_fondo: r.tipo_fondo as string,
    flow_mom_usd_mm:
      r.flow_mom_usd_mm != null ? toNumOrNull(r.flow_mom_usd_mm) : null,
    flow_ytd_usd_mm:
      r.flow_ytd_usd_mm != null ? toNumOrNull(r.flow_ytd_usd_mm) : null,
    flow_ltm_usd_mm:
      r.flow_ltm_usd_mm != null ? toNumOrNull(r.flow_ltm_usd_mm) : null,
  }));
}

export async function getContributorsByAfp(
  fecha: string,
): Promise<ContributorsRow[]> {
  const data = await query<{
    afp: string;
    fecha_cotizantes: unknown;
    aum_usd_mm: unknown;
    n_cotizantes: unknown;
    avg_usd_per_cotiz: unknown;
    share_aum: unknown;
    share_cotiz: unknown;
  }>(
    `SELECT afp, fecha_cotizantes, aum_usd_mm, n_cotizantes, avg_usd_per_cotiz,
            share_aum, share_cotiz
     FROM ${MART}.v_contributors_market_share
     WHERE fecha_reporte = DATE(@fecha)`,
    { fecha },
  );
  return data.map((r) => ({
    afp: r.afp as string,
    fecha_cotizantes: toDateStrOrNull(r.fecha_cotizantes),
    aum_usd_mm: toNum(r.aum_usd_mm) || 0,
    n_cotizantes: r.n_cotizantes != null ? toNumOrNull(r.n_cotizantes) : null,
    avg_usd_per_cotiz:
      r.avg_usd_per_cotiz != null ? toNumOrNull(r.avg_usd_per_cotiz) : null,
    share_aum: r.share_aum != null ? toNumOrNull(r.share_aum) : null,
    share_cotiz: r.share_cotiz != null ? toNumOrNull(r.share_cotiz) : null,
  }));
}

// Re-export types and helper for convenience.
export type {
  AumRow,
  ContributorsRow,
  FlowsRow,
  ReturnsRow,
} from './types-market-share';
export {
  pivotByAfp,
  AFPS_RETURN,
  AFP_COLOR,
  TIPO_FONDOS,
} from './types-market-share';
export type { AfpReturn, TipoFondo } from './types-market-share';
