# GCP_RUNBOOK — Operación del dashboard AFP en Google Cloud

Operación día a día una vez migrado (plan en `PLAN_MIGRACION_GCP.md`; andamiaje y ticket a
infra en `infra/README.md`). Proyecto **`pat-uat-global`**, región **`southamerica-west1`**.

| Pieza | Nombre | Dónde mirar |
|---|---|---|
| Web | Cloud Run service `afp-web` → `https://afp-web-<hash>-<region>.a.run.app` | Consola → Cloud Run → Services |
| Pipeline | Cloud Run job `afp-sync` (imagen `afp/sync`, `ENTRYPOINT python main.py`) | Cloud Run → Jobs → Executions |
| Programación | Cloud Scheduler `afp-sync-monthly` — días **8 y 18**, **07:00 America/Santiago** | Cloud Scheduler |
| Datos | BigQuery `afp_raw`, `afp_dim`, `afp_mart`, `afp_ops`, `afp_stg` | BigQuery Studio |
| Bitácora | `afp_ops.run_log` (paso, inicio, fin, rc, filas) | BigQuery |
| Secretos | `afp-sqlserver-*`, `afp-web-revalidate-token`, `afp-idp-api-key` | Secret Manager |
| Egress del job | Cloud NAT `afp-nat` con IP fija `afp-nat-ip` (sin VPN) | VPC network → Cloud NAT |
| CI/CD | GitHub Actions (`ci`, `deploy-web`, `deploy-sync`, `deploy-bq`, `run-sync`) | GitHub → Actions |

```bash
# atajos usados en todo el runbook
P=pat-uat-global; R=southamerica-west1
gcloud config set project $P
WEB_URL=$(gcloud run services describe afp-web --region $R --format='value(status.url)')
```

---

## 1. Operación mensual

### 1.1 Automática (Scheduler)

El Scheduler dispara `afp-sync` **sin flags** (= `python main.py`) los días 8 y 18 a las 07:00.
Los 8 pasos son idempotentes, así que la segunda corrida recoge las fuentes que llegan tarde
(CHIST rezaga ~4 meses y ancla su ventana al `MAX(fecha)` de la fuente). No hay nada que
"cronometrar": si una fuente aún no tiene el mes, ese paso re-sincroniza lo ya cargado.

Ver la última ejecución programada:

```bash
gcloud scheduler jobs describe afp-sync-monthly --location $R --format='value(lastAttemptTime,status)'
gcloud run jobs executions list --job afp-sync --region $R --limit 5
```

Pausar / reanudar la programación (p. ej. durante la convivencia con Supabase):

```bash
gcloud scheduler jobs pause  afp-sync-monthly --location $R
gcloud scheduler jobs resume afp-sync-monthly --location $R
```

### 1.2 Manual (workflow `run-sync`)

GitHub → Actions → **run-sync** → *Run workflow*. Los inputs son los flags de `main.py`:

| Input | Flag | Cuándo |
|---|---|---|
| `only` | `--only chist_adjusted,bbg_returns` | relanzar un paso fallido o adelantar CHIST |
| `start` | `--start 2025-01-01` | ventana explícita (aplica también a CHIST) |
| `months_back` | `--months-back 6` | correcciones retroactivas más viejas |
| `skip_strategy` | `--skip-strategy` | corrida rápida sin `ipd_strategy` |
| `keep_going` | `--keep-going` | no parar en el primer fallo |
| `list` | `--list` | prueba de humo: imprime el plan y sale (no toca SQL Server ni BigQuery) |

El workflow espera a que el job termine y adjunta el log (resumen + artefacto). Equivalente
por CLI (ojo con el delimitador `^|^` cuando hay comas en los valores):

```bash
gcloud run jobs execute afp-sync --region $R --wait                                   # = python main.py
gcloud run jobs execute afp-sync --region $R --wait --args="^|^--only|chist_adjusted,bbg_returns"
gcloud run jobs execute afp-sync --region $R --wait --args="--skip-strategy,--months-back,6"
```

### 1.3 Verificación post-corrida

1. La ejecución termina `Succeeded` y el resumen final de `main.py` muestra `OK` en todos los pasos (§2).
2. `afp_ops.run_log` tiene una fila por paso con `rc = 0`:
   ```sql
   SELECT step, started_at, finished_at, rc, rows_written
   FROM `pat-uat-global.afp_ops.run_log`
   WHERE started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 DAY)
   ORDER BY started_at;
   ```
3. Frescura por módulo: `SELECT * FROM afp_mart.v_module_freshness` debe mostrar el mes nuevo
   (el techo lo pone la fuente en SQL Server, no el sync).
4. La web muestra los badges "as of" nuevos. El job llama `POST $WEB_URL/api/revalidate` al
   terminar; si no se refleja, esperar 5 min (TTL de datos 300 s) o forzar:
   ```bash
   curl -sS -X POST "$WEB_URL/api/revalidate" -H "x-revalidate-token: $(gcloud secrets versions access latest --secret afp-web-revalidate-token)"
   ```

---

## 2. Leer `run_log` y logs

**Logs de una ejecución** (stdout/stderr de `main.py` y de los scripts de `sync/`):

```bash
EXEC=$(gcloud run jobs executions list --job afp-sync --region $R --limit 1 --format='value(metadata.name)')
gcloud logging read "resource.type=\"cloud_run_job\" AND resource.labels.job_name=\"afp-sync\" AND labels.\"run.googleapis.com/execution_name\"=\"$EXEC\"" \
  --order asc --limit 2000 --format='value(timestamp,severity,textPayload)'
```

El **resumen final** de `main.py` (tabla `paso / OK|FAIL|SKIP / segundos`) es la última entrada
del log. Sólo errores:

```bash
gcloud logging read 'resource.type="cloud_run_job" AND resource.labels.job_name="afp-sync" AND severity>=ERROR' --freshness 2d --limit 50
```

En consola: Cloud Run → Jobs → `afp-sync` → pestaña *Executions* → la ejecución → *Logs*.

**`afp_ops.run_log`** es la bitácora estructurada (una fila por paso); sirve para ver
duración por paso a lo largo del tiempo:

```sql
SELECT step, DATE(started_at) d, TIMESTAMP_DIFF(finished_at, started_at, SECOND) s, rc, rows_written
FROM `pat-uat-global.afp_ops.run_log` ORDER BY started_at DESC LIMIT 40;
```

---

## 3. Si el job falla

Primero el síntoma en el log (§2); luego:

| Síntoma | Causa probable / acción |
|---|---|
| `Login timeout` / `TCP Provider: Error code 0x2749` contra SQL Server en todos los pasos | La IP NAT no está allowlisteada (o cambió el firewall). Verificar §6 y el ticket de `infra/README.md` §3. Mientras: corrida on-prem (§7). |
| `Login failed for user` | Credenciales `afp-sqlserver-uid/pwd` vencidas → rotar (§4) |
| `403 Access Denied: Dataset afp_*` | ACL del dataset perdida → `bash infra/setup-afp.sh` la re-aplica |
| Un paso `FAIL` y los siguientes `SKIP` | Comportamiento por defecto (sin `--keep-going`). Relanzar **sólo ese paso**: `run-sync` con `only=<paso>`; si es de ventana, luego correr los que quedaron `SKIP` con `only=a,b,c`. |
| `Container called exit(137)` / OOM | `ipd_strategy` con más datos de lo previsto. Subir memoria en `deploy-sync.yml` (`--memory 8Gi --cpu 4`) y redeploy. |
| Timeout a las 3 h | Igual: medir por paso en `run_log`; considerar `--skip-strategy` y correr `ipd_strategy` aparte. |
| Un paso escribe 0 filas | Normal si la fuente aún no tiene el mes (incremental). |
| La web sigue con el mes viejo tras corrida OK | `v_module_freshness`; revalidación (§1.3.4); revisar que `WEB_URL` y el token del job coincidan con los de la web (`gcloud run jobs describe afp-sync --format=yaml \| grep -A2 WEB_URL`). |

**Todo es idempotente**: relanzar un paso (o la corrida completa) nunca duplica datos
(DELETE por fecha + INSERT, o MERGE). No hay reintentos automáticos (`--max-retries 0`) a
propósito: un reintento ciego duplicaría el tiempo de `ipd_strategy` sin información nueva.

La alerta `AFP: job afp-sync falló` (Cloud Monitoring, métrica `afp_sync_failed`) avisa al canal
configurado en el setup (`NOTIFICATION_CHANNEL`). Si no se configuró, revisar el estado de las
ejecuciones tras cada día 8/18.

---

## 4. Secretos: primer valor y rotación

Los secretos nacen **vacíos** con `infra/setup-afp.sh`; el job y la web leen `latest` al
arrancar cada ejecución/instancia.

**Primer valor** (quien tenga el `.env` actual tiene los cuatro `DB_*`):

```bash
printf '%s' '<host>'        | gcloud secrets versions add afp-sqlserver-host --data-file=-
printf '%s' 'Inteligencia_Mercado' | gcloud secrets versions add afp-sqlserver-db --data-file=-
printf '%s' '<usuario>'     | gcloud secrets versions add afp-sqlserver-uid  --data-file=-
printf '%s' '<contraseña>'  | gcloud secrets versions add afp-sqlserver-pwd  --data-file=-
openssl rand -hex 32 | tr -d '\n' | gcloud secrets versions add afp-web-revalidate-token --data-file=-
printf '%s' '<API key IdP>' | gcloud secrets versions add afp-idp-api-key    --data-file=-
```

`printf '%s'` evita un salto de línea final (rompe la contraseña sin error visible).

**Rotación** = agregar una versión nueva y desactivar la anterior:

```bash
printf '%s' '<nueva contraseña>' | gcloud secrets versions add afp-sqlserver-pwd --data-file=-
gcloud secrets versions list afp-sqlserver-pwd
gcloud secrets versions disable <N-1> --secret afp-sqlserver-pwd
```

- **Job** (`afp-sync`): toma la versión nueva en la **siguiente ejecución**; no hay que redeployar.
- **Web** (`afp-web`): Cloud Run resuelve `latest` al **crear la instancia**; para forzar,
  `gcloud run services update afp-web --region $R --update-labels rotated=$(date +%s)` (crea una
  revisión nueva) o esperar al siguiente deploy. El `afp-web-revalidate-token` debe rotarse
  en ambos lados a la vez (job y web leen el mismo secreto, así que basta la nueva versión + revisión nueva de la web).
- Ver quién puede leer cada secreto: `gcloud secrets get-iam-policy afp-sqlserver-pwd`.

---

## 5. Deploys y CI

| Qué cambió | Workflow | Disparo |
|---|---|---|
| `web/**` | `deploy-web` | push a `main` (con tráfico); PR → preview `--no-traffic --tag pr-N` con URL en el PR |
| `sync/**`, `main.py`, `db/bigquery/marts/**` | `deploy-sync` | push a `main` (sólo redeploya el job; no lo ejecuta) |
| `db/**` | `deploy-bq` | push a `main` (`apply.py`); manual con `with_marts=true` para reconstruir `mv_*` |
| cualquier PR/push | `ci` | lint/tsc/build web, ruff/compileall/`main.py --list`, `apply.py --parse-check`, `docker build` ×2, `bash -n infra/*.sh` |

Todos autentican con WIF (`google-github-actions/auth@v2`) y el environment **`uat`**; los
únicos datos en GitHub son `vars.GCP_PROJECT_ID`, `vars.GCP_REGION`, `secrets.GCP_WIF_PROVIDER`,
`secrets.GCP_DEPLOY_SA`.

**Rollback web**: Cloud Run guarda revisiones; `gcloud run services update-traffic afp-web --region $R --to-revisions <rev>=100`.
**Rollback job**: `gcloud run jobs update afp-sync --region $R --image <imagen anterior>` (las imágenes quedan en Artifact Registry `afp/sync:<sha>`; se conservan las 10 más recientes).

### 5.1 Verificación post-deploy

```bash
# web
curl -sS -o /dev/null -w '%{http_code}\n' "$WEB_URL/login"          # 200
curl -sS -o /dev/null -w '%{http_code}\n' "$WEB_URL/"               # 307 -> /login sin cookie
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$WEB_URL/api/revalidate"   # 401 sin token
gcloud run services describe afp-web --region $R --format='value(status.latestReadyRevisionName,spec.template.spec.containers[0].image)'
# job
gcloud run jobs describe afp-sync --region $R --format='value(template.template.containers[0].image)'
gcloud run jobs execute afp-sync --region $R --wait --args="--list"   # humo: sólo imprime el plan
# esquema
python db/bigquery/apply.py --project $P --location $R --dry-run
```

Luego abrir las 9 rutas con login (`/`, `/asset-allocation`, `/market-share`, `/strategy`,
`/foreign`, `/managers`, `/chilean-stocks`, `/distributors`, `/admin/data-sources`) y comparar
con la checklist de `validation/`.

---

## 6. La IP NAT (allowlist en el SQL Server)

```bash
gcloud compute addresses describe afp-nat-ip --region $R --format='value(address)'
gcloud compute routers nats describe afp-nat --router afp-router --region $R --format='value(natIps)'
```

Esa IP es la **única** por la que sale `afp-sync` (Direct VPC egress `--vpc-egress all-traffic`
por `afp-vpc/afp-run-egress` → Cloud NAT). Es estática: no cambia con redeploys. Sólo cambiaría
si alguien borrara `afp-nat-ip`; el setup la recrea, pero con otra dirección → nuevo allowlist.
El texto del pedido está en `infra/README.md` §3. Probar conectividad desde el job sin tocar
datos: `run-sync` con `only=dim_bd_previa` (la tabla más chica).

---

## 7. Corrida on-prem con la misma imagen (si el SQL Server no admite la IP)

`afp-sync` es portable: la misma imagen corre en cualquier máquina con Docker que alcance el
SQL Server (red/VPN Patria), escribiendo en BigQuery por HTTPS/443 con **ADC** de un usuario
que tenga `bigquery.jobUser` + WRITER en los datasets `afp_*` (o impersonando `afp-sync-run`).

```bash
gcloud auth login && gcloud auth application-default login
gcloud auth configure-docker $R-docker.pkg.dev
IMG=$R-docker.pkg.dev/$P/afp/sync:$(git rev-parse HEAD)      # o la que diga `gcloud run jobs describe afp-sync`
docker pull $IMG
docker run --rm \
  -v "$HOME/.config/gcloud:/root/.config/gcloud:ro" \
  -e GOOGLE_CLOUD_PROJECT=$P -e GCP_PROJECT_ID=$P -e BQ_LOCATION=$R \
  -e DB_SERVER=... -e DB_DATABASE=Inteligencia_Mercado -e DB_UID=... -e DB_PWD=... \
  -e WEB_URL=$WEB_URL -e REVALIDATE_TOKEN="$(gcloud secrets versions access latest --secret afp-web-revalidate-token)" \
  $IMG --only chist_adjusted            # mismos flags que main.py
```

En Windows (PowerShell) el volumen es `-v "$env:APPDATA\gcloud:/root/.config/gcloud:ro"`.
Sin Docker, también sirve el repo directo: `pip install -r sync/requirements.txt` + ODBC Driver 18 +
`.env` con `DB_*` y `GCP_PROJECT_ID`/`BQ_LOCATION` + `python main.py` (flujo del `HANDOFF.md` con
destino BigQuery). Es el mismo camino del backfill inicial (F2.8 del plan).

---

## 8. Costos esperados (orden de magnitud, USD/mes)

| Ítem | Estimación | Nota |
|---|---|---|
| Cloud Run `afp-web` con `--min-instances 1` (1 vCPU / 1 GiB, CPU sólo durante requests) | 10–15 | Es el ítem fijo mayor. Con `min-instances 0` cae a ~1–3 pero hay cold start (~3–5 s) |
| Cloud Run job `afp-sync` (2 vCPU / 4 GiB, ~1–2 h × 2 corridas/mes) | < 1 | |
| Cloud NAT + IP estática | 1–3 | NAT ≈ 0.044/h por gateway mientras haya subnet asignada + tráfico; la IP reservada en uso ≈ 0.005/h |
| BigQuery almacenamiento (< 5 GB) | < 1 | 10 GB gratis |
| BigQuery consultas (web con caché 300 s + job) | 0–5 | 1 TB/mes gratis; las tablas son de MB |
| Artifact Registry (≤ 10 imágenes × 2) | < 1 | 0.5 GB gratis |
| Secret Manager, Scheduler, Logging, Identity Platform (< 50 usuarios) | ~0 | dentro de free tier |
| **Total** | **≈ 15–25** | vs. Supabase free + Vercel hobby hoy (0, pero con auto-pausa y tope 500 MB) |

Revisar con `INFORMATION_SCHEMA.JOBS_BY_PROJECT` (bytes facturados de `afp_*`) y el reporte de
facturación filtrado por label `app=afp-dashboard`.

---

## 9. Usuarios (Identity Platform)

Alta/baja de usuarios del dashboard (sin registro self-service):

```bash
# Consola: Identity Platform -> Users -> Add user (email + contraseña temporal)
# CLI (Firebase): firebase auth:import users.json --project $P --hash-algo=BCRYPT   # migración desde Supabase
```

Si D2 termina en el fallback "login propio" (servicio público + tabla `afp_ops.users`), la
gestión de usuarios pasa a un INSERT/UPDATE en esa tabla; se documentará aquí al cerrar D2.

---

## 10. Referencias

- `PLAN_MIGRACION_GCP.md` — decisiones D1–D7, fases, mapeo objeto por objeto.
- `infra/README.md` — ticket a infra, allowlist, config GitHub, fallback Cloud Build.
- `infra/setup-afp.sh` — la fuente de verdad de nombres de recursos (re-ejecutable).
- `HANDOFF.md` — la corrida mensual legacy (laptop + Supabase + Vercel) vigente hasta el corte.
