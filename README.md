# AFP Chile Dashboard

Dashboard Next.js que reproduce el reporte mensual del sistema de pensiones de Chile
(10 secciones, ~48 páginas PDF) para el equipo de Sales/Distribution. Datos desde el
SQL Server `Inteligencia_Mercado` (fuente de verdad, red Patria) espejados a BigQuery por
un pipeline Python mensual.

> **Migración a GCP en curso (2026-09)**: el destino es Cloud Run + BigQuery en el proyecto
> `pat-uat-global`. Hasta el corte, el flujo legacy (laptop + Supabase + Vercel) sigue
> vigente y está documentado en `HANDOFF.md`. Plan: `PLAN_MIGRACION_GCP.md`; operación en
> GCP: `docs/GCP_RUNBOOK.md`.

## Stack

- **Frontend**: Next.js 16, React 19, Tailwind, Recharts, shadcn/ui — en **Cloud Run** (`afp-web`, imagen `afp/web`)
- **Datos**: **BigQuery** (`afp_raw`, `afp_dim`, `afp_mart`, `afp_ops`, `afp_stg`), leído con `@google-cloud/bigquery` y SQL parametrizado
- **Auth**: **Identity Platform** (email + contraseña), sesión en cookie firmada verificada en `proxy.ts`
- **Sync**: Python (`main.py` + `sync/*.py`, pyodbc + ODBC Driver 18) empaquetado como **Cloud Run job** (`afp-sync`), disparado por Cloud Scheduler (días 8 y 18) o a mano desde GitHub Actions
- **Esquema**: DDL de BigQuery versionado en `db/bigquery/`, aplicado por `db/bigquery/apply.py`
- **CI/CD**: **GitHub Actions** con Workload Identity Federation (sin llaves JSON); infra con scripts `gcloud` idempotentes en `infra/`

## Layout del repo

```
web/            Next.js dashboard (la UI); web/Dockerfile (puerto 8080)
sync/           Scripts Python del pipeline SQL Server -> BigQuery; sync/Dockerfile (imagen del job)
main.py         Orquestador mensual (8 pasos idempotentes; flags --list/--only/--start/--months-back/--skip-strategy/--keep-going)
db/             Esquema BigQuery versionado: bigquery/{tables,views,marts,functions}, apply.py, seeds/, supabase_snapshot/
validation/     Paridad BigQuery vs Supabase (baseline, comparadores, checklist de UI)
infra/          setup-afp.sh (idempotente), diagnostico-iam.sh, README con el ticket a infra
.github/        Workflows: ci, deploy-web, deploy-sync, deploy-bq, run-sync
docs/           GCP_RUNBOOK.md (operación en GCP)
```

## Secciones del dashboard

| Sección | Tema | Estado |
|---|---|---|
| Alternative Assets | Cubos legacy de alternativos (NAV / Uncalled / Total por AFP) | ✅ |
| Market Share (01) | AUM / Retornos / Flujos / Cotizantes por AFP × fondo | ✅ |
| Asset Allocation (02·03) | Local vs Foreign × asset class × AFP × tipo de fondo | ✅ |
| Strategy (04) | Estrategias Moneda + market share de pares | ✅ |
| Foreign Investment (07) | Inversión extranjera por región / asset class | ✅ |
| Chilean Stocks (05·06) | Cartera + Transacciones | 🚧 |
| Distributors (09) | Desglose por distribuidor / manager | 🚧 |

## Correr la web en local

Necesita credenciales de Google con lectura de BigQuery (`bigquery.jobUser` + READER en
`afp_mart`/`afp_dim`/`afp_raw`), vía **Application Default Credentials**:

```bash
gcloud auth login
gcloud auth application-default login
cd web
cp .env.example .env.local     # GCP_PROJECT_ID, BQ_LOCATION, BQ_DATASET_*, NEXT_PUBLIC_IDP_API_KEY, REVALIDATE_TOKEN
npm install
npm run dev                    # http://localhost:3000
```

Imagen igual a la de Cloud Run: `docker build -f web/Dockerfile -t afp/web web && docker run -p 8080:8080 --env-file web/.env.local afp/web`.

## Correr el sync en local

Debe ejecutarse desde una red que alcance el SQL Server (oficina o VPN de Patria). Escribe a
BigQuery por HTTPS/443 con ADC:

```bash
cp .env.example .env           # DB_* (SQL Server) + GCP_PROJECT_ID + BQ_LOCATION (+ WEB_URL / REVALIDATE_TOKEN opcionales)
gcloud auth application-default login
pip install -r sync/requirements.txt      # + ODBC Driver 18 for SQL Server instalado en el sistema

python main.py --list                     # ver el plan sin ejecutar
python main.py                            # corrida mensual completa
python main.py --only chist_adjusted      # un solo paso
python main.py --start 2020-01-01         # backfill / ventana explícita
```

Con la imagen del job (misma que corre en Cloud Run, sirve como respaldo on-prem):
`docker build -f sync/Dockerfile -t afp/sync . && docker run --rm --env-file .env -v ~/.config/gcloud:/root/.config/gcloud:ro afp/sync --list`.
Detalle en `docs/GCP_RUNBOOK.md` §7.

## Operación en GCP (resumen)

- **Corrida mensual**: Cloud Scheduler `afp-sync-monthly` (días 8 y 18, 07:00 America/Santiago) o workflow **run-sync** en GitHub Actions con los mismos flags de `main.py`.
- **Deploys**: push a `main` → `deploy-web` (web/), `deploy-sync` (sync/, main.py, marts), `deploy-bq` (db/). PRs generan una preview de la web sin tráfico.
- **Infra**: `bash infra/diagnostico-iam.sh` → ticket a infra (`infra/README.md`) → `bash infra/setup-afp.sh`.

## Notas de arquitectura

- SQL Server es la **fuente de verdad** con historia completa; BigQuery es el espejo que consume la web (mismas ventanas y filtros que hoy; no se amplían en esta migración).
- La estrategia de escritura por tabla es deliberada (DELETE por fecha + INSERT para las tablas por fecha, MERGE para valores y dimensiones, WRITE_TRUNCATE para `ipd_*`), y todos los pasos son idempotentes: relanzar nunca duplica.
- Cada cubo del reporte vive en una vista `v_<cubo>` (ahora en `afp_mart`); las matviews `mv_*` son tablas reconstruidas por el job; las RPC `f_sec05_*` son table functions. Mismos nombres que en Supabase, así `LINEAGE.md` sigue siendo válido.
- El job sale a internet por **Cloud NAT con IP fija** (`afp-nat-ip`), allowlisteada en el firewall del SQL Server; no hay VPN. Si el allowlist no está, la misma imagen corre on-prem.
- **Legacy (hasta el corte)**: el sync escribía en Supabase vía REST (los puertos Postgres están bloqueados en la red corporativa) y la web se desplegaba en Vercel. Ver `HANDOFF.md`.
