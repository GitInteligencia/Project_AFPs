// Fuente: BigQuery (antes Supabase/PostgREST)
import { MART, RAW, query, queryOne, toDateStrOrNull, toNum } from './db';
import type {
  Sec05SizeRow,
  Sec05IpsaMembershipRow,
  Sec05ConcentrationRow,
  Sec05Top40Row,
} from './types-sec05';

// Sec05 sobre SQL vivo (2026-07-01): Pionero/MRV desde ipd_cartera_eom
// (TBL_IPA_V2 type=2), índices desde ipd_bms_membership (TBL_BMS_Exposicion),
// AFPs desde v_chilean_stocks_gics (CHIST). Sin seeds JSON.
//
// Las 4 RPC de Supabase (f_sec05_*) son table functions en afp_mart con los
// mismos nombres de parámetro (p_fecha).

// Per-source resolved fechas for a given target. Used to render per-column
// dates in card headers so the user understands exactly what they're seeing.
export type Sec05ResolvedFechas = {
  pionero: string | null;
  mrv: string | null;
  ipsa: string | null;
  afps: string | null;
};

export async function getSec05ResolvedFechas(
  targetFecha: string,
): Promise<Sec05ResolvedFechas> {
  const [pionero, mrv, ipsa, afps] = await Promise.all([
    queryOne<{ fecha: unknown }>(
      `SELECT fecha FROM ${RAW}.ipd_cartera_eom
       WHERE id_fund = @id_fund AND fecha <= DATE(@fecha)
       ORDER BY fecha DESC
       LIMIT 1`,
      { id_fund: 33, fecha: targetFecha },
    ),
    queryOne<{ fecha: unknown }>(
      `SELECT fecha FROM ${RAW}.ipd_cartera_eom
       WHERE id_fund = @id_fund AND fecha <= DATE(@fecha)
       ORDER BY fecha DESC
       LIMIT 1`,
      { id_fund: 19, fecha: targetFecha },
    ),
    queryOne<{ fecha: unknown }>(
      `SELECT fecha FROM ${RAW}.ipd_bms_membership
       WHERE fecha <= DATE(@fecha)
       ORDER BY fecha DESC
       LIMIT 1`,
      { fecha: targetFecha },
    ),
    queryOne<{ fecha_reporte: unknown }>(
      `SELECT fecha_reporte FROM ${MART}.v_chilean_stocks_gics
       WHERE fecha_reporte <= DATE(@fecha)
       ORDER BY fecha_reporte DESC
       LIMIT 1`,
      { fecha: targetFecha },
    ),
  ]);
  return {
    pionero: toDateStrOrNull(pionero?.fecha),
    mrv: toDateStrOrNull(mrv?.fecha),
    ipsa: toDateStrOrNull(ipsa?.fecha),
    afps: toDateStrOrNull(afps?.fecha_reporte),
  };
}

export async function getSec05SizeBreakdown(
  fecha: string,
): Promise<Sec05SizeRow[]> {
  const data = await query<Record<string, unknown>>(
    `SELECT * FROM ${MART}.f_sec05_size(DATE(@p_fecha))`,
    { p_fecha: fecha },
  );
  return data.map((r) => ({
    bucket: r.bucket as Sec05SizeRow['bucket'],
    pionero_pct: toNum(r.pionero_pct) || 0,
    mrv_pct: toNum(r.mrv_pct) || 0,
    ipsa_pct: toNum(r.ipsa_pct) || 0,
    afps_pct: toNum(r.afps_pct) || 0,
  }));
}

export async function getSec05IpsaMembership(
  fecha: string,
): Promise<Sec05IpsaMembershipRow[]> {
  const data = await query<Record<string, unknown>>(
    `SELECT * FROM ${MART}.f_sec05_ipsa_membership(DATE(@p_fecha))`,
    { p_fecha: fecha },
  );
  return data.map((r) => ({
    bucket: r.bucket as Sec05IpsaMembershipRow['bucket'],
    pionero_pct: toNum(r.pionero_pct) || 0,
    mrv_pct: toNum(r.mrv_pct) || 0,
    ipsa_pct: toNum(r.ipsa_pct) || 0,
    afps_pct: toNum(r.afps_pct) || 0,
  }));
}

export async function getSec05Concentration(
  fecha: string,
): Promise<Sec05ConcentrationRow[]> {
  const data = await query<Record<string, unknown>>(
    `SELECT * FROM ${MART}.f_sec05_concentration(DATE(@p_fecha))`,
    { p_fecha: fecha },
  );
  return data.map((r) => ({
    metric: r.metric as Sec05ConcentrationRow['metric'],
    pionero: toNum(r.pionero) || 0,
    mrv: toNum(r.mrv) || 0,
    ipsa: toNum(r.ipsa) || 0,
    afps: toNum(r.afps) || 0,
  }));
}

export async function getSec05Top40(
  fecha: string,
): Promise<Sec05Top40Row[]> {
  const data = await query<Record<string, unknown>>(
    `SELECT * FROM ${MART}.f_sec05_top40(DATE(@p_fecha))`,
    { p_fecha: fecha },
  );
  return data.map((r) => ({
    rk: toNum(r.rk) || 0,
    nemo: r.nemo as string,
    emisor: (r.emisor as string | null) ?? null,
    company_name: (r.company_name as string | null) ?? null,
    group_name: (r.group_name as string | null) ?? null,
    size_bucket: (r.size_bucket as Sec05Top40Row['size_bucket']) ?? null,
    gics_name: (r.gics_name as string | null) ?? null,
    gics_chist: (r.gics_chist as string | null) ?? null,
    monto_usd_mm: toNum(r.monto_usd_mm) || 0,
    weight: toNum(r.weight) || 0,
  }));
}
