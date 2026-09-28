# Plan de migración a 100 % GCP — AFP Chile Dashboard

> **Objetivo**: mover el dashboard (web), el pipeline mensual de datos y todo lo que hoy
> vive en Supabase + Vercel + una laptop en red Patria, a Google Cloud dentro del
> **mismo proyecto GCP actual**, con Cloud Run (servicio + jobs), BigQuery,
> Secret Manager, Cloud Scheduler, Artifact Registry e Identity Platform, y con
> CI/CD íntegramente en GitHub Actions.
>
> **Regla de oro**: el alcance funcional se mantiene **100 % íntegro**. Mismas
> secciones, mismos números, mismas vistas (mismos nombres), mismas ventanas y
> filtros de datos, mismo login con usuario/contraseña. Los cambios en código son
> **quirúrgicos**: se sustituye la capa de I/O del sync y la capa de acceso a datos
> de la web; las páginas, componentes y la lógica de negocio no se tocan.
>
> Estado: **diseño, pendiente de aprobación** (rama `claude/migracion-gcp-9w4y80`).
> Levantamiento hecho el 2026-09-28 sobre `main` @ `1d955da`.

---

## 0. Resumen ejecutivo

| Hoy | Mañana (GCP) |
|---|---|
| Web Next.js 16 en **Vercel** | Web Next.js 16 en **Cloud Run** (`afp-web`), imagen en Artifact Registry |
| Datos en **Supabase Postgres** (free tier 500 MB, se auto-pausa) | Datos en **BigQuery** (datasets `afp_raw`, `afp_dim`, `afp_mart`, `afp_ops`, `afp_stg`) |
| Web lee vía **PostgREST** (`supabase-js`) | Web lee vía **`@google-cloud/bigquery`** con SQL parametrizado, misma firma de funciones en `web/lib/queries-*.ts` |
| Vistas `v_*`, matviews `mv_*`, RPC `f_sec05_*` en Postgres | Vistas `v_*` en BigQuery, `mv_*` como **tablas reconstruidas por el job**, `f_sec05_*` como **table functions** de BigQuery |
| Sync Python (`main.py`, 8 pasos) corrido **a mano desde una laptop en red Patria** | Sync Python **idéntico** empaquetado en **Cloud Run Job** (`afp-sync`), disparado por **Cloud Scheduler** y/o `workflow_dispatch`, llegando a SQL Server por **VPN** |
| Auth **Supabase Auth** (email + password) | Auth **Identity Platform** (email + password), usuarios importados con su hash bcrypt (mantienen contraseña) |
| Secretos en `.env` / panel Vercel | **Secret Manager**, inyectados como env en Cloud Run |
| Sin CI/CD, deploy = push a Vercel | **GitHub Actions** con Workload Identity Federation (sin llaves JSON): CI en PR, deploy de web/sync/SQL/infra en `main` |
| DDL de Supabase parcialmente versionado | **Todo el esquema BigQuery versionado** en `db/bigquery/` y aplicado por pipeline |

Fases (detalle en §5):

| Fase | Qué entrega | Depende de |
|---|---|---|
| **F0** Congelar y capturar | Dump completo del esquema Supabase, export de tablas manuales, decisiones D1–D7 cerradas | — |
| **F1** Fundaciones GCP | Terraform: datasets, SAs, WIF, Artifact Registry, Secret Manager, VPC + conectividad a SQL Server | F0 |
| **F2** Capa de datos BigQuery | DDL de tablas, traducción de ~60 vistas/matviews/funciones, backfill, **validación de paridad** vs Supabase | F0 (F1 sólo para permisos) |
| **F3** Pipeline en Cloud Run Jobs | `sync/bq_io.py`, Dockerfile, Job, Scheduler, corrida en paralelo con Supabase | F1, F2 |
| **F4** Web en Cloud Run | `web/lib/db.ts`, reescritura de `queries-*.ts`, auth Identity Platform, Dockerfile, deploy | F2 |
| **F5** CI/CD completo + docs | Workflows definitivos, README/HANDOFF actualizados, runbook | F3, F4 |
| **F6** Corte y retiro | Migración de usuarios, DNS, apagado de Vercel y Supabase | F5 + paridad OK |

---

## 1. Estado actual (levantamiento)

### 1.1 Cadena de datos

```
Procesos del equipo → SQL Server (Inteligencia_Mercado / Inteligencia_Producto / DW_MONEDA)   [red interna Patria]
        │  main.py  →  sync/*.py   (pyodbc + ODBC Driver 18  →  supabase-py REST)          [laptop en red/VPN Patria]
        ▼
Supabase Postgres: tablas espejo → vistas v_* → matviews mv_* → funciones f_sec05_* / refresh_alternatives_matviews()
        │  supabase-js (PostgREST, service-role) con Next Data Cache 300 s + ISR 3600 s
        ▼
web/ (Next.js 16, App Router, server components)  →  Vercel        auth: Supabase Auth via @supabase/ssr + proxy.ts
```

### 1.2 Inventario

**Pipeline (`main.py`, 8 pasos, todos idempotentes):**

| # | Paso | Script | Fuente SQL Server | Tablas destino | Estrategia |
|---|---|---|---|---|---|
| 1 | `cotizantes` | `sync_sp_sqlserver_to_supabase.py` | `AFP_CL_Cotizantes` (pata `sp_*` apagada) | `cotizantes_afp` | DELETE ventana + INSERT |
| 2 | `core` | `sync_sqlserver_to_supabase.py` | 13 dims `DIM_BD_*`/`AFP_CL_DIM_*`, `DW_MONEDA.TBL_RENTABILIDADES_DW`, `AFP_CL_VC_PAT` | `dim_*` (13), `tipo_cambio`, `valores_cuota_patrimonio` | UPSERT; al final RPC `refresh_alternatives_matviews()` |
| 3 | `sd_asset_class` | `sync_sd_asset_class.py` | `AFP_CL_01_sd`, `AFP_CL_02_sd` | `sd_asset_class_tipo`, `sd_asset_class_afp` | DELETE por fecha + INSERT |
| 4 | `consolidated_sd` | `sync_consolidated_sd.py` | `AFP_CL_09_17_25_sd_consolidated` | `consolidated_sd` | DELETE por fecha + INSERT |
| 5 | `chist_adjusted` | `sync_chist_adjusted.py` | `AFP_CL_CHIST_ADJUSTED` (ventana auto-anclada) | `chist_adjusted` | DELETE por fecha + INSERT; RPC refresh |
| 6 | `bbg_returns` | `sync_bbg_returns.py` | `AFP_CL_BBG_Returns` | `bbg_returns` | DELETE + INSERT |
| 7 | `dim_bd_previa` | `sync_dim_bd_previa.py` | `DIM_BD_Previa_AFPCL` | `dim_bd_previa` | reload completo |
| 8 | `ipd_strategy` | `sync_ipd_strategy.py` | `TBL_IPA_V2`, `TBL_BMS_Exposicion`, `TBL_RENTABILIDADES_SERIES` | `ipd_cartera_eom`, `ipd_attribution_monthly`, `ipd_attribution_fund_month`, `ipd_rentabilidades`, `ipd_bms_membership` | DELETE-all + INSERT (pandas hace la atribución) |

Todos los scripts comparten los helpers `connect_sqlserver / connect_supabase / supabase_upsert / supabase_insert / supabase_delete_in / get_last_date / timed_read` de `sync_sqlserver_to_supabase.py` (o copias locales). **Ese es el punto de corte quirúrgico del pipeline.**

**Web — objetos Supabase leídos (39, extraído por grep de `.from()`/`.rpc()` en `web/lib`):**

Tablas directas (11): `tipo_cambio`, `valores_cuota_patrimonio`, `dim_bd_family`, `dim_data_sources`, `dim_distributor_by_manager`, `dim_sec08_top_flows`, `dim_strategy_ipd_funds`, `ipd_cartera_eom`, `ipd_attribution_monthly`, `ipd_attribution_fund_month`, `ipd_rentabilidades`, `ipd_bms_membership`.

Vistas (23): `v_aum`, `v_nav`, `v_uncalled`, `v_total`, `v_total_c1`, `v_afp_c1`, `v_afp_c2`, `v_afp_multifondo`, `v_asset_class_tipo_sd`, `v_asset_class_afp_sd`, `v_asset_class_dates_sd`, `v_local_fi_by_afp_sd`, `v_returns_afp_tipo`, `v_contributors_market_share`, `v_foreign_pdf_summary_combined`, `v_foreign_returns_flows_summary`, `v_foreign_fund_flows`, `v_foreign_managers_combined`, `v_sp_strategy_aum`, `v_local_equity_di_vs_if_combined`, `v_chilean_stocks_gics`, `v_distributors_sec09`, `v_module_freshness`.

Matviews (4): `mv_strategy_afp_ow_uw`, `mv_sp_direct_investment_detail`, `mv_foreign_latam_monthly`, `mv_chist_chilean_stocks_by_nemo` (+ intermedias `mv_chist_aa`, `mv_aum`, `mv_returns_afp_tipo`, `mv_foreign_fund_flows`, `mv_chist_foreign_managers`, etc.).

RPC (5): `f_sec05_size`, `f_sec05_ipsa_membership`, `f_sec05_concentration`, `f_sec05_top40` (lectura, con parámetros), `refresh_alternatives_matviews` (mantención).

Operadores PostgREST usados: `select/eq/gte/lte/gt/in/not/order/limit/range/maybeSingle/rpc`. Sin `or`, sin `like`, sin full-text. Paginación `.range()` en 6 lugares sólo para saltar el tope de 1 000 filas de PostgREST. **Reescritura a SQL parametrizado es mecánica.**

**Web — otros puntos de acoplamiento a Supabase:** `lib/supabase-server.ts` (cliente service-role + Data Cache), `lib/supabase-auth-server.ts`, `lib/supabase-browser.ts` (no se usa en ningún componente), `proxy.ts` (middleware auth, cache 60 s), `app/login/actions.ts` (login/logout), `components/sidebar.tsx` (botón logout). No hay fetch de datos desde el cliente; los 34 componentes `'use client'` son sólo UI.

### 1.3 Hallazgos que condicionan el plan

1. **El repo NO contiene el esquema completo de Supabase.** De los 39 objetos leídos por la web, 19 no tienen DDL en `sync/*.sql` (p. ej. `v_returns_afp_tipo`, `v_contributors_market_share`, `v_local_equity_di_vs_if_combined`, las 4 `f_sec05_*`, las 5 tablas `ipd_*`, `dim_data_sources`). Los `sync/*.sql` son *migrations* incrementales, no el estado final. → **F0 debe hacer `pg_dump --schema-only` del proyecto Supabase y versionarlo** antes de traducir nada.
2. **Tablas mantenidas a mano en Supabase sin seed versionado**: `dim_chilean_ticker_homol` (75 filas), `dim_valorizacion_remanente` (16), `dim_distributor_by_manager`, `dim_data_sources`, `dim_strategy_ipd_funds`, `dim_sec08_top_flows`, `dim_bdchile`, `dim_direct_investment_overlay`, `dim_foreign_classification_overlay`, `dim_foreign_region_override`, `dim_chilean_stocks_gics_override`. → **F0 las exporta a `db/seeds/` versionado** (son KB).
3. **SQL Server sólo es alcanzable desde la red Patria.** Hoy nada en la nube llega a él; el sync corre desde una laptop. → **La conectividad GCP ↔ Patria (VPN) es el camino crítico de F3** y necesita al equipo de redes de Patria (decisión D1). El resto de fases no la necesita: el backfill inicial a BigQuery se puede correr desde una laptop en red Patria (BigQuery va por HTTPS/443).
4. **Dos scripts usan `DRIVER={SQL Server}`** (`sync_sqlserver_to_supabase.py`, `sync_inteligencia_producto.py`), nombre de driver que sólo existe en Windows. En el contenedor Linux debe ser `ODBC Driver 18 for SQL Server` con `Encrypt=optional;TrustServerCertificate=yes` (como ya hacen los otros 5 scripts). Cambio de 3 líneas, necesario.
5. **Los `mv_*` se refrescan vía RPC plpgsql** al final de los pasos `core` y `chist_adjusted`. BigQuery no tiene `REFRESH MATERIALIZED VIEW` equivalente con esa semántica (sus MVs tienen restricciones de SQL y refresco automático). → Se traducen a **tablas reconstruidas** (`CREATE OR REPLACE TABLE … AS SELECT`) en un paso `marts` del job, conservando nombres `mv_*`.
6. **Caché de la web**: Data Cache 300 s + ISR 3 600 s + cache de auth 60 s, todo en memoria/disco por instancia. En Vercel eso está resuelto por la plataforma; en Cloud Run cada instancia tiene su caché. Además, hoy se "bustea" el ISR **redeployando** tras cada corrida (commits `Trigger fresh Vercel deployment…`). → Decisión D5 y endpoint de revalidación llamado por el job.
7. **Supabase free tier se auto-pausa** y ya rompió una corrida; BigQuery elimina ese modo de falla y el techo de 500 MB. **No se aprovecha para ampliar ventanas de datos en esta migración** (alcance íntegro); queda anotado como mejora posterior.
8. **No hay CI/CD, Dockerfiles ni `.github/`.** Se crean desde cero.
9. Los directorios `Codigos_legacy/`, `validacion/`, `CLAUDE.md` están gitignorados y **no** están en este clon. La validación de paridad nueva vivirá en el repo (`validation/`), no depende de ellos.

---

## 2. Principios

1. **Alcance íntegro.** Ninguna sección, vista, columna, ventana temporal o filtro cambia. Un número que hoy sale de `v_x` para `fecha=F` debe salir igual de `afp_mart.v_x` para `fecha=F` (tolerancia numérica documentada en §12).
2. **Cambios quirúrgicos y por capas.**
   - Pipeline: se reemplaza el módulo de escritura (`supabase_*` → `bq_*`) manteniendo firma y semántica; los scripts de paso y `main.py` casi no cambian.
   - Web: se reemplaza `lib/supabase-server.ts` por `lib/db.ts` y se reescribe el cuerpo de `queries-*.ts` **manteniendo firmas y tipos de retorno**; `app/` y `components/` no se tocan salvo login/logout.
   - Se conservan los nombres de tablas, vistas y funciones (`v_*`, `mv_*`, `f_sec05_*`) para que `LINEAGE.md` y la doc sigan siendo válidos.
3. **Mismo proyecto GCP, sin mezclar.** Todo recurso nuevo lleva prefijo `afp-`/`afp_`, labels `app=afp-dashboard`, `managed-by=terraform`, y su propia service account. Nada se comparte con otros workloads del proyecto salvo la VPC/VPN si ya existe una hacia Patria.
4. **Todo como código.** Terraform para infra, SQL versionado para BigQuery, GitHub Actions para CI/CD, Workload Identity Federation (sin llaves JSON descargadas).
5. **Convivencia y corte controlado.** Supabase y Vercel siguen vivos hasta que la paridad esté validada en producción paralela; el corte es un cambio de DNS y luego un apagado.
6. **Sin scope creep.** Historia completa de CHIST, nuevos módulos, cambios de UI, cambios de metodología: fuera de este plan (§14).

---

## 3. Arquitectura objetivo

```
                              GitHub (GitInteligencia/Project_AFPs)
                                │  GitHub Actions  (WIF → SA afp-github-deploy)
          ┌─────────────────────┼─────────────────────────┬──────────────────────┐
          ▼                     ▼                         ▼                      ▼
   Artifact Registry      Cloud Run Service           Cloud Run Job           BigQuery DDL
   afp/web, afp/sync      afp-web (Next.js)           afp-sync (main.py)      (db/bigquery/ apply)
                                │ ADC (SA afp-web-run)        │ ADC (SA afp-sync-run)
                                │ bigquery.jobUser +          │ bigquery.dataEditor afp_*
                                │ dataViewer afp_mart/afp_dim │ Direct VPC egress
                                ▼                             │
                     ┌──────────────────────┐                 ▼
                     │  BigQuery (region R) │        VPC afp-vpc ── HA VPN ──► Red Patria
                     │  afp_raw   (espejo)  │◄──────                              │
                     │  afp_dim   (dims/seeds)                          SQL Server Inteligencia_Mercado
                     │  afp_mart  (v_*, mv_*, f_sec05_*)                (fuente de verdad, sin cambios)
                     │  afp_ops   (run_log, freshness)
                     │  afp_stg   (staging MERGE, TTL 1 d)
                     └──────────────────────┘
   Identity Platform (email+password) ◄── afp-web login/proxy       Cloud Scheduler afp-sync-monthly ──► Job
   Secret Manager afp-*  ──► env de afp-web / afp-sync                Cloud Logging + alerta por fallo de job
```

### 3.1 Mapa componente → servicio GCP

| Componente | Servicio GCP | Nombre | Notas |
|---|---|---|---|
| Web Next.js | Cloud Run (service) | `afp-web` | `output: 'standalone'`, puerto 8080, min 1 / max 3 instancias, 1 vCPU / 1 GiB, concurrency 80 |
| Pipeline mensual | Cloud Run (job) | `afp-sync` | imagen `afp/sync`, `python main.py`; timeout 3 h; 2 vCPU / 4 GiB (paso `ipd_strategy` hace pandas pesado); reintentos 0 (idempotente, se relanza a mano) |
| Programación | Cloud Scheduler | `afp-sync-monthly` | ver D6 |
| Datos espejo | BigQuery dataset | `afp_raw` | `cotizantes_afp`, `tipo_cambio`, `valores_cuota_patrimonio`, `sd_asset_class_*`, `consolidated_sd`, `chist_adjusted`, `bbg_returns`, `ipd_*` |
| Dimensionales y seeds | BigQuery dataset | `afp_dim` | `dim_*` sincronizadas + manuales versionadas en `db/seeds/` |
| Capa de consumo | BigQuery dataset | `afp_mart` | vistas `v_*`, tablas `mv_*`, table functions `f_sec05_*` |
| Operación | BigQuery dataset | `afp_ops` | `run_log` (paso, inicio, fin, filas, rc), base de `v_module_freshness` si hace falta |
| Staging | BigQuery dataset | `afp_stg` | tablas temporales para `MERGE`; `default_table_expiration = 1 día` |
| Imágenes | Artifact Registry | repo `afp` (docker) | `afp/web:<sha>`, `afp/sync:<sha>`; política de limpieza: conservar 10 |
| Secretos | Secret Manager | `afp-sqlserver-host`, `afp-sqlserver-db`, `afp-sqlserver-uid`, `afp-sqlserver-pwd`, `afp-web-revalidate-token`, `afp-idp-api-key` | acceso por SA |
| Auth | Identity Platform | tenant por defecto, proveedor Email/Password | ver D2 |
| Identidades | IAM service accounts | `afp-web-run`, `afp-sync-run`, `afp-github-deploy` | mínimo privilegio (§10.3) |
| CI/CD identidad | Workload Identity Pool | `afp-github` / provider `github` | restringido a `repo:GitInteligencia/Project_AFPs:*` |
| Red | VPC + HA VPN (o reutilizar existente) | `afp-vpc`, subnet `afp-run-egress` | sólo si no existe ya una VPC con VPN a Patria; ver D1 |
| Estado Terraform / exports | GCS | `${PROJECT}-afp-tfstate`, `${PROJECT}-afp-artifacts` | versionado activado |
| Observabilidad | Cloud Logging / Monitoring | alerta `afp-sync-failed`, `afp-web-5xx` | notificación a correo del equipo |

### 3.2 Convenciones para no mezclar con lo demás del proyecto

- Prefijo **`afp-`** (recursos) / **`afp_`** (datasets BigQuery). Ningún recurso sin prefijo.
- Labels obligatorios: `app=afp-dashboard`, `env=prod`, `managed-by=terraform`.
- Una **service account por workload**; ninguna usa la SA por defecto de Compute.
- Región única **R** para Cloud Run, Artifact Registry, BigQuery y Scheduler (decisión D3). BigQuery no permite joins entre regiones, así que **todos** los datasets `afp_*` van en R.
- Terraform gestiona **sólo** recursos `afp-*` (no importa ni toca nada preexistente). Si el proyecto ya tiene VPC/VPN a Patria, se referencia con `data` sources, no se administra.
- Carpeta `infra/terraform/` con un único workspace `prod` (no hay ambientes hoy; alcance íntegro). Un ambiente `dev` es opcional y fuera de alcance.

---

## 4. Decisiones a confirmar antes de ejecutar

| ID | Decisión | Recomendación | Alternativas / implicancias |
|---|---|---|---|
| **D1** | Conectividad Cloud Run Job → SQL Server | **RESUELTA por el usuario (2026-09-28): sin VPN.** El túnel que necesitaba Geneva era hacia su servidor Geneva, no aplica aquí. Solución: el job sale por **Cloud NAT con IP estática** (`afp-nat-ip`, VPC `afp-vpc`, Direct VPC egress) y esa IP se allowlistea en el firewall del SQL Server. Además la imagen `afp-sync` es **portable**: si el allowlist se demora, la misma imagen corre en cualquier máquina que alcance el SQL Server, con ADC, escribiendo a BigQuery por HTTPS | **Nota de alcance**: el pipeline sigue leyendo el SQL Server `Inteligencia_Mercado` (única fuente del código actual). Las tablas que consume son elaboraciones del equipo (clasificación `supracategory`, `01_sd/02_sd`, consolidado, retornos Bloomberg, `DIM_BD_*`, `TBL_IPA_V2`); el origen último (spensiones.cl) es público, pero re-apuntar el job a spensiones.cl directo obligaría a rehacer esa clasificación en GCP y rompería el alcance íntegro. Queda fuera de este plan. |
| **D2** | Autenticación | **Identity Platform, proveedor Email/Password**, importando los usuarios de Supabase con su hash bcrypt (`firebase auth:import --hash-algo=BCRYPT`): misma pantalla de login, mismas credenciales, sesión en cookie `__session` firmada (Firebase Admin `createSessionCookie`) verificada en `proxy.ts` | **IAP** (Identity-Aware Proxy) delante de Cloud Run con cuentas Google: cero código de auth, pero cambia la UX (desaparece el login propio) y exige cuentas Google/Workspace para todos → rompe "alcance íntegro". Se descarta salvo que el equipo lo prefiera explícitamente. **Precedente `geneva` (§4.1):** IAP se intentó el 2026-07-22 y falló por falta de `setIamPolicy`; la consola quedó `--allow-unauthenticated` + login propio con clave compartida (provisorio). Identity Platform necesita que infra habilite `identitytoolkit.googleapis.com` y cree la API key: **pedirlo en el mismo ticket que la conectividad**. Si no llega a tiempo, el fallback compatible con el alcance es el patrón ya usado por el equipo: servicio público + login propio (usuario/contraseña con hash bcrypt en una tabla `afp_ops.users`, sesión firmada) — misma UX, sin dependencia de IAM. |
| **D3** | Región R | **RESUELTA: `southamerica-west1`** — es la región de todo Geneva (Cloud Run, Artifact Registry, BigQuery, Scheduler) en el mismo proyecto | — |
| **D4** | Matviews `mv_*` | **Tablas** en `afp_mart` reconstruidas por el paso `marts` del job (`CREATE OR REPLACE TABLE … AS SELECT`), en el mismo punto donde hoy se llama `refresh_alternatives_matviews()` | Materialized views nativas de BigQuery: refresco automático pero SQL restringido (sin `QUALIFY`/window en algunos casos) y costo de refresco incremental. Se descarta para paridad exacta. |
| **D5** | Caché Next.js en Cloud Run | **min-instances = 1, max = 3**, se mantienen `revalidate` actuales, y se agrega `POST /api/revalidate` (token en Secret Manager) que el job llama al terminar para invalidar Data Cache + ISR. Reemplaza el "redeploy para bustear ISR" de hoy | Cache handler compartido (GCS/Memorystore) para coherencia entre instancias. Más piezas; sólo si el tráfico obliga a >1 instancia estable. |
| **D6** | Disparo del pipeline | **Cloud Scheduler los días 8 y 18 de cada mes 07:00 America/Santiago** (los pasos son idempotentes; la doble corrida recoge fuentes que llegan tarde, p. ej. CHIST) **+** `workflow_dispatch` en GitHub Actions para corridas manuales con `--only`, `--start`, `--months-back` | Sólo manual (como hoy). Se recomienda automatizar porque ya no hay laptop de por medio. |
| **D7** | Infra como código | **Cambio de recomendación tras `geneva`: scripts `gcloud`/`bq` idempotentes + diagnóstico `testIamPermissions`** (`infra/setup-afp.sh` y `infra/diagnostico-iam.sh`, calco de `infra/cloudbuild/setup-infra.yaml` y `diagnostico-iam.yaml` de Geneva). Infra de Patria **no delega** `iam.serviceAccountAdmin` ni `resourcemanager.projectIamAdmin`: crea SAs y bindings project-level ella misma, una vez; el resto lo aplica una identidad de despliegue. Terraform exigiría exactamente esos roles para su `apply` y quedaría bloqueado | Terraform sólo si infra acepta operar el `apply` (poco probable según el precedente) |

Valores ya fijados por el usuario (2026-09-28): **proyecto `pat-uat-global` (UAT)**, **URLs por defecto de Cloud Run (`*.run.app`), sin dominio propio ni DNS**. Pendiente: lista de usuarios a migrar (base: los 5 correos de la consola Geneva).

### 4.1 Respuestas obtenidas del repo `IgnacioF1988/geneva` (revisado 2026-09-28)

Geneva es la otra app del equipo ya corriendo en GCP (loader/certify/extractor como Cloud Run Jobs, MCP y consola Streamlit como Cloud Run Services, BigQuery como motor). Es el precedente vivo de "cómo se hacen las cosas" en este proyecto y en esta organización. Lo que responde y lo que no:

| Pregunta | Respuesta desde `geneva` | Fuente |
|---|---|---|
| **Proyecto GCP** | `pat-uat-global`. **Ojo: es el proyecto UAT** ("no toca producción"; el pase a prod lo hará infra). Si "el mismo proyecto actual" es éste, el dashboard de AFP nacería en UAT. Confirmar si eso es aceptable o si infra ya tiene un proyecto prod donde replicar | `.env.example`, `ops/BRIEFING-INFRA-WIRING.md`, `HANDOFF.md` |
| **Región** | `southamerica-west1` para todo (Cloud Run, AR, BigQuery, Scheduler) | `infra/cloudbuild/*.yaml`, `CLAUDE.md` |
| **¿Existe VPN/VPC hacia la red on-prem?** | **No.** El extractor de Geneva necesita llegar a `sanws020.moneda.cl:80` y su deploy tiene `_VPC_CONNECTOR: ""` a la espera de que infra provisione "Serverless VPC Access connector en `southamerica-west1` + ruta/firewall (vía Cloud VPN/Interconnect si aún no hay túnel)". La extracción diaria de Geneva está detenida desde 2026-05-29 (P1) en parte por esto. El diseño de Geneva asume explícitamente "no depender de VPN": contenedor portable que corre on-prem o en GCP | `infra/cloudbuild/deploy-extractor.yaml`, `ops/PLAN-EXTRACTOR.md §GCP`, `ops/PENDIENTES.md` P1/P2/P5, `HANDOFF.md` §27 |
| **Auth de apps web** | IAP intentado y bloqueado por permisos (2026-07-22). Consola: `--allow-unauthenticated` + login propio (lista de correos + clave compartida en `CONSOLA_PASSWORD`). MCP: público + bearer token en Secret Manager. Identity Platform no se ha usado | `apps/consola/auth.py`, `infra/cloudbuild/deploy-consola.yaml`, `deploy-mcp.yaml` |
| **Dominio / DNS** | Sin dominio propio: se usan las URLs `*.run.app` de Cloud Run. No hay precedente de domain mapping ni Load Balancer | — |
| **CI/CD** | **Cloud Build triggers sobre push a `main`** (`geneva-{loader,certify,mcp,consola}-deploy`, funcionando desde 2026-07-08), con SA de build `cloud-build@pat-uat-global`. GitHub Actions existe sólo como *gates* interinos (ruff, pytest, checks) sin deploy. Repo interino personal; pendiente P4 mover a repo corporativo y re-apuntar triggers | `.github/workflows/gates.yml`, `infra/cloudbuild/deploy-*.yaml`, `ops/RUNBOOK-REFRESH-MARTS.md` |
| **Modelo de permisos de infra** | Infra (`msalas@patria.com`, `ti-infra-admin@patria.com`) **retiene** `iam.serviceAccountAdmin` y `resourcemanager.projectIamAdmin`: crea SAs y bindings project-level ella misma, una vez. A `cloud-build@` le concedió `bigquery.admin`, `storage.admin`, `artifactregistry.admin`, `iam.serviceAccountUser`, `cloudscheduler.admin` (+ `run.admin`, `artifactregistry.writer` previos) y se recomienda recortarlos tras el bootstrap. La cuenta humana (`ignacio.fuentes@`) tiene `cloudbuild.builds.editor` + `actAs` sobre `cloud-build@`, sin IAM admin. Secret Manager: no había `secretmanager.admin` (la clave de la consola viaja como substitution del build). Eventarc deshabilitado; Cloud Scheduler operativo | `ops/BRIEFING-INFRA-WIRING.md`, `infra/iam/setup-loader.md`, `infra/cloudbuild/setup-infra.yaml` |
| **Recursos ya existentes reutilizables** | Artifact Registry `geneva` (docker, `southamerica-west1`); SAs `cloud-build@`, `wiki-mcp-run@` (BQ dataViewer project-wide), `bi-storage@` (lectura, dev local), `geneva-loader@`, `geneva-certify@`; bucket `genevarawbucket`; datasets `geneva`, `geneva_ops`, `geneva_lab`. **Para AFP no se reutiliza ninguno** (principio de no mezclar): se pide repo AR `afp`, SAs `afp-*`, datasets `afp_*` | `setup-infra.yaml` |
| **Convenciones de naming** | `<app>-<componente>` para Cloud Run/SAs (`geneva-loader-catchup`, `geneva-certify-daily`), `<app>` y `<app>_ops` para datasets, label BigQuery `app=<app>-<componente>` para separar costos. Coincide con lo propuesto (`afp-web`, `afp-sync`, `afp_raw`/`afp_mart`/`afp_ops`, `app=afp-dashboard`) | `deploy-*.yaml`, `apps/consola/README.md` |
| **Dimensionamiento Cloud Run** | Services: `--min-instances=1 --max-instances=3/4`, 1–2 GiB, `--session-affinity` cuando hay estado. Jobs: `--cpu=2 --memory=4Gi` (OOM real con los 512 MiB por defecto), `--task-timeout=3600/7200`, `--max-retries=0/1`. Confirma los valores del §3.1 | `deploy-loader.yaml`, `deploy-mcp.yaml`, `deploy-consola.yaml` |
| **Programación** | Cloud Scheduler HTTP → `run.googleapis.com/v2/.../jobs/<job>:run` con `--oauth-service-account-email` de la SA runtime, que necesita `run.invoker` sobre su propio job. Zona `America/Santiago`. Sin dependencias entre jobs: orden por horario, pasos idempotentes | `setup-infra.yaml §6` |
| **Operador de la corrida mensual** | El equipo Geneva es Ignacio Fuentes (`ifuentes@` / `ignacio.fuentes@patria.com`); la consola lista 5 usuarios del equipo (`antonio.escobar@`, `jgonzalez@`, `ignacio.fuentes@`, `ignacio.rebolledo@`, `cristopher.olmedo@`). Es la base razonable para la lista de usuarios/operadores del dashboard AFP, a confirmar | `apps/consola/auth.py` |
| **Presupuesto** | No hay cifra. Geneva escanea ~130 GB/día en el refresh de marts sin restricción declarada; AFP quedará muy por debajo. Sigue abierto | — |
| **Tooling Python** | `uv` + `ruff` + `pytest`, Python 3.12, imágenes `python:3.12-slim`. Se adopta para `afp-sync` (CI y Dockerfile) | `pyproject.toml`, `infra/docker/*.Dockerfile` |

**Impacto en este plan:**

1. **D3 resuelta** (`southamerica-west1`). **Proyecto**: `pat-uat-global` salvo que se confirme un proyecto prod.
2. **D1 se reformula**: no hay túnel; la solicitud a infra se hace conjunta con la del extractor Geneva, y `afp-sync` se construye **portable** (Cloud Run Job cuando exista el conector; mientras, la misma imagen on-prem). El pipeline sigue siendo un solo `main.py` con destino BigQuery; sólo cambia dónde corre.
3. **D7 cambia a scripts `gcloud` idempotentes + diagnóstico IAM**, porque infra no delega los roles que Terraform necesitaría. El plan de F1 se reescribe como `infra/diagnostico-iam.sh` → ticket a infra con los `[NO]` → `infra/setup-afp.sh`.
4. **CI/CD (petición explícita de este proyecto: GitHub Actions).** Se mantiene GitHub Actions como orquestador, pero hay que elegir el mecanismo de autenticación, y ambos requieren una acción única de infra:
   - **(a) Workload Identity Federation** (lo propuesto): infra crea el pool/provider `afp-github` y el binding `workloadIdentityUser` sobre `afp-github-deploy@` (exige `iam.workloadIdentityPoolAdmin` + `projectIamAdmin`, que infra retiene). Sin llaves, auditable, independiente de Cloud Build. **Recomendado.**
   - **(b) GitHub Actions como gates + Cloud Build triggers para el deploy** (patrón ya vigente en la organización): reutiliza `cloud-build@` y el flujo que infra ya conoce, pero exige instalar la GitHub App de Cloud Build en la organización `GitInteligencia` y crear triggers, y el deploy deja de vivir en Actions.
   Si infra rechaza (a), (b) es el fallback natural y los `deploy-*.yml` se convierten en `cloudbuild/deploy-*.yaml` casi línea a línea.
5. **D2**: Identity Platform sigue siendo la recomendación (preserva login y contraseñas), pero se agrega el fallback "servicio público + login propio" que la organización ya acepta, para no bloquear F4 por permisos.
6. **Secret Manager**: incluir en el ticket a infra la creación de los secretos `afp-*` (o el rol `secretmanager.admin` acotado), porque Geneva no lo tenía.
7. **Ticket único a infra** (reemplaza los pedidos dispersos de F0/F1): crear SAs `afp-web-run`, `afp-sync-run`, `afp-github-deploy` + `bigquery.jobUser`; pool/provider WIF (o triggers Cloud Build); habilitar `identitytoolkit`; crear secretos `afp-*`; conector VPC + túnel a la red Patria con ruta al SQL Server:1433 (compartido con Geneva); habilitar `vpcaccess.googleapis.com`. Todo lo demás (datasets, ACLs por dataset, AR, Scheduler, Cloud Run) lo aplica `afp-github-deploy@` (o `cloud-build@`) con el setup idempotente.

---

## 5. Plan por fases

### F0 — Congelar y capturar (sin tocar producción)

**Objetivo:** tener en el repo todo lo que hoy sólo existe en Supabase, y cerrar D1–D7.

Tareas:
1. **Dump del esquema Supabase** (`pg_dump --schema-only --schema=public` con la connection string directa desde una red sin bloqueo, o desde el SQL editor exportando `pg_get_viewdef`/`pg_get_functiondef` de cada objeto) → `db/supabase_snapshot/schema.sql`. Es la **fuente canónica para la traducción**; los `sync/*.sql` quedan como historial.
2. **Grafo de dependencias** (`pg_depend`/`pg_rewrite`) → `db/supabase_snapshot/deps.csv` (vista → objetos base). Ordena la traducción y el orden de creación en BigQuery.
3. **Export de tablas manuales y metadata** vía REST (`supabase-py`) → `db/seeds/<tabla>.csv` + `db/seeds/README.md` (las 11 de §1.3.2). Script `db/seeds/export_from_supabase.py` versionado para poder repetirlo antes del corte.
4. **Perfil de tamaño** por tabla (`pg_total_relation_size`) y **muestra de referencia** para paridad: por cada objeto de §1.2, `COUNT(*)`, `MIN/MAX(fecha)`, y `SUM` de las columnas numéricas para las últimas 3 fechas → `validation/baseline_supabase/<objeto>.json`. Script `validation/snapshot_supabase.py`.
5. **Export de usuarios** de Supabase Auth (`auth.users`: `email`, `encrypted_password`, `created_at`) → archivo **fuera del repo** (secreto), para D2.
6. Cerrar D1–D7 con el equipo; anotar en este documento (§4) la decisión tomada.
7. Solicitar a redes Patria lo de D1 (VPN o allowlist). **Arranca el reloj del camino crítico.**

Criterios de aceptación: `db/supabase_snapshot/schema.sql` reproduce los 39 objetos + intermedios; `db/seeds/` tiene las 11 tablas; baseline generado; D1–D7 registradas.

### F1 — Fundaciones GCP (scripts idempotentes; ver D7 y §4.1)

**Objetivo:** todo el andamiaje del proyecto listo, vacío, con permisos mínimos.

> Tras revisar `geneva`, F1 se ejecuta con `infra/diagnostico-iam.sh` (imprime `[SI]/[NO]` por permiso, como `diagnostico-iam.yaml` de Geneva) → ticket único a infra con los `[NO]` → `infra/setup-afp.sh` (idempotente, re-ejecutable, como `setup-infra.yaml`). Los puntos siguientes describen **qué** se crea; el **cómo** ya no es Terraform. Si infra aceptara operar Terraform, la lista es la misma.

Tareas (`infra/`):
1. Backend GCS `${PROJECT}-afp-tfstate`; providers; variables `project_id`, `region`, `github_repo`.
2. APIs: `run`, `bigquery`, `artifactregistry`, `secretmanager`, `cloudscheduler`, `iamcredentials`, `identitytoolkit`, `vpcaccess`/`compute` (según D1), `logging`, `monitoring`.
3. Datasets `afp_raw`, `afp_dim`, `afp_mart`, `afp_ops`, `afp_stg` (este último con `default_table_expiration_ms = 86400000`), en región R, labels.
4. Service accounts `afp-web-run`, `afp-sync-run`, `afp-github-deploy` y roles (§10.3).
5. Workload Identity Pool `afp-github` + provider OIDC de GitHub, `attribute.repository == "GitInteligencia/Project_AFPs"`; binding `roles/iam.workloadIdentityUser` a `afp-github-deploy`.
6. Artifact Registry `afp` (Docker) con cleanup policy.
7. Secret Manager: los 6 secretos de §3.1 **creados vacíos** (los valores se cargan a mano una vez; Terraform ignora `secret_data`).
8. Identity Platform: habilitar, proveedor Email/Password, dominios autorizados; API key restringida a Identity Toolkit y al dominio de la web.
9. Red (según D1): VPC `afp-vpc` + subnet `afp-run-egress` (/26) + Cloud Router + HA VPN gateway + túneles + rutas al CIDR del SQL Server. Si ya existe VPN en el proyecto, `data` sources y sólo la subnet.
10. Cloud Run service `afp-web` y job `afp-sync` **definidos en Terraform con una imagen placeholder** (`gcr.io/cloudrun/hello`) y `lifecycle.ignore_changes = [template[0].containers[0].image]`: la imagen la actualizan los workflows de deploy, la configuración (env, secretos, SA, VPC, recursos) la gobierna Terraform.
11. Cloud Scheduler `afp-sync-monthly` (D6), con OAuth del SA `afp-sync-run` para invocar `jobs.run`.
12. Alertas: job failed (log-based metric sobre `run.googleapis.com/job_execution` con `status=Failed`) y 5xx ratio de `afp-web`.
13. Workflow `infra-plan.yml` (PR → `terraform plan` como comentario) y `infra-apply.yml` (`workflow_dispatch` con environment `prod` que exige aprobación).

Criterios: `terraform apply` limpio; `bq ls` muestra los 5 datasets; `gcloud run jobs describe afp-sync` existe; prueba de conectividad desde un job efímero (`nc -vz <sql-host> 1433`) OK cuando D1 esté desplegado.

### F2 — Capa de datos en BigQuery

**Objetivo:** el esquema completo en BigQuery, poblado, con paridad demostrada contra Supabase.

Tareas:
1. **DDL de tablas** (`db/bigquery/tables/*.sql`): una por tabla de `afp_raw` y `afp_dim`, derivadas de `schema.sql`. Reglas de tipo en §7. Particionar por `fecha` (mensual) y clusterizar por `afp, tipo_de_fondo` las tablas grandes (`chist_adjusted`, `consolidated_sd`, `valores_cuota_patrimonio`, `sd_asset_class_*`, `ipd_cartera_eom`); dims sin partición.
2. **Seeds** (`db/seeds/*.csv`) → `bq load` a `afp_dim` desde el workflow `deploy-bq.yml` (idempotente, `--replace`).
3. **Traducción de vistas** (`db/bigquery/views/*.sql`) en orden topológico según `deps.csv`. Una vista por archivo, `CREATE OR REPLACE VIEW afp_mart.v_x AS …`. Vistas intermedias también viven en `afp_mart` (nombre igual al de Postgres).
4. **Matviews → tablas** (`db/bigquery/marts/*.sql`): un archivo por `mv_*` con `CREATE OR REPLACE TABLE afp_mart.mv_x PARTITION BY … CLUSTER BY … AS SELECT …`, más `db/bigquery/marts/refresh_order.txt` que replica el contenido de `refresh_alternatives_matviews()` (orden de refresco). Las vistas que hoy leen `mv_*` siguen leyendo `afp_mart.mv_*`.
5. **RPC → table functions** (`db/bigquery/functions/*.sql`): `CREATE OR REPLACE TABLE FUNCTION afp_mart.f_sec05_size(p_fecha DATE, …) AS (…)`, preservando nombres y parámetros; los cuerpos salen de `pg_get_functiondef` en `schema.sql`.
6. **`v_module_freshness`**: se traduce igual (lee `MAX(fecha)` de cada tabla); si en Postgres depende de `pg_stat`/catálogo, se reemplaza por lecturas de `afp_ops.run_log`.
7. **Aplicador** `db/bigquery/apply.py` (Python + `google-cloud-bigquery`): ejecuta tables → seeds → views → functions en orden, con `--dry-run` para CI. Idempotente.
8. **Backfill inicial** a `afp_raw` **desde SQL Server** (fuente de verdad) usando ya el nuevo `sync/bq_io.py` de F3 (se adelanta su desarrollo mínimo) corrido desde una laptop en red Patria con `gcloud auth application-default login`: `python main.py --start 2020-01-01` (+ `chist_adjusted` con su ventana propia). Mismas ventanas y filtros que hoy. Las tablas sin fuente SQL (`ipd_*` se regeneran con el paso 8; las manuales vienen de seeds).
9. **Refresco de marts** y **validación de paridad** con `validation/compare_bq_vs_supabase.py`: para cada uno de los 39 objetos (y para las 4 funciones con los parámetros que usa la web), compara contra `baseline_supabase/` y contra Supabase en vivo: filas, fechas, sumas numéricas por `fecha` (y por `afp` donde exista). Tolerancias en §12. Informe `validation/reports/<fecha>.md`.
10. Iterar traducciones hasta paridad `[OK]` en todos los objetos.

Criterios: `apply.py` corre limpio desde cero sobre datasets vacíos; paridad `[OK]`/`[WARN]` en el 100 % de los objetos; ningún `[FAIL]` sin justificación escrita (y ninguna justificación que implique cambio de números).

### F3 — Pipeline en Cloud Run Jobs

**Objetivo:** `python main.py` corre en GCP, escribe en BigQuery, con la misma semántica de hoy.

Tareas:
1. **`sync/bq_io.py`** (nuevo): `connect_bigquery()`, `bq_upsert(table, df, on_conflict)`, `bq_insert(table, df)`, `bq_delete_in(table, col, values)`, `bq_replace(table, df)`, `get_last_date(table, col)`, `refresh_marts(names)`, `log_run(step, …)`. Contrato idéntico a los helpers `supabase_*` (§9.2). Dataset destino se resuelve por tabla (`afp_raw` vs `afp_dim`) desde un mapa en el propio módulo.
2. **Cambio quirúrgico en los 8 scripts + `sync_inteligencia_producto.py`**: reemplazar `from supabase import create_client` / `connect_supabase()` / `supabase_*()` por sus equivalentes `bq_*`; reemplazar `sb.rpc('refresh_alternatives_matviews')` por `refresh_marts(ALTERNATIVES_MARTS)`; corregir `DRIVER={SQL Server}` → `ODBC Driver 18` (hallazgo 1.3.4). La lógica de consulta a SQL Server, ventanas, dedupe y pandas **no se toca**.
3. **`main.py`**: sin cambios funcionales; se agrega escritura de `afp_ops.run_log` por paso (inicio, fin, rc, filas) y, al final, llamada a `POST ${WEB_URL}/api/revalidate` con el token (D5). Flags `--list/--only/--start/--months-back/--skip-strategy/--keep-going` intactos.
4. **`sync/requirements.txt`**: quitar `supabase`, agregar `google-cloud-bigquery[pandas]`, `pyarrow`, `db-dtypes`.
5. **`sync/Dockerfile`**: `python:3.12-slim-bookworm` + `msodbcsql18` + `unixodbc` (repo Microsoft), `pip install -r requirements.txt`, `COPY main.py sync/`, `ENTRYPOINT ["python","main.py"]`. `TQDM_DISABLE=1` para logs limpios.
6. **Env del job** (Terraform): `DB_SERVER/DB_DATABASE/DB_UID/DB_PWD` desde Secret Manager, `GCP_PROJECT_ID`, `BQ_LOCATION`, `WEB_URL`, `REVALIDATE_TOKEN` (secreto). `load_dotenv()` sigue funcionando en local con `.env`.
7. **Workflow `deploy-sync.yml`**: build & push `afp/sync:<sha>` → `gcloud run jobs update afp-sync --image …`.
8. **Workflow `run-sync.yml`** (`workflow_dispatch`, inputs `only`, `start`, `months_back`, `skip_strategy`, `keep_going`): `gcloud run jobs execute afp-sync --args=…  --wait`, y adjunta el resumen del log al job de Actions. Es el reemplazo de "abrir PowerShell en la laptop".
9. **Corrida en paralelo**: durante ≥ 1 ciclo mensual el job escribe en BigQuery mientras la corrida legacy sigue escribiendo en Supabase; se repite la comparación de F2.9 después de cada corrida.

Criterios: ejecución del job termina `OK` en los 8 pasos vía VPN; `run_log` completo; `mv_*` reconstruidos; comparación post-corrida `[OK]`.

### F4 — Web en Cloud Run

**Objetivo:** la misma web, leyendo BigQuery y autenticando con Identity Platform.

Tareas:
1. **`web/lib/db.ts`** (nuevo, `server-only`): cliente `BigQuery` singleton (ADC), `query<T>(sql, params, {tag})` que envuelve `bigquery.query({query, params, location})` y cachea el resultado con `unstable_cache`/`"use cache"` bajo el tag `bq` durante el mismo `REVALIDATE_S = 300` de hoy. Exporta `BQ_CACHE_TAG`. Nombres de datasets desde env (`BQ_DATASET_MART`, etc.) con defaults `afp_mart`/`afp_dim`/`afp_raw`.
2. **Reescritura de `web/lib/queries*.ts` (18 archivos)**: cada función conserva **nombre, parámetros y tipo de retorno**; el cuerpo pasa de builder PostgREST a SQL parametrizado (`SELECT cols FROM afp_mart.v_x WHERE fecha = @fecha ORDER BY … LIMIT n`). Los bucles `.range()` desaparecen (BigQuery devuelve todo) manteniendo el post-procesado en TypeScript tal cual. Las 4 RPC pasan a `SELECT * FROM afp_mart.f_sec05_x(@p1, @p2)`. Regla: **cero cambios en `app/` y `components/` por este punto**.
3. **Auth (D2)**: `lib/auth-server.ts` con `firebase-admin` (ADC): `signInWithEmailPassword()` → REST Identity Toolkit `accounts:signInWithPassword`, `createSessionCookie()`, `verifySessionCookie()`, `revoke`. `app/login/actions.ts`: mismas funciones `login(formData)`/`logout()` con el mismo contrato (redirect, `?error=`). `proxy.ts`: reemplaza `createServerClient(...).auth.getUser()` por `verifySessionCookie`, conservando el cache de 60 s y las redirecciones. `components/sidebar.tsx` y `app/login/page.tsx` **sin cambios** (siguen llamando `logout`/`login`). Eliminar `lib/supabase-*.ts` y las deps `@supabase/*`.
4. **`app/api/revalidate/route.ts`** (nuevo): `POST` con header `x-revalidate-token`; compara con `REVALIDATE_TOKEN`; ejecuta `revalidateTag('bq')` + `revalidatePath('/', 'layout')`. Hay que **excluir `/api/` del matcher de `proxy.ts`**: el comentario del código dice que ya excluye rutas API, pero la regex actual no lo hace y redirigiría el POST a `/login`.
5. **`next.config.ts`**: `output: 'standalone'`. **`web/Dockerfile`** multi-stage (`node:22-alpine`: deps → build → runner con `.next/standalone` + `public` + `.next/static`), `PORT=8080`, usuario no root. `.dockerignore`.
6. **Env del servicio** (Terraform): `GCP_PROJECT_ID`, `BQ_LOCATION`, `BQ_DATASET_*`, `NEXT_PUBLIC_IDP_API_KEY`, `IDP_AUTH_DOMAIN`, `REVALIDATE_TOKEN` (secreto). `web/.env.example` actualizado.
7. **Workflow `deploy-web.yml`**: build & push `afp/web:<sha>` → `gcloud run deploy afp-web --image …`. En PR: `gcloud run deploy --no-traffic --tag pr-<n>` y comentar la URL de preview (equivalente a los previews de Vercel).
8. **Paridad visual**: recorrer las 9 rutas (`/`, `/asset-allocation`, `/market-share`, `/strategy`, `/foreign`, `/managers`, `/chilean-stocks`, `/distributors`, `/admin/data-sources`) con las mismas fechas en Vercel y Cloud Run; checklist en `validation/ui_parity_checklist.md`. Medir TTFB por página (frío/caliente) y ajustar `min-instances`/cache si hace falta.

Criterios: `npm run build` y `npm run lint` limpios; contenedor sirve las 9 rutas con login; misma información en pantalla que Vercel para 3 fechas de referencia; TTFB en caliente ≤ el de Vercel + 300 ms.

### F5 — CI/CD completo y documentación

Tareas:
1. `ci.yml` (PR y push): web (`npm ci`, `lint`, `tsc --noEmit`, `next build`), python (`ruff`, `python -m compileall`, `python main.py --list`), SQL (`db/bigquery/apply.py --dry-run` contra el proyecto real, sólo lectura), Terraform (`fmt -check`, `validate`).
2. Filtros de paths para que cada deploy corra sólo cuando cambia su carpeta (`web/**`, `sync/**|main.py`, `db/**`, `infra/**`).
3. GitHub *environment* `prod` con aprobación requerida para `infra-apply` y `run-sync`.
4. Secrets/vars de GitHub: **sólo** `GCP_PROJECT_ID`, `GCP_REGION`, `GCP_WIF_PROVIDER`, `GCP_DEPLOY_SA`. Ninguna credencial de SQL Server ni de BigQuery pasa por GitHub.
5. Documentación: `README.md` (stack, layout), `HANDOFF.md` (la corrida mensual pasa a "ejecutar `run-sync` en Actions o esperar el Scheduler"; troubleshooting nuevo: job failed, VPN caída, Identity Platform), `docs/GCP_RUNBOOK.md` (operación día a día, costos esperados, cómo rotar secretos), actualizar `LINEAGE.md` cambiando "Supabase" por "BigQuery" (mismos nombres de objetos). Marcar `PLAN_SQL_SINGLE_SOURCE.md` como histórico.

### F6 — Corte y retiro

1. **Congelar** la corrida legacy (Supabase) después de la última corrida en paralelo validada.
2. **Importar usuarios** a Identity Platform (bcrypt) y avisar al equipo (no cambian contraseña).
3. **Dominio**: mapear el dominio actual a `afp-web` (Cloud Run domain mapping o Load Balancer HTTPS si se requiere Cloud Armor/IAP más adelante); bajar el TTL del DNS antes.
4. **Cutover**: cambiar DNS; monitorear 5xx y latencia 48 h; Vercel queda como rollback pasivo 2 semanas.
5. **Retiro**: pausar y luego eliminar el proyecto Supabase (previo `pg_dump` completo con datos a `${PROJECT}-afp-artifacts/supabase-final/`), eliminar el proyecto en Vercel, revocar service-role key, limpiar `.env.example` de variables Supabase.
6. Cerrar este plan con la sección "Progreso" al estilo de `PLAN_SQL_SINGLE_SOURCE.md`.

---

## 6. Mapeo objeto por objeto

### 6.1 Tablas escritas por el pipeline

| Tabla (mismo nombre) | Dataset | Estrategia hoy | Estrategia BigQuery | Partición / cluster |
|---|---|---|---|---|
| `cotizantes_afp` | `afp_raw` | DELETE `fecha >= w` + INSERT | `DELETE … WHERE fecha >= @w` + load append | `fecha` mensual |
| `tipo_cambio` | `afp_raw` | UPSERT `(fecha, instrumento_codigo)` | `MERGE` vía staging | `fecha` mensual |
| `valores_cuota_patrimonio` | `afp_raw` | UPSERT `(fecha, multifondo, afp)` | `MERGE` vía staging | `fecha` mensual / `afp, multifondo` |
| `sd_asset_class_tipo`, `sd_asset_class_afp` | `afp_raw` | DELETE por fecha + INSERT | `DELETE … WHERE fecha IN UNNEST(@fechas)` + load append | `fecha` mensual |
| `consolidated_sd` | `afp_raw` | DELETE por fecha + INSERT | ídem | `fecha` mensual / `tipo_fondo` |
| `chist_adjusted` | `afp_raw` | DELETE por fecha + INSERT | ídem | `fecha` mensual / `afp, tipo_de_fondo` |
| `bbg_returns` | `afp_raw` | DELETE + INSERT | ídem | `end_date` mensual |
| `ipd_cartera_eom`, `ipd_attribution_monthly`, `ipd_attribution_fund_month`, `ipd_rentabilidades`, `ipd_bms_membership` | `afp_raw` | DELETE-all + INSERT | load `WRITE_TRUNCATE` | `fecha` mensual donde exista |
| `dim_afp_equivalencias`, `dim_tipo_instrumento_filtro`, `dim_bd_funds`, `dim_bd_asset_class`, `dim_bd_category`, `dim_bd_region`, `dim_bd_ac_reg_cat`, `dim_bd_family`, `dim_bd_family_comp`, `dim_bd_direct_inv_lics`, `dim_homol_funds`, `dim_tipo_instrumento_sp`, `dim_rel_feeder_master` | `afp_dim` | UPSERT full reload | `MERGE` vía staging (misma clave) | — |
| `dim_bd_previa` | `afp_dim` | reload completo | load `WRITE_TRUNCATE` | — |

### 6.2 Tablas manuales / seeds (sin fuente SQL Server)

| Tabla | Origen del dato | Destino | Cómo se mantiene después |
|---|---|---|---|
| `dim_valorizacion_remanente`, `dim_chilean_ticker_homol`, `dim_chilean_stocks_gics_override`, `dim_foreign_region_override`, `dim_distributor_by_manager`, `dim_strategy_ipd_funds` | export Supabase (F0) → `db/seeds/*.csv` | `afp_dim` | editar el CSV en un PR → `deploy-bq.yml` recarga (`--replace`). **Gana trazabilidad** respecto a editar en el panel de Supabase |
| `dim_sec08_top_flows`, `dim_bdchile`, `dim_direct_investment_overlay`, `dim_foreign_classification_overlay` | export Supabase (F0) (los `load_*.py` legacy leen JSON/Excel gitignorados) | `afp_dim` | ídem |
| `dim_data_sources` | export Supabase (F0) | `afp_dim` | ídem; `last_loaded_at` lo puede actualizar `apply.py` al recargar seeds |

### 6.3 Objetos leídos por la web

| Objeto | Tipo hoy | Tipo en BigQuery | DDL de partida |
|---|---|---|---|
| `v_aum`, `v_nav`, `v_uncalled`, `v_total`, `v_total_c1`, `v_afp_c1`, `v_afp_c2` | vista sobre `mv_chist_aa` / `mv_aum` | vista sobre tablas `mv_chist_aa` / `mv_aum` | `sync/mv_alternatives_materialize.sql` + dump |
| `v_afp_multifondo` | vista | vista | `sync/v_afp_multifondo.sql` |
| `v_asset_class_tipo_sd`, `v_asset_class_afp_sd` | vista | vista | `sync/v_asset_class_sd_alternatives.sql` |
| `v_asset_class_dates_sd`, `v_local_fi_by_afp_sd` | vista | vista | **dump** |
| `v_returns_afp_tipo` | vista → `mv_returns_afp_tipo` → `v_cuota_month_end` + `v_daily_flows` | vista → tabla `mv_returns_afp_tipo` → vistas | **dump** |
| `v_contributors_market_share` | vista | vista | **dump** |
| `v_foreign_pdf_summary_combined`, `v_foreign_managers_combined` | vista | vista | `sync/v_foreign_consolidated_switch.sql`, `sync/nt_taxonomy_foreign_views.sql` + dump |
| `v_foreign_returns_flows_summary`, `v_foreign_fund_flows` | vista → matview | vista → tabla `mv_*` | **dump** |
| `mv_sp_direct_investment_detail` | matview | tabla | `sync/v_foreign_di_switch.sql` |
| `mv_foreign_latam_monthly`, `mv_chist_chilean_stocks_by_nemo` | matview | tabla | **dump** |
| `mv_strategy_afp_ow_uw` | matview | tabla | `sync/mv_strategy_afp_ow_uw.sql` |
| `v_sp_strategy_aum` | vista | vista | `sync/v_strategy_switch.sql` |
| `v_local_equity_di_vs_if_combined` | vista | vista | **dump** |
| `v_chilean_stocks_gics` | vista | vista | `sync/chilean_stocks_gics_override.sql`, `sync/v_chilean_stocks_switch.sql` |
| `v_distributors_sec09` | vista | vista | `sync/v_distributors_*.sql` |
| `v_module_freshness` | vista | vista (posible apoyo en `afp_ops.run_log`) | `sync/v_module_freshness_add_strategy_afp_owuw.sql` + dump |
| `f_sec05_size`, `f_sec05_ipsa_membership`, `f_sec05_concentration`, `f_sec05_top40` | función SQL (RPC) | **table function** | **dump** (`pg_get_functiondef`) |
| `refresh_alternatives_matviews` | función plpgsql | paso `marts` del job (`refresh_order.txt`) | `sync/mv_alternatives_materialize.sql` |
| `tipo_cambio`, `valores_cuota_patrimonio`, `dim_bd_family`, `dim_data_sources`, `dim_distributor_by_manager`, `dim_sec08_top_flows`, `dim_strategy_ipd_funds`, `ipd_*` | tabla | tabla | §6.1 / §6.2 |

---

## 7. Guía de traducción Postgres → BigQuery

Constructos encontrados en los `sync/*.sql` (frecuencia entre paréntesis) y su equivalente:

| Postgres | BigQuery | Nota |
|---|---|---|
| `x::text` (210), `::varchar` (68), `::character` (12) | `CAST(x AS STRING)` | |
| `::numeric` (39), `numeric(p,s)` | `NUMERIC` (38,9) para montos/valores; `FLOAT64` para ratios y retornos | Mantener `NUMERIC` en columnas que hoy son `numeric` para paridad; validar sumas en §12 |
| `::date` (34), `::timestamp(tz)` | `CAST(x AS DATE)`, `TIMESTAMP` | Las fechas del dominio son `DATE` |
| `::double` (10) | `FLOAT64` | |
| `::interval` (7), `fecha - interval '1 month'` | `DATE_SUB(fecha, INTERVAL 1 MONTH)` | |
| `date_trunc('month', f)` (6) | `DATE_TRUNC(f, MONTH)` | orden de argumentos invertido |
| `to_char(f, 'YYYY-MM')` (8) | `FORMAT_DATE('%Y-%m', f)` | |
| `DISTINCT ON (k) … ORDER BY k, o` (7) | `… QUALIFY ROW_NUMBER() OVER (PARTITION BY k ORDER BY o) = 1` | |
| `LATERAL` (2) | `CROSS JOIN UNNEST(…)` o subconsulta correlacionada | caso a caso |
| `agg(x) FILTER (WHERE c)` (2) | `agg(IF(c, x, NULL))` / `COUNTIF(c)` | |
| `split_part(s, d, n)` (2) | `SPLIT(s, d)[SAFE_OFFSET(n-1)]` | |
| `COALESCE`, `NULLIF`, `ROW_NUMBER` | iguales | |
| `CREATE INDEX` (26) | no existe → `PARTITION BY` / `CLUSTER BY` | |
| `CREATE MATERIALIZED VIEW` (19) | `CREATE OR REPLACE TABLE … AS SELECT` en `marts/` | D4 |
| `CREATE FUNCTION … RETURNS TABLE … LANGUAGE sql` | `CREATE OR REPLACE TABLE FUNCTION` | parámetros con nombre `p_*` |
| `LANGUAGE plpgsql`, `SECURITY DEFINER`, `GRANT`, RLS | no aplica | permisos vía IAM |
| Identificadores `public.x` | `` `${project}.afp_mart.x` `` | `apply.py` sustituye `${project}` |
| División entera / `numeric` division | `SAFE_DIVIDE` sólo donde hoy hay `NULLIF(den,0)`; no cambiar semántica de NULL vs 0 | |
| Comparación de strings | BigQuery es case-sensitive como Postgres; `TRIM` explícito donde Postgres tenía `char(n)` con padding | riesgo real en joins por `nemo`/`afp` |

Regla: la traducción es **1:1 en semántica**; si un cambio "mejoraría" la vista, se anota en §14 y no se hace.

---

## 8. Diseño de la web sobre BigQuery

### 8.1 `web/lib/db.ts`

```ts
import 'server-only';
import { BigQuery } from '@google-cloud/bigquery';
import { unstable_cache } from 'next/cache';

export const BQ_CACHE_TAG = 'bq';
const REVALIDATE_S = 300;                       // mismo TTL que supabase-server.ts
const bq = new BigQuery({ location: process.env.BQ_LOCATION });
export const MART = `\`${process.env.GCP_PROJECT_ID}.${process.env.BQ_DATASET_MART ?? 'afp_mart'}\``;
export const DIM  = `\`${process.env.GCP_PROJECT_ID}.${process.env.BQ_DATASET_DIM  ?? 'afp_dim'}\``;
export const RAW  = `\`${process.env.GCP_PROJECT_ID}.${process.env.BQ_DATASET_RAW  ?? 'afp_raw'}\``;

export function query<T>(sql: string, params: Record<string, unknown> = {}): Promise<T[]> {
  const run = unstable_cache(
    async () => { const [rows] = await bq.query({ query: sql, params }); return rows as T[]; },
    ['bq', sql, JSON.stringify(params)],
    { revalidate: REVALIDATE_S, tags: [BQ_CACHE_TAG] },
  );
  return run();
}
```

### 8.2 Patrón de reescritura (ejemplo real, `queries.ts::getOverview`)

Hoy: 4 llamadas PostgREST en `Promise.all` y un merge en TS. Mañana: las mismas 4 consultas SQL en `Promise.all` y **el mismo merge en TS**, sin tocar el resto:

```ts
const [aum, nav, unc, tot] = await Promise.all([
  query<{afp: string; aum_usd_mm: number}>(`SELECT afp, aum_usd_mm FROM ${MART}.v_aum WHERE fecha = @fecha`, { fecha }),
  query<…>(`SELECT afp, nav_usd_mm FROM ${MART}.v_nav WHERE fecha = @fecha`, { fecha }),
  …
]);
```

Tipos: BigQuery devuelve `DATE` como `{ value: 'YYYY-MM-DD' }` y `NUMERIC` como string; `db.ts` expone `toDateStr()` y `toNum()` y cada query los aplica en el mismo lugar donde hoy hace `Number(r.x)` / `r.fecha as string`. Así los tipos exportados (`types-*.ts`) no cambian.

RPC: `supabase.rpc('f_sec05_size', {p_fecha, …})` → `query(\`SELECT * FROM ${MART}.f_sec05_size(@p_fecha, …)\`, {...})`.

### 8.3 Caché y coherencia

- Se conservan `export const revalidate = 3600` por página y el TTL 300 s de datos.
- El job llama `POST /api/revalidate` al terminar; con `min-instances=1` la invalidación llega a la instancia caliente. Si hay más instancias, expiran solas a los 300 s / 3600 s (mismo comportamiento que hoy sin redeploy).
- Costo BigQuery: las vistas leen tablas de MB; con caché de 300 s y ~40 consultas por render, el consumo mensual queda muy por debajo de 1 TB gratis. Se revisa en F4.8 con `INFORMATION_SCHEMA.JOBS`.
- Latencia: BigQuery ~0,4–1,5 s por consulta en frío vs ~250 ms PostgREST. Compensado por caché y paralelismo; si una página supera 3 s en frío se evalúa BI Engine (reserva mínima 1 GB) **sin cambiar código**.

### 8.4 Auth (Identity Platform)

- Cookie `__session` httpOnly, `Secure`, `SameSite=Lax`, 12 h (configurable), creada con `admin.auth().createSessionCookie(idToken, {expiresIn})`.
- `proxy.ts` verifica con `verifySessionCookie(cookie, /*checkRevoked*/ false)`; cache in-memory 60 s por valor de cookie (idéntico al actual). Requiere runtime Node (Next 16 `proxy.ts` corre en Node por defecto).
- `login()` llama a `https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=…` server-side; los mensajes de error se mapean a los textos que hoy muestra `/login?error=`.
- Sin registro self-service (igual que hoy); usuarios se crean en la consola de Identity Platform o con `gcloud identity-platform`.

---

## 9. Diseño del pipeline

### 9.1 Contenedor

```
sync/Dockerfile
  FROM python:3.12-slim-bookworm
  RUN curl https://packages.microsoft.com/keys/microsoft.asc … && apt-get install -y msodbcsql18 unixodbc
  COPY sync/requirements.txt . && pip install --no-cache-dir -r requirements.txt
  COPY main.py . && COPY sync/ sync/
  ENV TQDM_DISABLE=1 PYTHONUNBUFFERED=1
  ENTRYPOINT ["python", "main.py"]
```

### 9.2 `sync/bq_io.py` — contrato

| Función | Reemplaza a | Implementación |
|---|---|---|
| `connect_bigquery()` | `connect_supabase()` | `bigquery.Client(project, location)` con ADC |
| `bq_insert(client, table, df, batch_size=…, show_progress=…)` | `supabase_insert` | `load_table_from_dataframe(df, dest, WRITE_APPEND)` (parquet); `batch_size` se ignora |
| `bq_upsert(client, table, df, on_conflict, …)` | `supabase_upsert` | dedupe en pandas (igual que hoy) → load a `afp_stg.<table>_<uuid>` → `MERGE dest USING stg ON keys WHEN MATCHED THEN UPDATE SET … WHEN NOT MATCHED THEN INSERT ROW` → drop stg |
| `bq_delete_in(client, table, col, values)` | `supabase_delete_in` | `DELETE FROM dest WHERE col IN UNNEST(@values)`; devuelve `num_dml_affected_rows` |
| `bq_replace(client, table, df, pk_col)` | `supabase_replace` (ipd) | `load_table_from_dataframe(…, WRITE_TRUNCATE)` |
| `get_last_date(client, table, col)` | `get_last_date` | `SELECT MAX(col)` |
| `refresh_marts(client, names)` | `rpc('refresh_alternatives_matviews')` | ejecuta `db/bigquery/marts/<name>.sql` en orden (los `.sql` se copian a la imagen) |
| `log_run(client, step, started, finished, rc, rows)` | — (nuevo) | insert en `afp_ops.run_log` |

Resolución de dataset por tabla: `dim_*` → `afp_dim`; resto → `afp_raw`; override por env para pruebas.

### 9.3 Operación

- **Scheduler** (D6) ejecuta `main.py` sin flags. Corridas ad-hoc: `run-sync.yml` o `gcloud run jobs execute afp-sync --args="--only,chist_adjusted"`.
- **Logs**: stdout del script → Cloud Logging; el resumen final de `main.py` es la última entrada. `run_log` alimenta un panel simple y `v_module_freshness` puede exponer `last_run_at`.
- **Fallo**: alerta por correo; se relanza el paso con `--only` (idempotente). No hay reintentos automáticos para no duplicar tiempo de `ipd_strategy`.
- **Secretos**: rotación = actualizar versión en Secret Manager + nueva ejecución (el job lee `latest`).

---

## 10. CI/CD en GitHub Actions

### 10.1 Workflows

| Archivo | Disparo | Qué hace |
|---|---|---|
| `.github/workflows/ci.yml` | PR y push a cualquier rama | web: `npm ci && npm run lint && npx tsc --noEmit && npm run build`; python: `ruff check`, `compileall`, `python main.py --list`; sql: `db/bigquery/apply.py --dry-run`; terraform: `fmt -check`, `validate` |
| `deploy-web.yml` | push a `main` con cambios en `web/**`; PR (preview `--no-traffic --tag pr-N`) | build → Artifact Registry → `gcloud run deploy afp-web` |
| `deploy-sync.yml` | push a `main` con cambios en `sync/**`, `main.py`, `db/bigquery/marts/**` | build → Artifact Registry → `gcloud run jobs update afp-sync` |
| `deploy-bq.yml` | push a `main` con cambios en `db/**` | `apply.py` (tables → seeds → views → functions) |
| `run-sync.yml` | `workflow_dispatch` (inputs) | `gcloud run jobs execute afp-sync --args … --wait` + resumen |
| `infra-plan.yml` / `infra-apply.yml` | PR en `infra/**` / `workflow_dispatch` con environment `prod` | `terraform plan` (comentario en PR) / `terraform apply` |

Todos autentican con `google-github-actions/auth@v2` (WIF, `id-token: write`), sin llaves.

### 10.2 Secrets / variables de GitHub

`GCP_PROJECT_ID`, `GCP_REGION`, `GCP_WIF_PROVIDER` (`projects/N/locations/global/workloadIdentityPools/afp-github/providers/github`), `GCP_DEPLOY_SA` (`afp-github-deploy@…`). Nada más.

### 10.3 Roles IAM (mínimo privilegio)

| SA | Roles |
|---|---|
| `afp-github-deploy` | `run.admin`, `iam.serviceAccountUser` (sobre `afp-web-run` y `afp-sync-run`), `artifactregistry.writer`, `bigquery.jobUser`, `bigquery.dataEditor` **sólo** en datasets `afp_*`, `storage.objectAdmin` en bucket tfstate, `secretmanager.viewer`; para Terraform además `roles/editor` acotado o los roles específicos de los recursos que administra |
| `afp-web-run` | `bigquery.jobUser`, `bigquery.dataViewer` en `afp_mart` y `afp_dim` (y `afp_raw` sólo por `tipo_cambio`/`valores_cuota_patrimonio`, o se exponen como vistas en `afp_mart`), `secretmanager.secretAccessor` en sus secretos, `firebaseauth.admin` (Identity Platform) |
| `afp-sync-run` | `bigquery.jobUser`, `bigquery.dataEditor` en `afp_raw`, `afp_dim`, `afp_mart`, `afp_ops`, `afp_stg`, `secretmanager.secretAccessor` en sus secretos, `run.invoker` (para que Scheduler lo use) |

---

## 11. Estructura final del repo

```
.
├── .github/workflows/         ci.yml · deploy-web.yml · deploy-sync.yml · deploy-bq.yml · run-sync.yml · infra-plan.yml · infra-apply.yml
├── main.py                    (sin cambios funcionales; + run_log + revalidate)
├── sync/                      (scripts intactos; + bq_io.py, Dockerfile, .dockerignore; − dependencia supabase)
├── db/
│   ├── supabase_snapshot/     schema.sql · deps.csv        (referencia histórica, F0)
│   ├── seeds/                 *.csv · README.md · export_from_supabase.py
│   └── bigquery/              apply.py · tables/ · views/ · marts/ (+ refresh_order.txt) · functions/
├── validation/                snapshot_supabase.py · compare_bq_vs_supabase.py · baseline_supabase/ · reports/ · ui_parity_checklist.md
├── infra/terraform/           main.tf · datasets.tf · iam.tf · run.tf · network.tf · scheduler.tf · secrets.tf · idp.tf · wif.tf · variables.tf
├── web/                       (app/ y components/ intactos; lib/db.ts, lib/auth-server.ts, queries-*.ts reescritas; app/api/revalidate/route.ts; Dockerfile; next.config.ts standalone)
├── docs/GCP_RUNBOOK.md
├── README.md · HANDOFF.md · LINEAGE.md   (actualizados)
└── PLAN_MIGRACION_GCP.md      (este documento, con sección Progreso)
```

Se eliminan al final de F6: `web/lib/supabase-*.ts`, variables `SUPABASE_*` de los `.env.example`, `sync/refresh_mv.py` (reemplazado por `refresh_marts`). Los scripts `sync/sync_sp_xml.py`, `sync_sp_cotizantes.py`, `load_*.py`, `inspect_*.py` se conservan como referencia (igual que hoy) sin portarlos.

---

## 12. Validación y criterios de corte

**Paridad de datos** (`validation/compare_bq_vs_supabase.py`), por objeto y por `fecha` (últimas 3 fechas disponibles + 2 fechas históricas fijas, p. ej. `2025-06-30` y `2025-12-31`):

| Métrica | Tolerancia |
|---|---|
| `COUNT(*)` por fecha | exacto |
| Conjunto de claves (`afp`, `tipo_de_fondo`, `nemo`, …) por fecha | exacto |
| Sumas de columnas `*_usd_mm`, `*_clp`, `aum`, `nav`, `uncalled`, `total`, `pct_*` | `abs diff ≤ 1e-6` relativo (NUMERIC) o `≤ 1e-9` absoluto en porcentajes (FLOAT64) |
| Funciones `f_sec05_*` con los parámetros que usa la web | mismas filas, mismo orden |
| `v_module_freshness` | mismas `as_of_date` por módulo |

Resultado `[OK]`/`[WARN]` (diferencia explicada por redondeo de tipo) /`[FAIL]`. **No se corta con ningún `[FAIL]`.**

**Paridad de UI**: checklist por ruta y fecha; mismos KPIs, mismas filas en tablas, mismos badges "as of".

**Operativa**: 1 ciclo mensual completo corrido por el Scheduler en GCP con `OK` en 8/8 pasos y revalidación de la web funcionando.

**Seguridad**: ninguna credencial en GitHub, imágenes sin secretos (`docker history`), `afp-web` no expone nada bajo `/api` sin token, Identity Platform con enumeración de emails desactivada.

---

## 13. Riesgos y mitigaciones

| Riesgo | Impacto | Mitigación |
|---|---|---|
| **Redes Patria no aprueba VPN a tiempo** | Bloquea F3 (ejecución en GCP) | Pedirlo en F0; F2/F4 avanzan con backfill desde laptop; contingencia D1(c) transitoria |
| **Vistas sin DDL en repo mal reconstruidas** | Números distintos | Dump canónico en F0; traducción 1:1; paridad automatizada por objeto |
| **Diferencias sutiles Postgres vs BigQuery** (`char(n)` padding, `numeric` vs float, orden de `NULL`, collation) | `[FAIL]` en paridad | Guía §7; `TRIM` explícito; `NUMERIC` donde hoy hay `numeric`; `ORDER BY … NULLS LAST` explícito |
| **Latencia BigQuery en páginas con muchas consultas** | UX más lenta que Vercel | Caché 300 s/3600 s, `min-instances=1`, warm-up post-job; BI Engine como palanca sin código |
| **Cloud Run Job > 1 h** (`ipd_strategy` con pandas) | Timeout | Timeout 3 h, 2 vCPU/4 GiB; medir en la primera corrida y ajustar |
| **Usuarios pierden acceso en el corte** | Operación | Importar hashes bcrypt (mantienen contraseña); comunicar; Vercel como rollback 2 semanas |
| **Costo inesperado** | Presupuesto | BigQuery bajo 1 TB/mes de consultas y < 5 GB almacenados; Cloud Run min 1 instancia ≈ USD 10–15/mes; VPN HA ≈ USD 70/mes (el ítem mayor). Budget alert `afp-budget` en Terraform |
| **Mezcla con otros recursos del proyecto** | Gobernanza | Prefijo `afp-`, labels, SAs propias, Terraform sólo sobre `afp-*` |
| **Drift entre `sync/*.sql` históricos y BigQuery** | Confusión futura | `db/bigquery/` pasa a ser la única fuente de DDL; `sync/*.sql` se mueve a `db/supabase_snapshot/migrations_legacy/` en F6 |

---

## 14. Fuera de alcance (explícito)

- Ampliar ventanas de datos (p. ej. `chist_adjusted` full-history ahora que no hay tope de 500 MB).
- Cambios de UI, nuevos módulos, cerrar los 🚧 de Chilean Stocks / Distributors, `Ajustes_Dashboard.md`.
- Migrar SQL Server a Cloud SQL / traer los procesos del equipo IM a GCP (SQL Server **sigue siendo la fuente de verdad on-prem**).
- Revivir los scrapers de spensiones.cl.
- IAP / SSO corporativo (queda documentado como evolución natural sobre D2).
- Ambientes `dev`/`staging` completos (sólo previews de la web por PR).

---

## 15. Preguntas abiertas para el equipo

Resueltas el 2026-09-28: proyecto `pat-uat-global` (UAT), región `southamerica-west1`, URLs `*.run.app` sin dominio propio, sin VPN (Cloud NAT + IP fija allowlisteada en el SQL Server; imagen portable como respaldo).

Siguen abiertas:
1. Confirmar D2: Identity Platform (requiere que infra habilite la API y cree la API key) vs fallback "servicio público + login propio" ya usado por el equipo.
2. Lista definitiva de usuarios del dashboard (base: los 5 correos de la consola Geneva).
3. Mecanismo de auth para GitHub Actions: WIF (recomendado) o gates en Actions + deploy por Cloud Build triggers. Ambos requieren una acción única de infra (ticket en `infra/README.md`).
4. Presupuesto mensual aceptable (sin dato; estimación en `docs/GCP_RUNBOOK.md`).
5. Quién carga el primer valor de los secretos `afp-sqlserver-*` y quién pide el allowlist de la IP NAT al dueño del SQL Server.

---

## Progreso

- 2026-09-28 — Levantamiento completo del repo y redacción de este plan (rama `claude/migracion-gcp-9w4y80`). Pendiente: aprobación y cierre de D1–D7 para arrancar F0.
- 2026-09-28 — Revisión del repo `IgnacioF1988/geneva` (app hermana en GCP): resueltas región y proyecto, conectividad on-prem confirmada inexistente, D1/D2/D7 reformuladas, F1 pasa a scripts idempotentes, ticket único a infra definido (§4.1).
- 2026-09-28 — Decisiones del usuario: UAT (`pat-uat-global`), URLs por defecto de Cloud Run, sin VPN. D1 resuelta con Cloud NAT + IP fija e imagen portable. Arranca la ejecución: `sync/` → BigQuery, `web/` → BigQuery + Identity Platform + Docker, `db/bigquery/` + `validation/`, `infra/` + `.github/workflows/` + runbook.
