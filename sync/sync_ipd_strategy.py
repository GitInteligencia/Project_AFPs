"""
Sync 4.1/4.2 Strategy: SQL Server Inteligencia_Producto (prod) -> BigQuery.

Destino (2026-09, migracion GCP): tablas ipd_* en afp_raw via sync/bq_io.py
(load WRITE_TRUNCATE = full reload), ADC. Antes: Supabase REST.

Opcion D (2026-07-01): el diario NUNCA toca el destino. Este script:
  1. Lee TBL_IPA_V2 diaria deduplicada (FechaReporte = FechaCartera) para los 7
     fondos Moneda de estrategia vivos: 13 MDLAT, 17 MLDL, 28 MSC, 34 MLE,
     52 MSCLUX, 59 MLATHY, 68 MLCC (Geneva).
  2. Calcula atribucion diaria en pandas y sube solo el agregado MENSUAL:
       contrib_total    = w(t-1) * r_unit(t)   con r_unit = retorno del valor
                          unitario USD (TotalMVal / (Qty*Factor)): precio + FX
                          + devengo, robusto a compras/ventas intradia y a
                          paydowns de bonos amortizables (Factor).
       contrib_price    = w(t-1) * r_LocalPrice(t)  (precio limpio, moneda local)
       contrib_fx_carry = total - price
     Derivados (Source='DERIVADOS'): contrib_total = dMTM/NAV(t-1) (unit value
     no tiene sentido cuando el MTM cruza cero); price=0.
     Lineas sin precio (LocalPrice=1 ambos dias: cash, receivables/payables,
     margenes) y Source='CASH APPRAISAL': contribuyen 0 — sus cambios de MVal
     son flujos, no P&L (validado: sin esta regla meten +-80 bps/dia falsos).
     Instrumentos que aparecen/desaparecen contribuyen 0 ese dia (el flujo lo
     captura la linea de cash en la valorizacion siguiente).

     Lo que la atribucion por posiciones NO captura (dividendos y cupones
     cobrados aterrizan en caja) va a la fila residual del fondo-mes:
       residual = ret_serie (MTD oficial de TBL_RENTABILIDADES_SERIES, USD)
                  - ret_month (suma de contribuciones)
     La UI muestra el residual como "Income / cash & other" para que el total
     cuadre con el retorno oficial.
  3. Sube la cartera de fin de mes (ultima FechaCartera disponible del mes).
     Incluye PIONERO (33) y MRV (19) solo-cartera para Sec05 Chilean Stocks,
     con investment_type_code (2 = equity) desde BD_INSTRUMENTOS.
  4. Sube TBL_RENTABILIDADES_SERIES parseada (solo fondos estrategia) para 4.2.
  5. Sube la composicion de los indices S&P (TBL_BMS_Exposicion: IGPA 16,
     IGPAL 17, IGPAM 18, IGPAS 19, IPSA 20; EOM + ultima fecha) a
     ipd_bms_membership — reemplaza los seeds dim_ipsa_composition /
     dim_benchmark_composition y da la clasificacion por SIZE de Sec05.

Metodologia validada contra el piloto TBL_PERFORMANCE_ATTRIBUTION (MSCLUX
2025-01-15: pesos identicos a 3 decimales, contribucion +-0.3-0.8 bps).

Destino (BigQuery afp_raw): ipd_cartera_eom, ipd_attribution_monthly,
ipd_attribution_fund_month, ipd_rentabilidades, ipd_bms_membership. Full reload
(load WRITE_TRUNCATE; antes DELETE + INSERT).

Usage:
    python sync/sync_ipd_strategy.py
"""

import os
import sys
import urllib.parse
from time import time

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bq_io import bq_replace, connect_bigquery  # noqa: E402

load_dotenv()

# fondos de estrategia (posiciones/atribucion). RENT usa ademas 55 (MLCC LX) y 60.
FUNDS = {13: 'MDLAT', 17: 'MLDL', 28: 'MSC', 34: 'MLE',
         52: 'MSCLUX', 59: 'MLATHY', 68: 'MLCC'}
# Sec05 Chilean Stocks: solo cartera EOM (sin atribucion)
CARTERA_ONLY_FUNDS = {33: 'PIONERO', 19: 'MRV'}
RENT_FUNDS = [13, 17, 28, 34, 52, 55, 59, 60]
# retornos oficiales de serie: MLCC tiene posiciones en 68 (Geneva) pero cuota en 55 (LX)
RENT_MAP = {68: 55}
# indices S&P para Sec05: composicion + pesos (EOM + ultima fecha disponible)
BMS_IDS = {16: 'IGPA', 17: 'IGPAL', 18: 'IGPAM', 19: 'IGPAS', 20: 'IPSA'}

# retornos unitarios diarios fuera de este rango se tratan como suciedad de
# precio/carga y contribuyen 0 (evita que un dato malo domine el mes)
MAX_ABS_DAILY_RET = 0.60
# snapshots parciales: fecha descartada si su NAV se desvia de la mediana movil
# local (ventana centrada) fuera de este rango. Outlier LOCAL, no cadena: los
# shifts permanentes legitimos (traspaso MDLAT<->MLATHY nov-2024, /3.5 y x5.3)
# deben sobrevivir; una carga parcial es un pozo de 1-2 dias.
NAV_RATIO_RANGE = (0.4, 2.5)
NAV_MEDIAN_WINDOW = 11
# backstop: un fondo no se mueve mas de esto en un dia; si pasa, el dia es
# suciedad y sus contribuciones se anulan
MAX_ABS_FUND_DAILY = 0.15


# =============================================================
# CONEXIONES
# =============================================================

def connect_sqlserver():
    odbc = (
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER={os.getenv('DB_SERVER')};DATABASE=Inteligencia_Producto;"
        "UID=ccampos;PWD=Patria2024####;"
        "Encrypt=optional;TrustServerCertificate=yes"
    )
    return create_engine(
        f"mssql+pyodbc:///?odbc_connect={urllib.parse.quote_plus(odbc)}",
        connect_args={'timeout': 60},
    )


def connect_supabase():
    """Wrapper de compatibilidad: devuelve un bigquery.Client (ADC)."""
    return connect_bigquery()


def supabase_replace(sb, table, df, pk_col, batch_size=500):
    """Full reload: load WRITE_TRUNCATE (antes DELETE all + INSERT por lotes).
    pk_col/batch_size se conservan por firma; bq_replace los ignora."""
    return bq_replace(sb, table, df, pk_col)


# =============================================================
# EXTRACCION SQL SERVER
# =============================================================

def read_positions(ms):
    ids = ','.join(str(k) for k in {**FUNDS, **CARTERA_ONLY_FUNDS})
    print("  leyendo TBL_IPA_V2 (dedupe FechaReporte=FechaCartera)...", flush=True)
    t0 = time()
    df = pd.read_sql(f"""
        SELECT v.ID_Fund       AS id_fund,
               v.FechaCartera  AS fecha,
               v.ID_Instrumento AS id_instrumento,
               v.Source        AS source,
               m.Code          AS currency,
               v.LocalPrice    AS local_price,
               v.Qty           AS qty,
               v.Factor        AS factor,
               v.TotalMVal     AS mval
        FROM dbo.TBL_IPA_V2 v
        LEFT JOIN dbo.BD_Monedas m ON m.id_CURR = v.id_CURR
        WHERE v.ID_Fund IN ({ids}) AND v.FechaReporte = v.FechaCartera
    """, ms)
    print(f"  ({len(df):,} filas en {time() - t0:.0f}s)")
    df['fecha'] = pd.to_datetime(df['fecha'])
    # consolidar posibles filas repetidas del mismo instrumento/fuente
    # qty efectiva para bonos amortizables: Qty * Factor (paydown no es P&L)
    df['factor'] = df['factor'].replace(0, np.nan).fillna(1.0)
    df['qty_eff'] = df['qty'] * df['factor']
    df = (df.groupby(['id_fund', 'fecha', 'id_instrumento', 'source'], as_index=False)
            .agg(currency=('currency', 'first'), local_price=('local_price', 'mean'),
                 qty=('qty', 'sum'), qty_eff=('qty_eff', 'sum'), mval=('mval', 'sum')))
    return df


def read_instrument_names(ms, instrument_ids):
    ids = ','.join(str(int(i)) for i in instrument_ids)
    df = pd.read_sql(f"""
        SELECT ID_Instrumento AS id_instrumento,
               Name_Instrumento AS instrumento,
               CompanyName AS company,
               Investment_Type_Code AS investment_type_code
        FROM dbo.BD_INSTRUMENTOS
        WHERE ID_Instrumento IN ({ids})
    """, ms)
    df['investment_type_code'] = pd.to_numeric(
        df['investment_type_code'], errors='coerce').astype('Int64')
    return df.drop_duplicates('id_instrumento')


def read_bms_membership(ms):
    """Constituyentes de los indices S&P (Sec05): fin de mes + ultima fecha disponible.
    weight = TotalMVal / total del indice en la fecha."""
    ids = ','.join(str(k) for k in BMS_IDS)
    df = pd.read_sql(f"""
        WITH fechas AS (
          SELECT FechaCartera f,
                 ROW_NUMBER() OVER (PARTITION BY LEFT(FechaCartera,7) ORDER BY FechaCartera DESC) rn
          FROM (SELECT DISTINCT FechaCartera FROM dbo.TBL_BMS_Exposicion WHERE ID_BM IN ({ids})) x
        )
        SELECT x.FechaCartera AS fecha, x.ID_BM AS id_bm, x.ID_Instrumento AS id_instrumento,
               i.Name_Instrumento AS ticker, i.CompanyName AS company,
               x.TotalMVal AS mval
        FROM dbo.TBL_BMS_Exposicion x
        LEFT JOIN dbo.BD_INSTRUMENTOS i ON i.ID_Instrumento = x.ID_Instrumento
        WHERE x.ID_BM IN ({ids})
          AND x.FechaCartera IN (SELECT f FROM fechas WHERE rn = 1)
    """, ms)
    df = (df.groupby(['fecha', 'id_bm', 'id_instrumento'], as_index=False)
            .agg(ticker=('ticker', 'first'), company=('company', 'first'),
                 mval=('mval', 'sum')))
    tot = df.groupby(['fecha', 'id_bm'])['mval'].transform('sum')
    df['weight'] = df['mval'] / tot
    return df.drop(columns=['mval'])


def read_rentabilidades(ms):
    ids = "','".join(str(i) for i in RENT_FUNDS)
    df = pd.read_sql(f"""
        SELECT Agrupacion, Quiebre AS quiebre, Currency AS currency,
               Fecha AS fecha, Fecha_Data AS fecha_data,
               Valor_Cuota AS valor_cuota, Patrimonio AS patrimonio,
               DTD AS dtd, MTD AS mtd, YTD AS ytd, ITD AS itd,
               [1Y] AS y1, [2Y] AS y2, [3Y] AS y3, [5Y] AS y5,
               alpha1Y AS alpha_1y, beta1Y AS beta_1y,
               sharperatio_1Y AS sharpe_1y, tracking_error1Y AS te_1y,
               info_ratio1Y AS ir_1y
        FROM dbo.TBL_RENTABILIDADES_SERIES
        WHERE LEFT(Agrupacion, CHARINDEX('-', Agrupacion) - 1) IN ('{ids}')
    """, ms)
    # Agrupacion = '<id_fund>-<id_serie>-<bm_ticker>-<currency>' (ticker sin '-')
    parts = df.pop('Agrupacion').str.split('-')
    df.insert(0, 'id_fund', parts.str[0].astype(int))
    df.insert(1, 'id_serie', parts.str[1].astype(int))
    df.insert(2, 'bm_ticker', parts.str[2:-1].str.join('-'))
    return df


# =============================================================
# ATRIBUCION
# =============================================================

def drop_partial_snapshots(pos):
    """Descarta fechas cuyo NAV es outlier vs la mediana movil local (carga
    parcial). Una carga a medias rompe pesos, dMTM de derivados y la cartera
    EOM; un shift de nivel permanente (p.ej. traspaso entre vehiculos) NO se
    descarta porque la mediana local lo acompana."""
    keep_frames = []
    for id_fund, g in pos.groupby('id_fund'):
        nav = g.groupby('fecha')['mval'].sum().sort_index()
        med = nav.rolling(NAV_MEDIAN_WINDOW, center=True, min_periods=3).median()
        ratio = nav / med
        ok = (nav > 0) & ratio.between(*NAV_RATIO_RANGE)
        n_drop = int((~ok).sum())
        if n_drop:
            print(f"    [warn] fondo {id_fund}: {n_drop} fechas descartadas "
                  f"por NAV outlier local (carga parcial)")
        keep_frames.append(g[g['fecha'].isin(nav.index[ok])])
    return pd.concat(keep_frames, ignore_index=True)


def compute_attribution(pos):
    """Contribuciones diarias por instrumento -> agregado mensual + retorno del fondo."""
    attr_frames, fund_frames = [], []

    for id_fund, g in pos.groupby('id_fund'):
        g = g.sort_values('fecha')
        nav = g.groupby('fecha')['mval'].sum()
        fechas = nav.index.sort_values()
        prev_map = dict(zip(fechas[1:], fechas[:-1]))

        cur = g[g['fecha'].isin(prev_map)].copy()
        cur['fecha_prev'] = cur['fecha'].map(prev_map)
        prev = g.rename(columns={
            'fecha': 'fecha_prev', 'local_price': 'lp_prev', 'qty': 'qty_prev',
            'qty_eff': 'qty_eff_prev', 'mval': 'mval_prev'})[
            ['fecha_prev', 'id_instrumento', 'source', 'lp_prev', 'qty_prev',
             'qty_eff_prev', 'mval_prev']]
        m = cur.merge(prev, on=['fecha_prev', 'id_instrumento', 'source'], how='inner')
        m['nav_prev'] = m['fecha_prev'].map(nav)
        m = m[m['nav_prev'].abs() > 0]
        m['w_prev'] = m['mval_prev'] / m['nav_prev']

        # retorno unitario USD (precio + FX + devengo), por face efectivo (Qty*Factor)
        with np.errstate(divide='ignore', invalid='ignore'):
            u1 = np.where(m['qty_eff'] != 0, m['mval'] / m['qty_eff'], np.nan)
            u0 = np.where(m['qty_eff_prev'] != 0, m['mval_prev'] / m['qty_eff_prev'], np.nan)
            r_unit = u1 / u0 - 1
            r_price = np.where((m['lp_prev'] > 0) & (m['local_price'] > 0),
                               m['local_price'] / m['lp_prev'] - 1, np.nan)
        n_clip = int(np.nansum(np.abs(r_unit) > MAX_ABS_DAILY_RET))
        if n_clip:
            print(f"    [warn] fondo {id_fund}: {n_clip} retornos diarios "
                  f"|r|>{MAX_ABS_DAILY_RET:.0%} descartados (suciedad de precio)")
        r_unit = np.where(np.abs(r_unit) > MAX_ABS_DAILY_RET, np.nan, r_unit)
        r_price = np.where(np.abs(r_price) > MAX_ABS_DAILY_RET, np.nan, r_price)

        is_deriv = m['source'].eq('DERIVADOS').to_numpy()
        # lineas sin precio (cash / receivables / payables / margenes): sus cambios
        # de MVal son flujos, no P&L -> contribucion 0 (el income real va al residual)
        is_priceless = (m['source'].eq('CASH APPRAISAL')
                        | (m['lp_prev'].sub(1).abs().lt(1e-9)
                           & m['local_price'].sub(1).abs().lt(1e-9))
                        | m['local_price'].isna() | m['lp_prev'].isna()).to_numpy()
        contrib_total = np.where(
            is_deriv,
            (m['mval'] - m['mval_prev']) / m['nav_prev'],
            np.where(is_priceless, 0.0, m['w_prev'] * np.nan_to_num(r_unit)))
        contrib_price = np.where(is_deriv | is_priceless, 0.0,
                                 m['w_prev'] * np.nan_to_num(r_price))
        m['contrib_total'] = contrib_total
        m['contrib_price'] = contrib_price

        # backstop: dias con |retorno del fondo| imposible = suciedad -> contribs 0
        day_ret = m.groupby('fecha')['contrib_total'].transform('sum')
        bad_days = day_ret.abs() > MAX_ABS_FUND_DAILY
        if bad_days.any():
            nbad = m.loc[bad_days, 'fecha'].nunique()
            print(f"    [warn] fondo {id_fund}: {nbad} dias anulados por |ret diario|>{MAX_ABS_FUND_DAILY:.0%}")
            m.loc[bad_days, ['contrib_total', 'contrib_price']] = 0.0

        m['contrib_fx_carry'] = m['contrib_total'] - m['contrib_price']
        m['mes'] = m['fecha'].dt.to_period('M').dt.to_timestamp()

        agg = (m.groupby(['mes', 'id_instrumento'], as_index=False)
                 .agg(currency=('currency', 'last'),
                      avg_weight=('w_prev', 'mean'),
                      contrib_total=('contrib_total', 'sum'),
                      contrib_price=('contrib_price', 'sum'),
                      contrib_fx_carry=('contrib_fx_carry', 'sum'),
                      n_dias=('fecha', 'nunique')))
        agg.insert(0, 'id_fund', id_fund)
        attr_frames.append(agg)

        # retorno mensual del fondo = compuesto de los retornos diarios
        daily = m.groupby('fecha')['contrib_total'].sum()
        fund = pd.DataFrame({
            'mes': daily.index.to_period('M').to_timestamp(),
            'ret_d': daily.values})
        fund = fund.groupby('mes', as_index=False)['ret_d'].agg(
            lambda s: float(np.prod(1 + s) - 1))
        fund.columns = ['mes', 'ret_month']
        eom = nav.groupby(nav.index.to_period('M').to_timestamp()).last()
        fund['nav_eom'] = fund['mes'].map(eom)
        fund.insert(0, 'id_fund', id_fund)
        fund_frames.append(fund)

    return pd.concat(attr_frames, ignore_index=True), pd.concat(fund_frames, ignore_index=True)


def fund_serie_monthly(rent):
    """Retorno mensual oficial por fondo: MTD de la serie USD en la fecha EOM.
    (MDLAT id 13 solo tiene serie CLP -> queda sin ret_serie.)"""
    r = rent[(rent['quiebre'] == 'Serie') & (rent['currency'] == 'USD')].copy()
    r['fecha'] = pd.to_datetime(r['fecha'])
    r = r[r['fecha'].dt.is_month_end]
    r['mes'] = r['fecha'].dt.to_period('M').dt.to_timestamp()
    return (r.groupby(['id_fund', 'mes'], as_index=False)['mtd'].mean()
              .rename(columns={'mtd': 'ret_serie'}))


def build_cartera_eom(pos):
    """Ultima FechaCartera disponible de cada mes, por fondo."""
    pos = pos.copy()
    pos['mes'] = pos['fecha'].dt.to_period('M')
    last = pos.groupby(['id_fund', 'mes'])['fecha'].transform('max')
    eom = pos[pos['fecha'] == last].drop(columns=['mes'])
    nav = eom.groupby(['id_fund', 'fecha'])['mval'].transform('sum')
    eom['weight'] = eom['mval'] / nav
    return eom.rename(columns={'mval': 'mval_usd'})


# =============================================================
# MAIN
# =============================================================

def main():
    print("=" * 60)
    print("Sync 4.1/4.2 Strategy: Inteligencia_Producto -> BigQuery")
    print("=" * 60)
    ms = connect_sqlserver()
    sb = connect_supabase()
    t0 = time()

    pos = read_positions(ms)
    pos = drop_partial_snapshots(pos)
    names = read_instrument_names(ms, pos['id_instrumento'].unique())

    print("  calculando atribucion diaria -> mensual...")
    attr, fund_month = compute_attribution(pos[pos['id_fund'].isin(FUNDS)])
    cartera = build_cartera_eom(pos)  # incluye Pionero/MRV (solo cartera, Sec05)

    attr = attr.merge(names, on='id_instrumento', how='left')
    cartera = cartera.merge(names, on='id_instrumento', how='left')

    print("  leyendo TBL_RENTABILIDADES_SERIES...")
    rent = read_rentabilidades(ms)
    print("  leyendo TBL_BMS_Exposicion (indices S&P, Sec05)...")
    bms = read_bms_membership(ms)

    # reconciliacion contra el retorno oficial de la serie
    serie = fund_serie_monthly(rent)
    fund_month['rent_fund'] = fund_month['id_fund'].replace(RENT_MAP)
    fund_month = fund_month.merge(
        serie.rename(columns={'id_fund': 'rent_fund'}),
        on=['rent_fund', 'mes'], how='left').drop(columns=['rent_fund'])
    fund_month['residual'] = fund_month['ret_serie'] - fund_month['ret_month']

    # serializar fechas
    for df, cols in ((attr, ['mes']), (fund_month, ['mes']), (cartera, ['fecha'])):
        for c in cols:
            df[c] = pd.to_datetime(df[c]).dt.strftime('%Y-%m-%d')

    attr = attr[['id_fund', 'mes', 'id_instrumento', 'instrumento', 'company',
                 'currency', 'avg_weight', 'contrib_total', 'contrib_price',
                 'contrib_fx_carry', 'n_dias']]
    cartera = cartera[['id_fund', 'fecha', 'id_instrumento', 'instrumento', 'company',
                       'currency', 'source', 'investment_type_code',
                       'qty', 'local_price', 'mval_usd', 'weight']]

    print("\n  subiendo a BigQuery (full reload)...")
    supabase_replace(sb, 'ipd_attribution_monthly', attr, 'row_id')
    supabase_replace(sb, 'ipd_attribution_fund_month', fund_month, 'id_fund')
    supabase_replace(sb, 'ipd_cartera_eom', cartera, 'row_id')
    supabase_replace(sb, 'ipd_rentabilidades', rent, 'row_id')
    supabase_replace(sb, 'ipd_bms_membership', bms, 'row_id')

    print(f"\nTotal: {time() - t0:.0f}s")


if __name__ == '__main__':
    main()
