#!/usr/bin/env bash
# =====================================================================
# infra/setup-afp.sh — SETUP de la infraestructura GCP del dashboard AFP.
# Idempotente y re-ejecutable: cada recurso se crea sólo si no existe y
# cada binding se re-aplica sin efecto si ya estaba. NO hace deploys de
# código (eso es .github/workflows/deploy-*.yml) ni toca datos.
#
# Patrón: calco de geneva/infra/cloudbuild/setup-infra.yaml. Los pasos que
# exigen roles que infra NO delega (crear SAs, bindings project-level, WIF,
# Identity Platform) son TOLERANTES al 403: avisan "se asume hecho por
# infra" y siguen. Antes de correrlo, ver qué puede hacer sola la identidad
# con infra/diagnostico-iam.sh; el ticket para lo demás está en infra/README.md.
#
# Uso:
#   gcloud auth login && gcloud config set project pat-uat-global
#   bash infra/setup-afp.sh
#   NOTIFICATION_CHANNEL=projects/.../notificationChannels/123 bash infra/setup-afp.sh
#
# Re-correrlo tras el primer deploy de los workflows es seguro y recomendable
# (re-aplica run.invoker sobre el job y verifica que todo siga en su sitio).
# =====================================================================
set -euo pipefail

# ----------------------------- variables ------------------------------
PROJECT="${PROJECT:-pat-uat-global}"
REGION="${REGION:-southamerica-west1}"
GITHUB_REPO="${GITHUB_REPO:-GitInteligencia/Project_AFPs}"

# Identidades (una SA por workload; ninguna usa la SA por defecto de Compute)
SA_WEB="${SA_WEB:-afp-web-run}"
SA_SYNC="${SA_SYNC:-afp-sync-run}"
SA_DEPLOY="${SA_DEPLOY:-afp-github-deploy}"

# Cloud Run / Artifact Registry / Scheduler
RUN_SERVICE="${RUN_SERVICE:-afp-web}"
RUN_JOB="${RUN_JOB:-afp-sync}"
AR_REPO="${AR_REPO:-afp}"
SCHEDULER_JOB="${SCHEDULER_JOB:-afp-sync-monthly}"
SCHEDULE="${SCHEDULE:-0 7 8,18 * *}"          # días 8 y 18, 07:00
TIME_ZONE="${TIME_ZONE:-America/Santiago}"
# Imágenes placeholder para que service/job EXISTAN antes del primer deploy.
# Para el job se usa la imagen oficial de quickstart de Cloud Run Jobs porque
# TERMINA sola (gcr.io/cloudrun/hello es un servidor HTTP y una ejecución
# accidental del job se quedaría colgada hasta el timeout).
PLACEHOLDER_SERVICE_IMAGE="${PLACEHOLDER_SERVICE_IMAGE:-gcr.io/cloudrun/hello}"
PLACEHOLDER_JOB_IMAGE="${PLACEHOLDER_JOB_IMAGE:-us-docker.pkg.dev/cloudrun/container/job:latest}"

# BigQuery
DATASETS="${DATASETS:-afp_raw afp_dim afp_mart afp_ops afp_stg}"
STG_TABLE_EXPIRATION_S="${STG_TABLE_EXPIRATION_S:-86400}"   # afp_stg: 1 día

# Secret Manager (se crean VACÍOS; el valor lo carga infra/operador con
# `gcloud secrets versions add <nombre> --data-file=-`)
SECRETS="${SECRETS:-afp-sqlserver-host afp-sqlserver-db afp-sqlserver-uid afp-sqlserver-pwd afp-web-revalidate-token afp-idp-api-key}"

# Red: egress del job por Cloud NAT con IP estática (opción "sin VPN": el
# SQL Server allowlistea esa IP). Direct VPC egress exige subnet >= /26.
VPC="${VPC:-afp-vpc}"
SUBNET="${SUBNET:-afp-run-egress}"
SUBNET_RANGE="${SUBNET_RANGE:-10.90.0.0/26}"
ROUTER="${ROUTER:-afp-router}"
NAT="${NAT:-afp-nat}"
NAT_IP="${NAT_IP:-afp-nat-ip}"

# WIF (GitHub Actions -> SA de deploy, sin llaves JSON)
WIF_POOL="${WIF_POOL:-afp-github}"
WIF_PROVIDER="${WIF_PROVIDER:-github}"

# Alertas: canal de notificación existente (projects/P/notificationChannels/ID).
# Vacío = se crea la métrica pero NO la policy (se imprime cómo hacerlo).
NOTIFICATION_CHANNEL="${NOTIFICATION_CHANNEL:-}"
LOG_METRIC="${LOG_METRIC:-afp_sync_failed}"

LABELS="app=afp-dashboard,env=uat,managed-by=afp-setup"
APIS="run.googleapis.com bigquery.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com cloudscheduler.googleapis.com iamcredentials.googleapis.com identitytoolkit.googleapis.com compute.googleapis.com logging.googleapis.com monitoring.googleapis.com sts.googleapis.com"

# ----------------------------- helpers --------------------------------
SA_WEB_EMAIL="$SA_WEB@$PROJECT.iam.gserviceaccount.com"
SA_SYNC_EMAIL="$SA_SYNC@$PROJECT.iam.gserviceaccount.com"
SA_DEPLOY_EMAIL="$SA_DEPLOY@$PROJECT.iam.gserviceaccount.com"
PENDIENTES=()          # lo que no se pudo hacer y queda para infra
TMPD=$(mktemp -d); trap 'rm -rf "$TMPD"' EXIT

title() { echo; echo "== $* =="; }
ok()    { echo "  [ok] $*"; }
note()  { echo "  [..] $*"; }
pend()  { echo "  [PENDIENTE infra] $*"; PENDIENTES+=("$*"); }

# Ejecuta un comando; si falla, registra el pendiente y sigue (tolerancia al 403).
tolerante() {  # tolerante "<descripción para infra>" cmd args...
  local desc="$1"; shift
  if "$@" >/dev/null 2>"$TMPD/err"; then ok "$desc"; else
    pend "$desc  ($(head -c 200 "$TMPD/err" | tr '\n' ' '))"
  fi
}

command -v gcloud >/dev/null || { echo "ERROR: falta gcloud"; exit 2; }
command -v bq >/dev/null     || { echo "ERROR: falta bq (componente de gcloud: gcloud components install bq)"; exit 2; }
command -v python3 >/dev/null || { echo "ERROR: falta python3"; exit 2; }

gcloud config set project "$PROJECT" --quiet >/dev/null
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')
IDENTIDAD=$(gcloud auth list --filter=status:ACTIVE --format='value(account)')
echo "proyecto: $PROJECT ($PROJECT_NUMBER)   región: $REGION   identidad: $IDENTIDAD"

# ------------------------------ 1) APIs --------------------------------
title "1) APIs"
# Una sola llamada; si no hay serviceUsageAdmin falla toda y se registra el pendiente.
# shellcheck disable=SC2086
tolerante "habilitar APIs: $APIS" gcloud services enable $APIS --project "$PROJECT"

# ------------------------------- 2) SAs --------------------------------
title "2) Service accounts (mínimo privilegio, SIN keys)"
# Crear SAs exige iam.serviceAccountAdmin, que infra NO delega: si no existen y
# no se pueden crear, se asume que infra las crea con estos nombres exactos.
for SA in "$SA_WEB" "$SA_SYNC" "$SA_DEPLOY"; do
  if gcloud iam service-accounts describe "$SA@$PROJECT.iam.gserviceaccount.com" --project "$PROJECT" >/dev/null 2>&1; then
    ok "SA $SA existe"
  else
    tolerante "crear SA $SA@$PROJECT.iam.gserviceaccount.com" \
      gcloud iam service-accounts create "$SA" --project "$PROJECT" \
        --display-name "AFP dashboard: $SA" --description "app=afp-dashboard; ver infra/README.md"
  fi
done

# ---------------------- 3) bindings a nivel proyecto -------------------
title "3) Bindings a nivel PROYECTO (exigen projectIamAdmin; tolerantes)"
bind_project() {  # member role
  tolerante "roles project-level: $2 -> $1" \
    gcloud projects add-iam-policy-binding "$PROJECT" --quiet --condition=None \
      --member "serviceAccount:$1" --role "$2"
}
# jobUser: correr consultas/jobs BQ (la ESCRITURA va por ACL de dataset, paso 5).
for SA_EMAIL in "$SA_WEB_EMAIL" "$SA_SYNC_EMAIL" "$SA_DEPLOY_EMAIL"; do
  bind_project "$SA_EMAIL" roles/bigquery.jobUser
done
# SA de deploy (GitHub Actions): desplegar Cloud Run y subir imágenes.
bind_project "$SA_DEPLOY_EMAIL" roles/run.admin
bind_project "$SA_DEPLOY_EMAIL" roles/artifactregistry.writer
# La web crea/verifica session cookies de Identity Platform con firebase-admin (D2).
bind_project "$SA_WEB_EMAIL" roles/firebaseauth.admin
# El job y la web leen sus secretos vía --set-secrets: el accessor se da POR SECRETO (paso 7).

# --------------------- 4) IAM sobre las SAs runtime --------------------
title "4) serviceAccountUser: la SA de deploy puede 'actAs' de las SAs runtime"
for SA_EMAIL in "$SA_WEB_EMAIL" "$SA_SYNC_EMAIL"; do
  tolerante "serviceAccountUser de $SA_DEPLOY sobre $SA_EMAIL" \
    gcloud iam service-accounts add-iam-policy-binding "$SA_EMAIL" --project "$PROJECT" \
      --member "serviceAccount:$SA_DEPLOY_EMAIL" --role roles/iam.serviceAccountUser
done

# ---------------------------- 5) BigQuery ------------------------------
title "5) Datasets BigQuery (región $REGION) + ACL por dataset"
for DS in $DATASETS; do
  if bq show --project_id "$PROJECT" "$PROJECT:$DS" >/dev/null 2>&1; then
    ok "dataset $DS existe"
  else
    EXTRA=()
    [[ "$DS" == "afp_stg" ]] && EXTRA=(--default_table_expiration "$STG_TABLE_EXPIRATION_S")
    tolerante "crear dataset $DS" \
      bq mk --dataset --project_id "$PROJECT" --location "$REGION" \
        --label app:afp-dashboard --label env:uat --label managed-by:afp-setup \
        --description "AFP Chile Dashboard ($DS). Ver PLAN_MIGRACION_GCP.md" ${EXTRA[@]+"${EXTRA[@]}"} "$PROJECT:$DS"
  fi
done

# ACL por dataset, no project-wide (patrón geneva): se lee el access actual, se
# agregan las entradas que falten y se escribe de vuelta. Idempotente.
#   afp-sync-run      WRITER en los 5 (escribe raw/dim, reconstruye marts, run_log, staging)
#   afp-github-deploy WRITER en los 5 (deploy-bq.yml aplica DDL/seeds) == dataEditor acotado
#   afp-web-run       READER en afp_mart, afp_dim y afp_raw (tipo_cambio / valores_cuota_patrimonio)
export PROJECT SA_WEB_EMAIL SA_SYNC_EMAIL SA_DEPLOY_EMAIL DATASETS TMPD
if python3 - <<'PY'
import json, os, subprocess, sys
P = os.environ["PROJECT"]; T = os.environ["TMPD"]
web, sync, dep = (os.environ[k] for k in ("SA_WEB_EMAIL", "SA_SYNC_EMAIL", "SA_DEPLOY_EMAIL"))
grants = {ds: [(sync, "WRITER"), (dep, "WRITER")] for ds in os.environ["DATASETS"].split()}
for ds in ("afp_mart", "afp_dim", "afp_raw"):
    grants.setdefault(ds, []).append((web, "READER"))
rc = 0
for ds, gs in grants.items():
    show = subprocess.run(["bq", "show", "--format=prettyjson", f"{P}:{ds}"], capture_output=True, text=True)
    if show.returncode:
        print(f"  [..] {ds}: no se pudo leer ({show.stderr.strip()[:120]}) — se omite la ACL"); rc = 1; continue
    meta = json.loads(show.stdout); access = meta.get("access", [])
    nuevos = [{"role": r, "userByEmail": e} for e, r in gs if {"role": r, "userByEmail": e} not in access]
    if not nuevos:
        print(f"  [ok] {ds}: ACL al día"); continue
    with open(f"{T}/ds.json", "w") as f:
        json.dump({"access": access + nuevos}, f)
    up = subprocess.run(["bq", "update", "--source", f"{T}/ds.json", f"{P}:{ds}"], capture_output=True, text=True)
    if up.returncode:
        print(f"  [..] {ds}: no se pudo actualizar la ACL ({up.stderr.strip()[:160]})"); rc = 1
    else:
        print(f"  [ok] {ds}: +{len(nuevos)} accesos ({', '.join(e.split('@')[0]+':'+r for e, r in gs)})")
sys.exit(rc)
PY
then :; else pend "ACL por dataset (WRITER $SA_SYNC/$SA_DEPLOY en $DATASETS; READER $SA_WEB en afp_mart afp_dim afp_raw)"; fi

# ------------------------- 6) Artifact Registry ------------------------
title "6) Artifact Registry $AR_REPO (docker, $REGION)"
if gcloud artifacts repositories describe "$AR_REPO" --location "$REGION" --project "$PROJECT" >/dev/null 2>&1; then
  ok "repo $AR_REPO existe"
else
  tolerante "crear repo Artifact Registry $AR_REPO" \
    gcloud artifacts repositories create "$AR_REPO" --repository-format=docker \
      --location "$REGION" --project "$PROJECT" --labels "$LABELS" \
      --description "Imágenes afp/web y afp/sync (AFP Chile Dashboard)"
fi
# Política de limpieza: conservar las 10 versiones más recientes por imagen.
cat > "$TMPD/cleanup.json" <<'JSON'
[
  {"name": "keep-recent-10", "action": {"type": "Keep"},
   "mostRecentVersions": {"keepCount": 10}},
  {"name": "delete-older-than-90d", "action": {"type": "Delete"},
   "condition": {"olderThan": "7776000s", "tagState": "ANY"}}
]
JSON
tolerante "política de limpieza del repo $AR_REPO (keep 10 / delete > 90 d)" \
  gcloud artifacts repositories set-cleanup-policies "$AR_REPO" --location "$REGION" \
    --project "$PROJECT" --policy "$TMPD/cleanup.json" --no-dry-run

# --------------------------- 7) Secret Manager -------------------------
title "7) Secretos (vacíos) + secretAccessor por SA"
for S in $SECRETS; do
  if gcloud secrets describe "$S" --project "$PROJECT" >/dev/null 2>&1; then
    ok "secreto $S existe"
  else
    tolerante "crear secreto $S (vacío; el valor se carga con: gcloud secrets versions add $S --data-file=-)" \
      gcloud secrets create "$S" --project "$PROJECT" --replication-policy=automatic --labels "$LABELS"
  fi
done
grant_secret() {  # secreto sa_email
  tolerante "secretAccessor de ${2%%@*} sobre $1" \
    gcloud secrets add-iam-policy-binding "$1" --project "$PROJECT" \
      --member "serviceAccount:$2" --role roles/secretmanager.secretAccessor
}
for S in afp-sqlserver-host afp-sqlserver-db afp-sqlserver-uid afp-sqlserver-pwd afp-web-revalidate-token; do
  grant_secret "$S" "$SA_SYNC_EMAIL"
done
for S in afp-web-revalidate-token afp-idp-api-key; do
  grant_secret "$S" "$SA_WEB_EMAIL"
done

# -------------------------------- 8) Red -------------------------------
title "8) Red: VPC $VPC / subnet $SUBNET / router $ROUTER / IP $NAT_IP / NAT $NAT"
if gcloud compute networks describe "$VPC" --project "$PROJECT" >/dev/null 2>&1; then ok "VPC $VPC existe"; else
  tolerante "crear VPC $VPC (custom)" \
    gcloud compute networks create "$VPC" --project "$PROJECT" --subnet-mode=custom
fi
if gcloud compute networks subnets describe "$SUBNET" --region "$REGION" --project "$PROJECT" >/dev/null 2>&1; then ok "subnet $SUBNET existe"; else
  tolerante "crear subnet $SUBNET $SUBNET_RANGE (Direct VPC egress exige >= /26)" \
    gcloud compute networks subnets create "$SUBNET" --project "$PROJECT" --network "$VPC" \
      --region "$REGION" --range "$SUBNET_RANGE" --enable-private-ip-google-access
fi
if gcloud compute routers describe "$ROUTER" --region "$REGION" --project "$PROJECT" >/dev/null 2>&1; then ok "router $ROUTER existe"; else
  tolerante "crear Cloud Router $ROUTER" \
    gcloud compute routers create "$ROUTER" --project "$PROJECT" --network "$VPC" --region "$REGION"
fi
if gcloud compute addresses describe "$NAT_IP" --region "$REGION" --project "$PROJECT" >/dev/null 2>&1; then ok "IP estática $NAT_IP existe"; else
  tolerante "reservar IP estática regional $NAT_IP (la que allowlistea el SQL Server)" \
    gcloud compute addresses create "$NAT_IP" --project "$PROJECT" --region "$REGION" --network-tier=PREMIUM
fi
if gcloud compute routers nats describe "$NAT" --router "$ROUTER" --region "$REGION" --project "$PROJECT" >/dev/null 2>&1; then ok "NAT $NAT existe"; else
  tolerante "crear Cloud NAT $NAT sólo para la subnet $SUBNET con IP $NAT_IP" \
    gcloud compute routers nats create "$NAT" --project "$PROJECT" --router "$ROUTER" --region "$REGION" \
      --nat-custom-subnet-ip-ranges "$SUBNET" --nat-external-ip-pool "$NAT_IP" --enable-logging --log-filter=ERRORS_ONLY
fi
NAT_IP_ADDR=$(gcloud compute addresses describe "$NAT_IP" --region "$REGION" --project "$PROJECT" --format='value(address)' 2>/dev/null || echo "(sin permiso / no creada)")

# ------------------------------ 9) Cloud Run ---------------------------
title "9) Cloud Run: job $RUN_JOB y service $RUN_SERVICE (placeholder si no existen)"
# Existen desde el setup para que Scheduler/IAM tengan a qué apuntar; la imagen
# real la ponen deploy-sync.yml / deploy-web.yml (que también fijan cpu/memoria/env).
if gcloud run jobs describe "$RUN_JOB" --region "$REGION" --project "$PROJECT" >/dev/null 2>&1; then ok "job $RUN_JOB existe"; else
  tolerante "crear job $RUN_JOB (placeholder $PLACEHOLDER_JOB_IMAGE, SA $SA_SYNC, egress por $VPC/$SUBNET)" \
    gcloud run jobs create "$RUN_JOB" --project "$PROJECT" --region "$REGION" \
      --image "$PLACEHOLDER_JOB_IMAGE" --service-account "$SA_SYNC_EMAIL" \
      --network "$VPC" --subnet "$SUBNET" --vpc-egress all-traffic \
      --cpu 2 --memory 4Gi --task-timeout 3h --max-retries 0 --labels "$LABELS"
fi
if gcloud run services describe "$RUN_SERVICE" --region "$REGION" --project "$PROJECT" >/dev/null 2>&1; then ok "service $RUN_SERVICE existe"; else
  # min-instances 0 en el placeholder: no pagar una instancia caliente de "hello";
  # deploy-web.yml lo sube a 1 con la imagen real.
  tolerante "crear service $RUN_SERVICE (placeholder $PLACEHOLDER_SERVICE_IMAGE, SA $SA_WEB, público)" \
    gcloud run deploy "$RUN_SERVICE" --project "$PROJECT" --region "$REGION" \
      --image "$PLACEHOLDER_SERVICE_IMAGE" --service-account "$SA_WEB_EMAIL" \
      --allow-unauthenticated --port 8080 --min-instances 0 --max-instances 3 \
      --labels "$LABELS" --quiet
fi

# ------------------------------ 10) Scheduler --------------------------
title "10) Cloud Scheduler $SCHEDULER_JOB ($SCHEDULE $TIME_ZONE) -> jobs/$RUN_JOB:run"
RUN_URI="https://run.googleapis.com/v2/projects/$PROJECT/locations/$REGION/jobs/$RUN_JOB:run"
if gcloud scheduler jobs describe "$SCHEDULER_JOB" --location "$REGION" --project "$PROJECT" >/dev/null 2>&1; then
  tolerante "actualizar schedule/URI de $SCHEDULER_JOB" \
    gcloud scheduler jobs update http "$SCHEDULER_JOB" --location "$REGION" --project "$PROJECT" \
      --schedule "$SCHEDULE" --time-zone "$TIME_ZONE" --uri "$RUN_URI" --http-method POST \
      --oauth-service-account-email "$SA_SYNC_EMAIL" --attempt-deadline 30m
else
  tolerante "crear Scheduler $SCHEDULER_JOB" \
    gcloud scheduler jobs create http "$SCHEDULER_JOB" --location "$REGION" --project "$PROJECT" \
      --schedule "$SCHEDULE" --time-zone "$TIME_ZONE" --uri "$RUN_URI" --http-method POST \
      --oauth-service-account-email "$SA_SYNC_EMAIL" --attempt-deadline 30m \
      --description "Corrida mensual del pipeline AFP (main.py sin flags). Pasos idempotentes: la doble corrida recoge fuentes tardías (CHIST)."
fi
# Para invocar run.googleapis.com la SA runtime necesita run.invoker sobre SU job.
tolerante "run.invoker de $SA_SYNC sobre el job $RUN_JOB (necesario para Scheduler)" \
  gcloud run jobs add-iam-policy-binding "$RUN_JOB" --region "$REGION" --project "$PROJECT" \
    --member "serviceAccount:$SA_SYNC_EMAIL" --role roles/run.invoker

# --------------------------------- 11) WIF -----------------------------
title "11) Workload Identity Federation: pool $WIF_POOL / provider $WIF_PROVIDER (repo $GITHUB_REPO)"
if gcloud iam workload-identity-pools describe "$WIF_POOL" --location global --project "$PROJECT" >/dev/null 2>&1; then ok "pool $WIF_POOL existe"; else
  tolerante "crear WIF pool $WIF_POOL" \
    gcloud iam workload-identity-pools create "$WIF_POOL" --location global --project "$PROJECT" \
      --display-name "GitHub Actions AFP" --description "OIDC de GitHub Actions para $GITHUB_REPO"
fi
if gcloud iam workload-identity-pools providers describe "$WIF_PROVIDER" --workload-identity-pool "$WIF_POOL" --location global --project "$PROJECT" >/dev/null 2>&1; then ok "provider $WIF_PROVIDER existe"; else
  tolerante "crear WIF provider $WIF_PROVIDER (restringido a attribute.repository == '$GITHUB_REPO')" \
    gcloud iam workload-identity-pools providers create-oidc "$WIF_PROVIDER" \
      --workload-identity-pool "$WIF_POOL" --location global --project "$PROJECT" \
      --issuer-uri "https://token.actions.githubusercontent.com" \
      --attribute-mapping "google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref,attribute.actor=assertion.actor" \
      --attribute-condition "attribute.repository == '$GITHUB_REPO'"
fi
WIF_PRINCIPAL="principalSet://iam.googleapis.com/projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/$WIF_POOL/attribute.repository/$GITHUB_REPO"
tolerante "workloadIdentityUser: el repo $GITHUB_REPO puede impersonar a $SA_DEPLOY" \
  gcloud iam service-accounts add-iam-policy-binding "$SA_DEPLOY_EMAIL" --project "$PROJECT" \
    --member "$WIF_PRINCIPAL" --role roles/iam.workloadIdentityUser
WIF_PROVIDER_FULL="projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/$WIF_POOL/providers/$WIF_PROVIDER"

# -------------------------------- 12) Alertas --------------------------
title "12) Alertas: métrica de log $LOG_METRIC + policy"
# Un task del job que sale con rc != 0 deja una línea ERROR del sistema de Cloud
# Run ("Container called exit(N)"), además de los ERROR propios de main.py.
METRIC_FILTER="resource.type=\"cloud_run_job\" AND resource.labels.job_name=\"$RUN_JOB\" AND severity>=ERROR"
if gcloud logging metrics describe "$LOG_METRIC" --project "$PROJECT" >/dev/null 2>&1; then ok "métrica $LOG_METRIC existe"; else
  tolerante "crear log-based metric $LOG_METRIC" \
    gcloud logging metrics create "$LOG_METRIC" --project "$PROJECT" \
      --description "Líneas ERROR del Cloud Run job $RUN_JOB (falla de la corrida mensual AFP)" \
      --log-filter "$METRIC_FILTER"
fi
if [[ -n "$NOTIFICATION_CHANNEL" ]]; then
  if gcloud alpha monitoring policies list --project "$PROJECT" --filter="displayName=\"AFP: job $RUN_JOB falló\"" --format='value(name)' 2>/dev/null | grep -q .; then
    ok "alert policy 'AFP: job $RUN_JOB falló' existe"
  else
    cat > "$TMPD/policy.json" <<JSON
{
  "displayName": "AFP: job $RUN_JOB falló",
  "combiner": "OR",
  "conditions": [{
    "displayName": "ERROR en $RUN_JOB (métrica $LOG_METRIC > 0 en 5 min)",
    "conditionThreshold": {
      "filter": "metric.type=\"logging.googleapis.com/user/$LOG_METRIC\" AND resource.type=\"cloud_run_job\"",
      "comparison": "COMPARISON_GT", "thresholdValue": 0, "duration": "0s",
      "aggregations": [{"alignmentPeriod": "300s", "perSeriesAligner": "ALIGN_SUM"}],
      "trigger": {"count": 1}
    }
  }],
  "notificationChannels": ["$NOTIFICATION_CHANNEL"],
  "alertStrategy": {"autoClose": "86400s"},
  "documentation": {"content": "La corrida mensual AFP (Cloud Run job $RUN_JOB) registró errores. Ver docs/GCP_RUNBOOK.md: leer run_log y logs, relanzar con --only.", "mimeType": "text/markdown"},
  "userLabels": {"app": "afp-dashboard", "env": "uat", "managed-by": "afp-setup"}
}
JSON
    tolerante "crear alert policy hacia $NOTIFICATION_CHANNEL" \
      gcloud alpha monitoring policies create --project "$PROJECT" --policy-from-file "$TMPD/policy.json"
  fi
else
  note "NOTIFICATION_CHANNEL vacío: no se crea la alert policy. Para crearla:"
  note "  gcloud beta monitoring channels create --display-name 'AFP ops' --type email --channel-labels email_address=<correo>"
  note "  NOTIFICATION_CHANNEL=\$(gcloud beta monitoring channels list --filter='displayName=\"AFP ops\"' --format='value(name)') bash infra/setup-afp.sh"
fi

# -------------------------------- resumen ------------------------------
WEB_URL=$(gcloud run services describe "$RUN_SERVICE" --region "$REGION" --project "$PROJECT" --format='value(status.url)' 2>/dev/null || echo "(service aún no existe)")
echo
echo "======================================================================"
echo "RESUMEN setup AFP  —  proyecto $PROJECT  región $REGION"
echo "======================================================================"
echo "  SAs            : $SA_WEB_EMAIL"
echo "                   $SA_SYNC_EMAIL"
echo "                   $SA_DEPLOY_EMAIL"
echo "  Datasets       : $DATASETS"
echo "  Artifact Reg.  : $REGION-docker.pkg.dev/$PROJECT/$AR_REPO/{web,sync}"
echo "  Secretos       : $SECRETS"
echo "  Cloud Run      : service $RUN_SERVICE -> $WEB_URL"
echo "                   job $RUN_JOB (egress $VPC/$SUBNET via NAT $NAT)"
echo "  IP NAT estática: $NAT_IP_ADDR   <-- pedir allowlist en el firewall del SQL Server (puerto 1433)"
echo "  Scheduler      : $SCHEDULER_JOB  '$SCHEDULE' $TIME_ZONE"
echo "  WIF provider   : $WIF_PROVIDER_FULL"
echo
echo "  GitHub -> Settings -> Secrets and variables -> Actions:"
echo "    vars    GCP_PROJECT_ID=$PROJECT"
echo "    vars    GCP_REGION=$REGION"
echo "    secrets GCP_WIF_PROVIDER=$WIF_PROVIDER_FULL"
echo "    secrets GCP_DEPLOY_SA=$SA_DEPLOY_EMAIL"
echo "    environment 'uat' (con reviewers si se quiere aprobación en deploys/run-sync)"
echo
echo "  Valores de secretos que hay que CARGAR (una vez, operador/infra):"
for S in $SECRETS; do
  VERS=$(gcloud secrets versions list "$S" --project "$PROJECT" --filter=state:ENABLED --format='value(name)' 2>/dev/null | wc -l | tr -d ' ')
  echo "    $S : ${VERS:-?} versión(es) habilitada(s)   ->  printf '%s' '<valor>' | gcloud secrets versions add $S --data-file=-"
done
echo
if ((${#PENDIENTES[@]})); then
  echo "  PENDIENTES para infra (${#PENDIENTES[@]}) — copiar al ticket de infra/README.md:"
  for P in "${PENDIENTES[@]}"; do echo "    - $P"; done
  echo
  echo "SETUP PARCIAL: re-correr este script cuando infra resuelva los pendientes (es idempotente)."
  exit 1
fi
echo "SETUP COMPLETO (idempotente; re-ejecutable sin riesgo). Siguiente: cargar secretos, pedir allowlist de la IP NAT, correr los workflows deploy-*."
