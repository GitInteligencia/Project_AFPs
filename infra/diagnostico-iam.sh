#!/usr/bin/env bash
# =====================================================================
# infra/diagnostico-iam.sh — DIAGNÓSTICO de permisos (no cambia nada).
#
# Corre `testIamPermissions` con la identidad activa de `gcloud auth`
# (o con la SA que se indique en IMPERSONATE_SA) e imprime, paso por paso
# de infra/setup-afp.sh, [SI]/[NO] + los permisos que faltan. Al final
# lista los ROLES EXACTOS a pedir a infra para cada [NO]: ese bloque es el
# ticket (ver infra/README.md).
#
# Uso:
#   gcloud auth login
#   bash infra/diagnostico-iam.sh                       # identidad actual
#   PROJECT=pat-uat-global bash infra/diagnostico-iam.sh
#   IMPERSONATE_SA=afp-github-deploy@pat-uat-global.iam.gserviceaccount.com \
#     bash infra/diagnostico-iam.sh                     # qué puede la SA de deploy
#
# Caveats honestos (también se imprimen):
#   - testIamPermissions a nivel PROYECTO no ve concesiones hechas sobre un
#     recurso puntual (un dataset, una SA, un secreto): un NO aquí puede ser
#     un SÍ acotado. El SÍ, en cambio, es concluyente.
#   - iam.serviceAccounts.actAs se testea a nivel proyecto (equivale a
#     serviceAccountUser project-wide); si se concedió por-SA no aparece.
#   - Si una API no está habilitada, sus permisos igual se evalúan (IAM es
#     independiente de Service Usage), así que el diagnóstico sirve antes
#     de habilitar nada.
# Patrón: calco de geneva/infra/cloudbuild/diagnostico-iam.yaml.
# =====================================================================
set -euo pipefail

PROJECT="${PROJECT:-pat-uat-global}"
REGION="${REGION:-southamerica-west1}"
IMPERSONATE_SA="${IMPERSONATE_SA:-}"

command -v gcloud >/dev/null || { echo "ERROR: falta gcloud en PATH"; exit 2; }
command -v python3 >/dev/null || { echo "ERROR: falta python3 (lo usa para llamar a la API y parsear JSON)"; exit 2; }

# --- identidad y token -------------------------------------------------
if [[ -n "$IMPERSONATE_SA" ]]; then
  EMAIL="$IMPERSONATE_SA (impersonada)"
  TOKEN=$(gcloud auth print-access-token --impersonate-service-account="$IMPERSONATE_SA")
else
  EMAIL=$(gcloud auth list --filter=status:ACTIVE --format='value(account)' 2>/dev/null || true)
  if [[ -z "$EMAIL" ]]; then
    echo "ERROR: no hay cuenta activa en gcloud. Corre: gcloud auth login"; exit 2
  fi
  TOKEN=$(gcloud auth print-access-token)
fi
export TOKEN EMAIL PROJECT REGION

python3 <<'PY'
import json, os, sys, urllib.request, urllib.error

PROJECT = os.environ["PROJECT"]
TOKEN = os.environ["TOKEN"]

def probe_project(perms):
    """testIamPermissions sobre el proyecto (equivale a:
    curl -X POST https://cloudresourcemanager.googleapis.com/v1/projects/P:testIamPermissions
         -H 'Authorization: Bearer $(gcloud auth print-access-token)'
         -d '{"permissions": [...]}' )"""
    req = urllib.request.Request(
        f"https://cloudresourcemanager.googleapis.com/v1/projects/{PROJECT}:testIamPermissions",
        data=json.dumps({"permissions": perms}).encode(),
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(req) as r:
            return set(json.load(r).get("permissions", []))
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        if e.code == 403:
            # Sin resourcemanager.projects.get la API ni siquiera responde:
            # la identidad no tiene NINGÚN rol en el proyecto (o el proyecto no existe para ella).
            print(f"  (HTTP 403 al consultar el proyecto {PROJECT}: la identidad no tiene acceso "
                  f"básico al proyecto — pedir al menos roles/viewer)")
            return set()
        print(f"  (HTTP {e.code}: {body[:300]})")
        return set()

# Cada paso de infra/setup-afp.sh -> permisos que exige -> rol que lo habilita.
# El orden sigue al del setup para que el ticket se lea en el mismo orden.
PASOS = [
    ("1. habilitar APIs (run, bigquery, artifactregistry, secretmanager, scheduler, "
     "iamcredentials, identitytoolkit, compute, logging, monitoring, sts)",
     ["serviceusage.services.enable", "serviceusage.services.get"],
     "roles/serviceusage.serviceUsageAdmin"),
    ("2. crear las SAs runtime/deploy (afp-web-run, afp-sync-run, afp-github-deploy)",
     ["iam.serviceAccounts.create", "iam.serviceAccounts.get"],
     "roles/iam.serviceAccountAdmin"),
    ("3. bindings IAM a nivel PROYECTO (bigquery.jobUser, run.admin, artifactregistry.writer, "
     "firebaseauth.admin)",
     ["resourcemanager.projects.getIamPolicy", "resourcemanager.projects.setIamPolicy"],
     "roles/resourcemanager.projectIamAdmin"),
    ("4. IAM SOBRE las SAs (serviceAccountUser de afp-github-deploy sobre las SAs runtime; "
     "workloadIdentityUser para WIF)",
     ["iam.serviceAccounts.getIamPolicy", "iam.serviceAccounts.setIamPolicy"],
     "roles/iam.serviceAccountAdmin"),
    ("5. datasets BigQuery afp_raw/afp_dim/afp_mart/afp_ops/afp_stg + ACL por dataset",
     ["bigquery.datasets.create", "bigquery.datasets.get", "bigquery.datasets.update"],
     "roles/bigquery.admin (o roles/bigquery.dataOwner por dataset si ya existen)"),
    ("6. repo Artifact Registry `afp` (docker) + política de limpieza",
     ["artifactregistry.repositories.create", "artifactregistry.repositories.get",
      "artifactregistry.repositories.update"],
     "roles/artifactregistry.admin"),
    ("7. secretos afp-* vacíos + secretAccessor por SA",
     ["secretmanager.secrets.create", "secretmanager.secrets.get",
      "secretmanager.secrets.setIamPolicy"],
     "roles/secretmanager.admin"),
    ("8. red: VPC afp-vpc, subnet afp-run-egress, router afp-router, IP afp-nat-ip, NAT afp-nat",
     ["compute.networks.create", "compute.subnetworks.create", "compute.routers.create",
      "compute.routers.update", "compute.addresses.create", "compute.networks.get"],
     "roles/compute.networkAdmin"),
    ("9. Cloud Run: job afp-sync + service afp-web (placeholder) con Direct VPC egress",
     ["run.jobs.create", "run.jobs.update", "run.jobs.setIamPolicy",
      "run.services.create", "run.services.update", "run.services.setIamPolicy",
      "iam.serviceAccounts.actAs", "compute.networks.use", "compute.subnetworks.use"],
     "roles/run.admin + roles/iam.serviceAccountUser (+ roles/compute.networkUser para Direct VPC egress)"),
    ("10. Cloud Scheduler afp-sync-monthly (días 8 y 18, 07:00 America/Santiago)",
     ["cloudscheduler.jobs.create", "cloudscheduler.jobs.get", "cloudscheduler.jobs.update"],
     "roles/cloudscheduler.admin"),
    ("11. Workload Identity Federation: pool afp-github + provider github (OIDC GitHub)",
     ["iam.workloadIdentityPools.create", "iam.workloadIdentityPools.get",
      "iam.workloadIdentityPoolProviders.create", "iam.workloadIdentityPoolProviders.get"],
     "roles/iam.workloadIdentityPoolAdmin"),
    ("12. Identity Platform: config Email/Password + API key restringida (lo hace infra en consola)",
     ["firebaseauth.configs.create", "firebaseauth.configs.update", "firebaseauth.configs.get",
      "serviceusage.apiKeys.create"],
     "roles/firebaseauth.admin + roles/serviceusage.apiKeysAdmin"),
    ("13. alertas: log-based metric afp_sync_failed + alert policy",
     ["logging.logMetrics.create", "logging.logMetrics.get",
      "monitoring.alertPolicies.create", "monitoring.alertPolicies.list",
      "monitoring.notificationChannels.list"],
     "roles/logging.configWriter + roles/monitoring.alertPolicyEditor (+ monitoring.notificationChannelViewer)"),
    ("14. (operación) ejecutar el job y leer logs — lo que necesita run-sync.yml",
     ["run.jobs.run", "run.executions.get", "logging.logEntries.list"],
     "roles/run.developer (o run.invoker + run.viewer) + roles/logging.viewer"),
]

print("=" * 76)
print(f"identidad evaluada : {os.environ.get('EMAIL', '(desconocida)')}")
print(f"proyecto           : {PROJECT}   región: {os.environ.get('REGION')}")
print("=" * 76)

# Una sola llamada con todos los permisos (máx. 100 por request).
todos = sorted({p for _, perms, _ in PASOS for p in perms})
assert len(todos) <= 100, "partir en dos llamadas"
tiene = probe_project(todos)

faltantes = []
for titulo, perms, rol in PASOS:
    ok = set(perms) <= tiene
    print(f"[{'SI' if ok else 'NO'}] {titulo}")
    if not ok:
        print(f"      faltan: {', '.join(sorted(set(perms) - tiene))}")
        faltantes.append((titulo, rol))

print()
if not faltantes:
    print("VEREDICTO: esta identidad puede ejecutar TODO infra/setup-afp.sh sola:")
    print("  bash infra/setup-afp.sh")
    sys.exit(0)

print("VEREDICTO: pedir a infra (UNA VEZ, para la identidad de arriba) — bloque para el ticket:")
print("-" * 76)
roles_unicos = []
for titulo, rol in faltantes:
    if rol not in roles_unicos:
        roles_unicos.append(rol)
for rol in roles_unicos:
    pasos = [t.split(".")[0] for t, r in faltantes if r == rol]
    print(f"  - {rol}   (habilita pasos {', '.join(pasos)})")
print("-" * 76)
print("Alternativa que infra suele preferir (no delegar IAM): que INFRA ejecute ella")
print("misma los pasos 2, 3, 4, 11 y 12 con los nombres exactos de infra/README.md, y")
print("el resto lo aplica el operador re-corriendo infra/setup-afp.sh (tolera los 403).")
print()
print("Ojo: un NO a nivel proyecto puede ser un SÍ acotado por recurso (pasos 4, 5, 7, 9")
print("admiten concesión por SA / dataset / secreto / servicio). El SÍ es concluyente.")
sys.exit(1)
PY
