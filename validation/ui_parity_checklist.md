# Checklist de paridad de UI (PLAN_MIGRACION_GCP.md §12 — "Paridad de UI")

Comparar la web sobre BigQuery (Cloud Run) contra la web actual (Vercel + Supabase) **ruta por ruta y fecha por
fecha**: mismos KPIs, mismas filas en tablas, mismos badges "as of". Usar las mismas fechas que la paridad de datos
(últimas 3 disponibles + `2025-06-30` + `2025-12-31` cuando existan) y el mismo usuario.

Convención: `[ ]` pendiente · `[x]` igual · `[~]` diferencia explicada (anotar) · `[!]` diferencia sin explicar (bloquea F6).

Rellenar una copia por corrida en `validation/reports/ui_<fecha>.md`.

---

## 1. `/` — Alternative Assets (home)
Objetos: `v_total`, `v_aum`, `v_nav`, `v_uncalled`, `v_afp_multifondo`, `tipo_cambio`, `valores_cuota_patrimonio`,
`v_afp_c1`, `v_afp_c2`, `v_total_c1`, `v_module_freshness` (alternatives).
- [ ] Selector de fechas: mismas fechas disponibles (`getAvailableDates`, `fecha >= 2025-01-01`) y misma fecha por defecto.
- [ ] Summary AFP: AUM / NAV / Uncalled / Total por AFP idénticos (2 decimales) y mismo orden (Total desc).
- [ ] Fila expandible por multifondo A–E: NAV / Uncalled / Total / AUM iguales para 2 AFP de muestra.
- [ ] Matriz NAV por AFP × C1 (Private Equity / Private Debt / Real Asset / Other Alternative / Local).
- [ ] Evolución (Total y AUM por AFP): mismos puntos, misma cantidad de fechas.
- [ ] Detalle por AFP y SYSTEM: byC1, foreignPE, foreignPD, foreignRA, local — mismos valores en la última fecha.
- [ ] Badge "as of" (Holdings CHIST) = misma fecha; `is_behind` igual.

## 2. `/asset-allocation`
Objetos: `v_asset_class_dates_sd`, `v_asset_class_afp_sd`, `v_asset_class_tipo_sd`, `v_local_fi_by_afp_sd`, `v_module_freshness`.
- [ ] Fechas disponibles iguales (`fecha_valor >= 2025-01-01`).
- [ ] Matriz por AFP (tipo_fondo='TOTAL'): 16 categorías × 8 columnas (7 AFP + TOTAL), monto y % (2 decimales) iguales.
- [ ] Matriz por tipo de fondo (A–E + TOTAL): idem.
- [ ] Tabla OW/UW vs sistema: mismos signos y magnitudes.
- [ ] Local Fixed Income por AFP × bucket (6 buckets): iguales.
- [ ] Gráfico "over time" por tipo de fondo y por AFP: mismo número de meses y valores en 3 meses de muestra.
- [ ] Badge "as of" (Cartera agregada SP, _sd).

## 3. `/market-share`
Objetos: `v_returns_afp_tipo`, `v_contributors_market_share`, `v_module_freshness`.
- [ ] Fechas disponibles iguales.
- [ ] AUM por AFP × tipo de fondo (USD MM y CLP bn).
- [ ] Retornos MoM / YTD / LTM en CLP y USD (4 decimales), incluyendo filas TOTAL.
- [ ] Retorno de rango personalizado (calculado en cliente desde `valor_cuota` / `fx_clp_per_usd`): probar 2 rangos.
- [ ] Flujos MoM / YTD / LTM.
- [ ] Contributors: `fecha_cotizantes`, `n_cotizantes`, AVG USD/cotizante, share AUM y share cotizantes.
- [ ] Badges "as of" (Patrimonio/Cuota y Cotizantes).

## 4. `/foreign`
Objetos: `v_foreign_pdf_summary_combined`, `v_foreign_returns_flows_summary`, `v_foreign_fund_flows`,
`mv_sp_direct_investment_detail`, `mv_foreign_latam_monthly`, `v_module_freshness`.
- [ ] Fechas disponibles y `source` (CHIST / SP_XML) por fecha iguales.
- [ ] Árbol PDF (taxonomía nt y legacy): FI/Equity × EM/DM × subregión × categoría FI, PE, Direct Investment, total.
- [ ] Changes (MoM, 3M, 6M, YTD, LTM, 3Y): mismas fechas base resueltas y mismos deltas.
- [ ] Split Return / Flow por ventana: `covered` / `missing` iguales y mismos montos.
- [ ] Direct Investment detail (4 periodos): mismas filas (asset_class, di_category, country, currency, usd_mm).
- [ ] Evolución (Equity / FI / PE / DI / Other / Total) y Latam Evolution (eq_active/etf/passive/di, fi_funds/di).
- [ ] Sec 08 Top Net Flows (MoM y YTD, top 10 inflows/outflows): mismas listas y orden.
- [ ] Badges "as of" (Holdings CHIST, Cartera agregada SP, Retornos Bloomberg).

## 5. `/managers`
Objetos: `v_foreign_managers_combined`, `dim_data_sources`, `v_module_freshness`.
- [ ] Fechas disponibles iguales.
- [ ] Tabla de managers (con alias `x-trackers → Deutsche`): mismos managers, Active/Passive, montos por asset class / region.
- [ ] Taxonomía nt vs legacy: mismas agrupaciones.
- [ ] SourceBadge (dim_data_sources) muestra la misma procedencia.
- [ ] Badge "as of".

## 6. `/strategy`
Objetos: `dim_bd_family`, `v_sp_strategy_aum`, `mv_strategy_afp_ow_uw`, `v_local_equity_di_vs_if_combined`,
`dim_strategy_ipd_funds`, `ipd_cartera_eom`, `ipd_attribution_monthly`, `ipd_attribution_fund_month`,
`ipd_rentabilidades`, `v_module_freshness`.
- [ ] Lista de familias (dim_bd_family) idéntica y en el mismo orden.
- [ ] Por familia: periodos disponibles (`periodo >= 2025-01`), snapshot de fondos (AUM y market share %), serie temporal,
      rollup "Other" (Top 10 HY).
- [ ] Positioning by AFP (OW/UW): misma `fecha_reporte`, mismos `weight` / `sys_avg` / `ow_uw` por AFP.
- [ ] Local Equity DI vs IF (CLP bn): mismas fechas y valores, `source` por fecha.
- [ ] 4.1 Cartera EOM por fondo Moneda: NAV, filas y pesos (ordenadas por |weight|).
- [ ] 4.1 Atribución mes y trimestre: `ret_calc`, `ret_serie`, `residual`, top contribuidores.
- [ ] 4.2 Rentabilidades (serie vs benchmark, MTD/YTD/1Y, EOM): misma moneda elegida (USD; CLP para MDLAT).
- [ ] Badges "as of" (Estrategias SP, Local Equity DI CHIST, Posicionamiento AFP CHIST).

## 7. `/chilean-stocks`
Objetos: `v_chilean_stocks_gics`, `mv_chist_chilean_stocks_by_nemo`, `tipo_cambio`, `ipd_cartera_eom`, `ipd_bms_membership`,
`f_sec05_size`, `f_sec05_ipsa_membership`, `f_sec05_concentration`, `f_sec05_top40`, `dim_data_sources`, `v_module_freshness`.
- [ ] Fechas disponibles (`v_chilean_stocks_gics`, `>= 2025-01-01`) iguales.
- [ ] GICS breakdown: sectores, n emisores, AUM, %, top 5 emisores por sector.
- [ ] Transactions MTD / YTD / LTM: top 10 compras y ventas y total neto (misma metodología inv − inv_prev × price ratio).
- [ ] Sec05 fechas resueltas por fuente (Pionero, MRV, IPSA, AFPs) iguales.
- [ ] Sec05 Size (Large/Mid/Small/No IGPA), IPSA membership, Concentration (companies/top10/20/30), Top 40 (rk, nemo, montos, pesos).
- [ ] SourceBadge y badges "as of" (Holdings CHIST, Pionero/MRV IPD).

## 8. `/distributors`
Objetos: `v_distributors_sec09`, `dim_distributor_by_manager`, `v_module_freshness`.
- [ ] Fechas disponibles iguales.
- [ ] Tabla Sec 09 por distribuidor × manager (montos, `is_mapped`), 4 fechas base (1Y, cierre año anterior, mes anterior, hoy).
- [ ] Bucket `Unmapped` y `[Direct Investment]` con mismos montos.
- [ ] Admin: mapping manager → distribuidor (dim_distributor_by_manager) y lista de managers sin mapear.
- [ ] Badge "as of".

## 9. `/admin/data-sources`
Objetos: `dim_data_sources`.
- [ ] Misma lista de datasets, mismo orden (pdf_section, dataset_key), mismos `current_source` / `target_source`.
- [ ] `last_loaded_at` coherente (en BigQuery lo actualiza `apply.py --only seeds`; anotar la diferencia esperada).

---

## Transversal
- [ ] Login con usuario/contraseña funciona y `/login` redirige igual (Identity Platform vs Supabase Auth).
- [ ] Sidebar / logout.
- [ ] Ninguna página muestra error de PostgREST/BigQuery en consola del servidor.
- [ ] Tiempos de carga en frío aceptables (anotar p95 por ruta).
- [ ] Tras una corrida del job: `/api/revalidate` refresca y los badges "as of" cambian en ambas webs igual.
