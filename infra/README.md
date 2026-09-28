# infra/ — Andamiaje GCP del dashboard AFP (proyecto `pat-uat-global`, región `southamerica-west1`)

Dos scripts `gcloud`/`bq` idempotentes reemplazan a Terraform (decisión D7 del
`PLAN_MIGRACION_GCP.md`: infra de Patria **no delega** `iam.serviceAccountAdmin`
ni `resourcemanager.projectIamAdmin`, que un `terraform apply` exigiría). El patrón
es el mismo que ya funciona en el repo `geneva` (`infra/cloudbuild/setup-infra.yaml`
y `diagnostico-iam.yaml`).

| Archivo | Qué hace | Cambia algo |
|---|---|---|
| `diagnostico-iam.sh` | `testIamPermissions` con la identidad activa de `gcloud`; imprime `[SI]/[NO]` por paso del setup y los roles a pedir | No |
| `setup-afp.sh` | Crea/verifica todo lo `afp-*`/`afp_*`: APIs, SAs, bindings, datasets + ACL, Artifact Registry, secretos vacíos, VPC + Cloud NAT con IP fija, Cloud Run (placeholder), Scheduler, WIF, alertas | Sí (sólo recursos `afp-*`; tolera 403) |

Los deploys de código **no** viven aquí: los hacen `.github/workflows/deploy-*.yml`
(imágenes `sync/Dockerfile` y `web/Dockerfile`, DDL con `db/bigquery/apply.py`).

---

## 1. Quién corre qué

| Paso | Quién | Comando / acción |
|---|---|---|
| 0. Diagnóstico | Operador (Ignacio) | `gcloud auth login && bash infra/diagnostico-iam.sh` |
| 1. Ticket a infra | Operador → infra | Sección 2 de este README, adjuntando la salida del diagnóstico |
| 2. Lo que infra retiene | Infra (`ti-infra-admin@patria.com`) | Crear SAs, bindings project-level, WIF, Identity Platform, secretos (o `secretmanager.admin`) |
| 3. Setup | Operador (o infra) | `bash infra/setup-afp.sh` — se puede correr **antes** de que infra termine: lo que no puede hacer lo lista como PENDIENTE y sale con rc 1 |
| 4. Re-setup | Operador | `bash infra/setup-afp.sh` otra vez cuando infra cierre el ticket (idempotente) |
| 5. Cargar secretos | Operador con la credencial SQL Server / infra | Sección 4 |
| 6. Allowlist IP NAT | Operador → dueño del SQL Server (TI) | Sección 3 |
| 7. Config GitHub | Operador (admin del repo) | Sección 5 |
| 8. Primer deploy | GitHub Actions | `deploy-bq.yml` → `deploy-sync.yml` → `deploy-web.yml` (push a `main` o `workflow_dispatch`) |
| 9. Verificación | Operador | Sección 6 |

---

## 2. Ticket único a infra (copiar y pegar)

> **Asunto:** GCP `pat-uat-global` — alta de la app `afp-dashboard` (Cloud Run + BigQuery), roles que infra retiene
>
> Hola equipo, para el dashboard de AFPs (misma organización que Geneva; mismo proyecto
> `pat-uat-global`, región `southamerica-west1`, todo con prefijo `afp-`/`afp_` y labels
> `app=afp-dashboard env=uat managed-by=afp-setup`) necesitamos estas acciones **una sola vez**.
> Todo lo demás (datasets, ACL por dataset, Artifact Registry, Scheduler, Cloud Run, red) lo
> aplica nuestro script idempotente `infra/setup-afp.sh` con la identidad indicada abajo.
>
> **Identidad que ejecutará el setup y los deploys:** `<pegar la primera línea de infra/diagnostico-iam.sh>`
>
> **A. Service accounts (exige `iam.serviceAccountAdmin`)** — crear en `pat-uat-global`, sin keys:
> - `afp-web-run@pat-uat-global.iam.gserviceaccount.com` — runtime del Cloud Run service `afp-web`
> - `afp-sync-run@pat-uat-global.iam.gserviceaccount.com` — runtime del Cloud Run job `afp-sync`
> - `afp-github-deploy@pat-uat-global.iam.gserviceaccount.com` — identidad de GitHub Actions (sólo vía WIF, ver C)
>
> **B. Bindings a nivel proyecto (exige `resourcemanager.projectIamAdmin`)**:
> - `roles/bigquery.jobUser` → las tres SAs de A (la escritura va acotada por ACL de dataset, no project-wide)
> - `roles/run.admin` y `roles/artifactregistry.writer` → `afp-github-deploy@`
> - `roles/firebaseauth.admin` → `afp-web-run@` (session cookies de Identity Platform)
> - `roles/iam.serviceAccountUser` de `afp-github-deploy@` **sobre** `afp-web-run@` y `afp-sync-run@` (binding en la SA, no en el proyecto)
>
> **C. Workload Identity Federation (exige `iam.workloadIdentityPoolAdmin`)** — para que GitHub Actions despliegue sin llaves JSON:
> - Pool `afp-github` (location `global`), provider OIDC `github`, issuer `https://token.actions.githubusercontent.com`,
>   attribute mapping `google.subject=assertion.sub, attribute.repository=assertion.repository, attribute.ref=assertion.ref, attribute.actor=assertion.actor`,
>   **attribute condition** `attribute.repository == "GitInteligencia/Project_AFPs"`.
> - Binding `roles/iam.workloadIdentityUser` sobre `afp-github-deploy@` para el miembro
>   `principalSet://iam.googleapis.com/projects/<PROJECT_NUMBER>/locations/global/workloadIdentityPools/afp-github/attribute.repository/GitInteligencia/Project_AFPs`.
> - Devolvernos el nombre completo del provider: `projects/<PROJECT_NUMBER>/locations/global/workloadIdentityPools/afp-github/providers/github`.
> - *Si WIF no se aprueba*, la alternativa es la sección 7 (Cloud Build triggers, como Geneva).
>
> **D. Identity Platform (login usuario/contraseña de la web)**:
> - Habilitar `identitytoolkit.googleapis.com` y activar Identity Platform en el proyecto, proveedor **Email/Password** (sin registro self-service; sin enumeración de emails).
> - Crear una **API key** restringida a la API Identity Toolkit (y, cuando exista, al referrer `https://afp-web-*.run.app`) y cargarla como versión del secreto `afp-idp-api-key` (o entregarla al operador por canal seguro).
>
> **E. Secret Manager**: crear vacíos (`--replication-policy=automatic`) `afp-sqlserver-host`, `afp-sqlserver-db`, `afp-sqlserver-uid`, `afp-sqlserver-pwd`, `afp-web-revalidate-token`, `afp-idp-api-key`, **o** conceder `roles/secretmanager.admin` a la identidad del setup para que los cree ella. Los valores se cargan después (sección 4).
>
> **F. Red / egress del job (sólo si la identidad del setup no tiene `roles/compute.networkAdmin`)**: VPC `afp-vpc` (custom), subnet `afp-run-egress` `10.90.0.0/26` en `southamerica-west1` con Private Google Access, Cloud Router `afp-router`, IP estática regional `afp-nat-ip`, Cloud NAT `afp-nat` sólo para esa subnet usando `afp-nat-ip`. Además `roles/compute.networkUser` a la identidad del setup y a `afp-github-deploy@` para el Direct VPC egress del job. **No hay VPN**: el job sale por esa IP fija y el SQL Server la allowlistea.
>
> **G. APIs** (si la identidad no tiene `serviceusage.serviceUsageAdmin`): `run, bigquery, artifactregistry, secretmanager, cloudscheduler, iamcredentials, identitytoolkit, compute, logging, monitoring, sts`.
>
> Con A–G resueltos, el setup, los datasets y el resto quedan de nuestro lado. Gracias.

Para saber exactamente cuáles letras aplican, correr `infra/diagnostico-iam.sh`: cada
`[NO]` mapea a una letra (2→A, 3/4→B, 11→C, 12→D, 7→E, 8/9→F, 1→G).

---

## 3. Pedido de allowlist de la IP NAT (al dueño del SQL Server)

Tras el setup, la IP la imprime el resumen (`IP NAT estática`) o:

```bash
gcloud compute addresses describe afp-nat-ip --region southamerica-west1 --project pat-uat-global --format='value(address)'
```

> **Asunto:** Allowlist de IP para acceso a SQL Server `Inteligencia_Mercado`
>
> Necesitamos que el firewall del SQL Server que hoy usa el pipeline AFP (host en el
> secreto `afp-sqlserver-host`, base `Inteligencia_Mercado`, puerto **1433/TCP**) permita
> conexiones entrantes desde la IP pública fija **`<IP NAT>`** (Cloud NAT `afp-nat` de
> GCP, proyecto `pat-uat-global`). Es la única IP de salida del job mensual `afp-sync`;
> usa el mismo usuario SQL de sólo lectura de hoy, con ODBC Driver 18 y TLS opcional.

Si el allowlist se demora, la imagen `afp-sync` es portable: corre en cualquier máquina que
alcance el SQL Server (ver `docs/GCP_RUNBOOK.md` §"Corrida on-prem").

---

## 4. Cargar el primer valor de cada secreto

```bash
P=pat-uat-global
printf '%s' 'sqlserver.patria.local'      | gcloud secrets versions add afp-sqlserver-host --project $P --data-file=-
printf '%s' 'Inteligencia_Mercado'        | gcloud secrets versions add afp-sqlserver-db   --project $P --data-file=-
printf '%s' '<usuario sql>'               | gcloud secrets versions add afp-sqlserver-uid  --project $P --data-file=-
printf '%s' '<contraseña sql>'            | gcloud secrets versions add afp-sqlserver-pwd  --project $P --data-file=-
openssl rand -hex 32                      | tr -d '\n' | gcloud secrets versions add afp-web-revalidate-token --project $P --data-file=-
printf '%s' '<API key Identity Platform>' | gcloud secrets versions add afp-idp-api-key    --project $P --data-file=-
```

`printf '%s'` evita colar un salto de línea al final (rompe la contraseña). Quien tenga el
`.env` actual de la laptop tiene ya los cuatro valores `DB_*`.

---

## 5. Configuración del repo GitHub (`GitInteligencia/Project_AFPs`)

Settings → Secrets and variables → Actions:

| Tipo | Nombre | Valor |
|---|---|---|
| Variable | `GCP_PROJECT_ID` | `pat-uat-global` |
| Variable | `GCP_REGION` | `southamerica-west1` |
| Secret | `GCP_WIF_PROVIDER` | `projects/<PROJECT_NUMBER>/locations/global/workloadIdentityPools/afp-github/providers/github` |
| Secret | `GCP_DEPLOY_SA` | `afp-github-deploy@pat-uat-global.iam.gserviceaccount.com` |

Settings → Environments → **`uat`**: opcionalmente "Required reviewers" para que los deploys y
`run-sync` pidan aprobación. Ninguna credencial de SQL Server ni de BigQuery pasa por GitHub.

---

## 6. Verificación posterior

```bash
P=pat-uat-global; R=southamerica-west1
bash infra/setup-afp.sh                                   # debe terminar "SETUP COMPLETO" (rc 0)
bq ls --project_id $P | grep afp_                          # 5 datasets
gcloud run jobs describe afp-sync --region $R --format='value(template.template.serviceAccount, template.template.vpcAccess.networkInterfaces)'
gcloud run services describe afp-web --region $R --format='value(status.url)'
gcloud scheduler jobs describe afp-sync-monthly --location $R --format='value(schedule,timeZone,httpTarget.uri)'
gcloud secrets versions list afp-sqlserver-pwd --format='value(name,state)'   # >= 1 ENABLED
gcloud compute addresses describe afp-nat-ip --region $R --format='value(address)'
```

Prueba de conectividad al SQL Server desde la red del job (tras el allowlist), sin tocar datos:

```bash
gcloud run jobs execute afp-sync --region $R --args="--list" --wait      # sólo imprime el plan
```

Luego una corrida real acotada (`--only dim_bd_previa`, la tabla más chica) desde
`run-sync.yml` y revisar `afp_ops.run_log`.

---

## 7. Fallback si infra no aprueba WIF: Cloud Build triggers

Es el patrón vigente en Geneva (`geneva-*-deploy`, SA `cloud-build@pat-uat-global`). GitHub
Actions sigue como *gates* (`ci.yml`) y el deploy pasa a Cloud Build:

1. Infra instala la GitHub App de Cloud Build en la organización `GitInteligencia` y conecta el repo (2ª gen).
2. Se crean `infra/cloudbuild/deploy-web.yaml`, `deploy-sync.yaml`, `deploy-bq.yaml` traduciendo casi
   línea a línea los pasos `docker build/push` + `gcloud run deploy|jobs deploy` de
   `.github/workflows/deploy-*.yml` (ver `geneva/infra/cloudbuild/deploy-loader.yaml` como molde).
3. Triggers `afp-web-deploy`, `afp-sync-deploy`, `afp-bq-deploy` sobre push a `main` con filtros
   de paths `web/**`, `sync/**|main.py|db/bigquery/marts/**`, `db/**`, con SA `cloud-build@` (ya tiene
   `run.admin`, `artifactregistry.*`, `bigquery.admin`, `iam.serviceAccountUser`).
4. `afp-github-deploy@` y la sección C del ticket se descartan; `run-sync.yml` se reemplaza por
   `gcloud run jobs execute afp-sync --args=... --wait` a mano (o un trigger manual de Cloud Build).

Lo que **no** cambia: `setup-afp.sh`, las SAs runtime, datasets, secretos, red y Scheduler.
