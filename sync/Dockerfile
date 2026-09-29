# Imagen del pipeline de datos (main.py + sync/): SQL Server -> BigQuery.
#
# Contexto de build = RAIZ del repo (necesita main.py, sync/ y db/bigquery/marts/):
#     docker build -f sync/Dockerfile -t afp-sync .
#
# La imagen es PORTABLE: la misma corre como Cloud Run Job (credenciales = la
# service account del job, via ADC) o en cualquier maquina on-prem que alcance
# el SQL Server, montando ADC (gcloud auth application-default login y
# GOOGLE_APPLICATION_CREDENTIALS apuntando al ADC del usuario). BigQuery va por
# HTTPS/443. Nunca se copian llaves JSON a la imagen.
#
# Variables esperadas en runtime (Secret Manager en Cloud Run; .env/-e on-prem):
#   DB_SERVER DB_DATABASE DB_UID DB_PWD            SQL Server (ODBC Driver 18)
#   GCP_PROJECT_ID BQ_LOCATION                     defaults pat-uat-global / southamerica-west1
#   WEB_URL REVALIDATE_TOKEN                       opcionales: POST /api/revalidate al terminar
#
# Uso: docker run --rm afp-sync --list ; docker run --rm afp-sync --only chist_adjusted
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    TQDM_DISABLE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    AFP_MARTS_DIR=/app/db/bigquery/marts

# msodbcsql18 + unixodbc desde el repositorio de Microsoft (Debian 12 / bookworm).
# ACCEPT_EULA=Y acepta la licencia del driver ODBC de Microsoft.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl gnupg ca-certificates \
    && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc \
        | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
    && curl -fsSL https://packages.microsoft.com/config/debian/12/prod.list \
        > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 unixodbc \
    && apt-get purge -y --auto-remove gnupg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencias primero para aprovechar la cache de capas.
COPY sync/requirements.txt sync/requirements.txt
RUN pip install -r sync/requirements.txt

# Codigo + SQL de los marts (bq_io.refresh_marts los lee de AFP_MARTS_DIR).
COPY main.py ./
COPY sync/ sync/
COPY db/bigquery/marts/ db/bigquery/marts/

# Flags de main.py se pasan como args del contenedor (--list, --only, --start, ...).
ENTRYPOINT ["python", "main.py"]
