"""
Registro de los objetos a validar en paridad Supabase <-> BigQuery (PLAN_MIGRACION_GCP.md §1.2 y §12).

39 objetos leídos por la web (12 tablas, 23 vistas, 4 matviews) + las 4 RPC f_sec05_* con parámetros de ejemplo.
Lo usan validation/snapshot_supabase.py (baseline vía REST) y validation/compare_bq_vs_supabase.py.

Campos:
  kind      'table' | 'view' | 'mart' | 'function'
  dataset   dataset BigQuery ('raw' | 'dim' | 'mart') — la clave se resuelve con DATASETS de db/bigquery/apply.py
  date_col  columna de fecha por la que se corta (None = objeto sin dimensión temporal: se compara completo)
  keys      columnas que forman la clave de negocio por fecha (conjunto exacto según §12)
  params    (functions) parámetros de ejemplo; se sobreescriben con --fecha-func
  order_by  (functions) orden canónico para comparar "mismas filas, mismo orden"
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ParityObject:
    name: str
    kind: str
    dataset: str
    date_col: str | None = None
    keys: tuple[str, ...] = ()
    params: dict = field(default_factory=dict)
    order_by: tuple[str, ...] = ()

    @property
    def bq_ref(self) -> str:
        return "${project}.${" + self.dataset + "}." + self.name


# Fecha de ejemplo para las RPC (la web pasa la fecha seleccionada; 2025-11-30 tiene CHIST, IPD e índices).
FUNC_FECHA_DEFAULT = "2025-11-30"

# Fechas históricas fijas de §12 además de las últimas 3 disponibles por objeto.
FIXED_DATES = ("2025-06-30", "2025-12-31")

OBJECTS: list[ParityObject] = [
    # --- Tablas directas (12) --------------------------------------------------------------
    ParityObject("tipo_cambio", "table", "raw", "fecha", ("instrumento_codigo",)),
    ParityObject("valores_cuota_patrimonio", "table", "raw", "fecha", ("afp", "multifondo")),
    ParityObject("dim_bd_family", "table", "dim", None, ("family_id",)),
    ParityObject("dim_data_sources", "table", "dim", None, ("dataset_key",)),
    ParityObject("dim_distributor_by_manager", "table", "dim", None, ("manager",)),
    ParityObject("dim_sec08_top_flows", "table", "dim", "fecha", ("period_type", "direction", "rk")),
    ParityObject("dim_strategy_ipd_funds", "table", "dim", None, ("family_id", "id_fund")),
    ParityObject("ipd_cartera_eom", "table", "raw", "fecha", ("id_fund", "id_instrumento", "source")),
    ParityObject("ipd_attribution_monthly", "table", "raw", "mes", ("id_fund", "id_instrumento")),
    ParityObject("ipd_attribution_fund_month", "table", "raw", "mes", ("id_fund",)),
    ParityObject("ipd_rentabilidades", "table", "raw", "fecha", ("id_fund", "id_serie", "quiebre", "currency")),
    ParityObject("ipd_bms_membership", "table", "raw", "fecha", ("id_bm", "id_instrumento")),
    # --- Vistas (23) ----------------------------------------------------------------------
    ParityObject("v_aum", "view", "mart", "fecha", ("afp",)),
    ParityObject("v_nav", "view", "mart", "fecha", ("afp",)),
    ParityObject("v_uncalled", "view", "mart", "fecha", ("afp",)),
    ParityObject("v_total", "view", "mart", "fecha", ("afp",)),
    ParityObject("v_total_c1", "view", "mart", "fecha", ("c1",)),
    ParityObject("v_afp_c1", "view", "mart", "fecha", ("afp", "c1")),
    ParityObject("v_afp_c2", "view", "mart", "fecha", ("afp", "region", "category", "alt_fund_type", "alt_strategy")),
    ParityObject("v_afp_multifondo", "view", "mart", "fecha", ("afp", "tipo_de_fondo")),
    ParityObject("v_asset_class_tipo_sd", "view", "mart", "fecha_valor", ("tipo_fondo", "pdf_category")),
    ParityObject("v_asset_class_afp_sd", "view", "mart", "fecha_valor", ("afp_nombre", "tipo_fondo", "pdf_category")),
    ParityObject("v_asset_class_dates_sd", "view", "mart", "fecha_valor", ()),
    ParityObject("v_local_fi_by_afp_sd", "view", "mart", "fecha_reporte", ("afp", "pdf_bucket")),
    ParityObject("v_returns_afp_tipo", "view", "mart", "fecha", ("afp", "tipo_fondo")),
    ParityObject("v_contributors_market_share", "view", "mart", "fecha_reporte", ("afp",)),
    ParityObject(
        "v_foreign_pdf_summary_combined", "view", "mart", "fecha_reporte",
        ("pdf_bucket", "pdf_em_dm", "pdf_subregion", "pdf_fi_category",
         "pdf_bucket_nt", "pdf_em_dm_nt", "pdf_subregion_nt", "pdf_fi_category_nt", "source"),
    ),
    ParityObject(
        "v_foreign_returns_flows_summary", "view", "mart", "fecha_reporte",
        ("pdf_bucket", "pdf_em_dm", "pdf_subregion", "pdf_fi_category",
         "pdf_bucket_nt", "pdf_em_dm_nt", "pdf_subregion_nt", "pdf_fi_category_nt"),
    ),
    ParityObject("v_foreign_fund_flows", "view", "mart", "fecha_reporte", ("fund_id",)),
    ParityObject(
        "v_foreign_managers_combined", "view", "mart", "fecha_reporte",
        ("manager", "fund_style", "asset_class", "category", "region",
         "nt_asset_class", "nt_sub_asset_class", "nt_category", "nt_sub_category", "nt_region", "source"),
    ),
    ParityObject("v_sp_strategy_aum", "view", "mart", "fecha_valor", ("family_id", "fund_short_name")),
    ParityObject("v_local_equity_di_vs_if_combined", "view", "mart", "fecha_reporte", ("source",)),
    ParityObject("v_chilean_stocks_gics", "view", "mart", "fecha_reporte", ("afp", "multifondo", "nemo", "emisor")),
    ParityObject("v_distributors_sec09", "view", "mart", "fecha_reporte", ("distributor", "manager")),
    ParityObject("v_module_freshness", "view", "mart", None, ("module_key", "source_label")),
    # --- Matviews -> tablas mv_* (4) -------------------------------------------------------
    ParityObject("mv_strategy_afp_ow_uw", "mart", "mart", "fecha_reporte", ("family_id", "afp")),
    ParityObject("mv_sp_direct_investment_detail", "mart", "mart", "fecha_valor", ("nemotecnico",)),
    ParityObject("mv_foreign_latam_monthly", "mart", "mart", "fecha_reporte", ("pdf_bucket", "style_group")),
    ParityObject("mv_chist_chilean_stocks_by_nemo", "mart", "mart", "fecha_reporte", ("nemo",)),
    # --- RPC -> table functions (4) --------------------------------------------------------
    ParityObject("f_sec05_size", "function", "mart", params={"p_fecha": FUNC_FECHA_DEFAULT}, order_by=("bucket",)),
    ParityObject("f_sec05_ipsa_membership", "function", "mart", params={"p_fecha": FUNC_FECHA_DEFAULT}, order_by=("bucket",)),
    ParityObject("f_sec05_concentration", "function", "mart", params={"p_fecha": FUNC_FECHA_DEFAULT}, order_by=("metric",)),
    ParityObject("f_sec05_top40", "function", "mart", params={"p_fecha": FUNC_FECHA_DEFAULT}, order_by=("rk",)),
]

BY_NAME: dict[str, ParityObject] = {o.name: o for o in OBJECTS}

assert len([o for o in OBJECTS if o.kind != "function"]) == 39, "deben ser los 39 objetos de PLAN §1.2"
assert len([o for o in OBJECTS if o.kind == "function"]) == 4


# Columnas cuyo tipo en Postgres es double precision / porcentaje -> tolerancia absoluta 1e-9 (§12).
# El resto de numéricas (numeric / integer) -> tolerancia relativa 1e-6.
FLOAT_COLUMN_PATTERNS = (
    "pct", "share_", "ret_", "weight", "avg_weight", "contrib_", "usd_ret", "residual", "ret_month", "ret_serie",
    "return_usd_mm", "flow_usd_mm", "precio", "local_price", "qty", "mval", "nav_eom",
    "dtd", "mtd", "ytd", "itd", "y1", "y2", "y3", "y5", "alpha_1y", "beta_1y", "sharpe_1y", "te_1y", "ir_1y",
    "porcentaje",
)


def is_float_like(column: str) -> bool:
    c = column.lower()
    return any(p in c for p in FLOAT_COLUMN_PATTERNS)
