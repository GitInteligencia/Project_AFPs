# HANDOFF — Traspaso del proyecto AFP Chile Dashboard

> ## Estado 2026-09: migración a GCP en curso
>
> El proyecto se está moviendo a Google Cloud (proyecto `pat-uat-global`, región
> `southamerica-west1`): web en **Cloud Run** (`afp-web`), datos en **BigQuery**
> (`afp_raw`/`afp_dim`/`afp_mart`/`afp_ops`/`afp_stg`), pipeline como **Cloud Run job**
> (`afp-sync`) disparado por Cloud Scheduler los días 8 y 18 o a mano desde GitHub Actions,
> login con Identity Platform y CI/CD en GitHub Actions. Nada del alcance funcional cambia
> (mismas secciones, mismos números, mismos nombres de vistas).
>
> - **Plan y decisiones**: `PLAN_MIGRACION_GCP.md` (D1–D7, fases F0–F6, mapeo objeto por objeto).
> - **Operación en GCP** (corrida mensual, logs, fallos, secretos, IP NAT, costos): `docs/GCP_RUNBOOK.md`.
> - **Andamiaje e infra** (diagnóstico de permisos, ticket a infra, setup idempotente): `infra/README.md`.
>
> **Todo lo que sigue en este documento describe el flujo LEGACY — corrida desde la laptop
> en red Patria + Supabase + Vercel — que sigue VIGENTE hasta el corte (F6 del plan).**
> Mientras dure la convivencia, la corrida mensual legacy se sigue haciendo como se explica
> abajo; en paralelo el job de GCP escribe en BigQuery y se valida la paridad. Cuando se
> haga el corte, este contenido pasa a ser histórico y el runbook manda.

---

Guía para la persona que hereda el mantenimiento del proyecto, con foco en la
**corrida mensual de actualización de datos**. Leer esto primero; el detalle
técnico está en los documentos listados al final.

---

## 1. Qué es este proyecto

Dashboard web (Next.js + Vercel) que reproduce el reporte mensual de AFPs de
Chile (~48 páginas PDF, 10 secciones) para el equipo de Sales/Distribution.
Los datos fluyen así:

```
Procesos del equipo (cargan las tablas fuente en SQL Server)
    ▼
SQL Server: Inteligencia_Mercado.dbo.*        ← fuente de verdad, historia completa
    │  sync (scripts en sync/, orquestados por main.py)
    ▼
Supabase (Postgres, vía REST API):            ← solo la ventana que usa el dashboard
  tablas espejo + vistas v_* + matviews mv_*
    │
    ▼
web/ (Next.js) → deploy en Vercel
```

> **Nota histórica**: hasta 2026-07 el proyecto scrapeaba spensiones.cl
> directamente (`sync/sync_sp_xml.py`, `sync/sync_sp_cotizantes.py`). Esos
> scrapers quedaron **retirados**: hoy las tablas fuente las mantiene el
> equipo en SQL Server y `main.py` solo espeja SQL Server → Supabase. Los
> scripts siguen en `sync/` por si hicieran falta como referencia.

La corrida mensual consiste en ejecutar la cadena de arriba con `main.py`
(sección 4).

---

## 2. Cómo recibir el proyecto: carpeta completa, NO `git clone`

El traspaso correcto es **copiar esta carpeta entera**. Un clone del repo git
llega incompleto, porque el `.gitignore` excluye a propósito:

- `.env` — las credenciales (sin esto nada corre)
- `CLAUDE.md` — notas de arquitectura y restricciones no obvias
- `Codigos_legacy/` — el pipeline Python legado, referencia de cómo se calcula cada cubo
- `validacion/` — el validador Excel-vs-Supabase (`compare_views.py` + `00_Inputs.xlsx`)
- `Excels construccion pdf/`, `PDFs de reporte actual/` — los workbooks y PDFs del reporte original
- `MANUAL_AFP_CL_ALTERNATIVE_ASSETS.md`, `PIPELINE_DATA_GAPS.md`

---

## 3. Prerrequisitos (una sola vez, en la máquina nueva)

### 3.1 Software

1. **Python 3.10+** y dependencias:
   ```powershell
   pip install -r sync/requirements.txt
   ```
2. **ODBC Driver 18 for SQL Server** (descarga gratuita de Microsoft).
   Es obligatorio: los scripts lo usan con `Encrypt=optional` y
   `TrustServerCertificate=yes`. Con el driver viejo `{SQL Server}` los
   scrapers fallan con `HYC00 Optional feature not implemented`.
3. (Solo para tocar el frontend) Node.js 20+ y `npm install` dentro de `web/`.

### 3.2 Red

La corrida debe ejecutarse **desde la red de Patria** (oficina o VPN): el SQL
Server `Inteligencia_Mercado` solo es alcanzable ahí. Supabase va por
HTTPS/443, así que no tiene problema de firewall — por eso mismo el sync usa
la **REST API de Supabase y no Postgres directo** (la red corporativa bloquea
los puertos 5432/6543). No "simplificar" el sync a psycopg/SQLAlchemy: funciona
en algunas redes y falla silenciosamente en la corporativa.

### 3.3 Credenciales y accesos que hay que PEDIR (no vienen en la carpeta)

| Acceso | Para qué | Cómo se obtiene |
|---|---|---|
| Usuario SQL Server (`DB_UID`/`DB_PWD` en `.env`) | Leer `Inteligencia_Mercado` (todas las tablas fuente `AFP_CL_*`, `TBL_IPA_V2`, dims) | Verificar si la cuenta del `.env` heredado sigue vigente; si era personal del dueño anterior, pedir una propia a TI |
| **Login al dashboard web de Supabase** (cuenta en la organización, proyecto activo: ProjectAFP_v2) | Reactivar el proyecto cuando se auto-pausa, editar vistas, SQL editor | Que el dueño anterior te invite a la organización de Supabase |
| Cuenta/proyecto de **Vercel** | Deploy del frontend `web/` | Acceso al team de Vercel donde vive el proyecto (no se necesita para la corrida mensual de datos) |

> **Si hay que re-importar el proyecto en Vercel** (cambio de cuenta, nuevo
> team): Import desde GitHub con **Root Directory = `web/`** (¡no la raíz!) y
> las **TRES** environment variables de `web/.env.local`:
> `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY` y
> `SUPABASE_SERVICE_ROLE_KEY`. Si falta la anon key, todo el sitio responde
> "Internal Server Error" (la usa el middleware de auth en cada request).
> Tras agregar/cambiar variables hay que hacer **Redeploy** — no aplican al
> deploy ya hecho.

> **Importante — auto-pausa de Supabase**: el proyecto está en free tier y se
> **pausa solo tras ~1 semana sin actividad**. Si la corrida mensual falla con
> errores de conexión a Supabase, lo primero es entrar a app.supabase.com y
> revisar si el proyecto está pausado (botón "Restore"). La service-role key
> del `.env` NO sirve para despausar; se necesita el login web. Ya ocurrió una
> vez (2026-06-22).

El `.env` en la raíz ya trae los valores actuales (ver `.env.example` para la
estructura). La `SUPABASE_SERVICE_ROLE_KEY` **bypasea RLS: nunca exponerla en
código de navegador** ni commitearla.

---

## 4. La corrida mensual

### 4.1 Cuándo

Cuando SQL Server ya tenga cargado el mes nuevo (las tablas `*_sd`, `VC_PAT` y
`BBG_Returns` suelen estar en la primera quincena del mes siguiente). No hace
falta cronometrar nada con precisión: cada paso toma **lo que haya** en su
tabla fuente, y correr más de una vez no daña nada — **todos los pasos son
idempotentes** (DELETE por fecha + INSERT, o UPSERT). Si una fuente aún no
tiene el mes, la corrida siguiente lo recoge.

Caso especial: `AFP_CL_CHIST_ADJUSTED` (cartera detallada) se publica con
**~4 meses de rezago** (en julio 2026 el último CHIST era feb 2026). El paso
`chist_adjusted` ancla su ventana al `MAX(fecha)` de la propia fuente
(re-sincroniza los últimos 3 meses publicados), así que no hay que hacer nada
especial: cuando el equipo cargue el mes nuevo de CHIST en SQL, la siguiente
corrida de `main.py` lo toma sola (o se adelanta con
`python main.py --only chist_adjusted`).

### 4.2 Comando

```powershell
cd <carpeta del proyecto>
python main.py --list              # 1) ver el plan sin ejecutar nada
python main.py                     # 2) la corrida mensual completa
```

Qué hace, en orden:

| # | Paso | Qué mueve |
|---|---|---|
| 1 | `cotizantes` | `AFP_CL_Cotizantes` → `cotizantes_afp` (ventana >= 2025-01) |
| 2 | `core` | Dims + `tipo_cambio` + `valores_cuota_patrimonio`, incremental; refresca matviews al final |
| 3 | `sd_asset_class` | `AFP_CL_01_sd/02_sd` → `sd_asset_class_*` |
| 4 | `consolidated_sd` | `AFP_CL_09_17_25_sd_consolidated` → `consolidated_sd` |
| 5 | `chist_adjusted` | `AFP_CL_CHIST_ADJUSTED` → `chist_adjusted` (ventana auto-anclada a la fuente); refresca matviews al final |
| 6 | `bbg_returns` | `AFP_CL_BBG_Returns` → `bbg_returns` |
| 7 | `dim_bd_previa` | `DIM_BD_Previa_AFPCL` → `dim_bd_previa` (reload completo, chica) |
| 8 | `ipd_strategy` | `TBL_IPA_V2` → `ipd_*` (full reload; datos de Strategy y Chilean Stocks. Es el paso más lento; `--skip-strategy` lo omite, pero entonces esas secciones no se actualizan) |

Los pasos 3, 4 y 6 re-sincronizan una ventana de 3 meses hacia atrás (default)
para absorber correcciones retroactivas de la SPE; el paso 5 hace lo mismo
pero contando desde el último mes publicado de CHIST.

### 4.3 Flags útiles

```powershell
python main.py --only chist_adjusted         # re-correr un solo paso
python main.py --months-back 6               # ventana más ancha (correcciones viejas)
python main.py --start 2025-01-01            # ventana explícita (aplica también a CHIST)
python main.py --keep-going                  # no parar en el primer fallo
python main.py --skip-strategy               # sin ipd_strategy (más rápida)
```

### 4.4 Verificación post-corrida

1. El resumen final de `main.py` debe mostrar `OK` en todos los pasos.
2. Abrir el dashboard: los badges "as of" de cada módulo deben mostrar el mes
   nuevo (la vista `v_module_freshness` en Supabase reporta el rezago por módulo).
3. (Opcional, solo cubos de alternativos) validar contra el Excel del proceso
   legado si todavía se produce:
   ```powershell
   python validacion/compare_views.py --fecha 2026-06-30
   ```
   `[OK]`/`[WARN]`/`[FAIL]` por cubo según tolerancia.

### 4.5 Mantenciones manuales que `main.py` NO cubre

- **`dim_valorizacion_remanente`** (Supabase): no tiene fuente en SQL Server;
  se mantiene a mano directamente en Supabase. Solo tocar si cambia la
  clasificación de valorización de algún fondo.
- **`sync/load_bd_funds_nt.py`**: carga la taxonomía `nt_*` desde
  `BD_Funds.xlsx` a `dim_bd_funds`. Correr solo cuando el equipo entregue una
  versión nueva del Excel.
- **Matviews**: los pasos `core` y `chist_adjusted` ya refrescan
  `mv_chist_aa`/`mv_aum` vía la RPC `refresh_alternatives_matviews()`. Si se
  corre un sync suelto fuera de `main.py` y el home de Alternatives queda
  desactualizado, ejecutar esa RPC a mano en el SQL editor de Supabase:
  `select refresh_alternatives_matviews();`

---

## 5. Si algo falla (síntoma → causa probable)

| Síntoma | Causa probable / acción |
|---|---|
| Errores de conexión / timeout contra Supabase en todos los pasos | Proyecto free-tier **pausado**. Entrar a app.supabase.com → Restore. |
| `HYC00 Optional feature not implemented` | Falta ODBC Driver 18; instalarlo (sección 3.1). |
| No conecta a SQL Server | ¿Estás en red/VPN de Patria? ¿Credenciales `DB_UID`/`DB_PWD` vigentes? |
| Timeout `57014` en el home de Alternatives del dashboard | Matviews sin refrescar → correr la RPC (sección 4.5). |
| El dashboard muestra un mes viejo pese a corrida OK | Revisar `v_module_freshness`; puede que la tabla fuente en SQL Server aún no tenga el mes (CHIST rezaga ~4 meses — ver 4.2). El techo de recencia lo pone la fuente, no el sync. |
| Un paso escribe 0 filas | Normal si la fuente aún no tiene el mes nuevo; el paso es incremental y no encuentra fechas nuevas. |

---

## 6. Cosas no obvias que conviene saber antes de "arreglar" algo

- **`v_limits` tiene un bug a propósito**: replica un bug del Excel legado
  (falta el factor `Remanente × 0.6`) para que la validación contra
  `00_Inputs.xlsx` cuadre. La versión corregida es `v_limits_corrected`. No
  "arreglar" `v_limits`.
- **Gaps documentados vs el PDF legado** (decisión: mantener el dato correcto
  y documentar, no replicar el bug): Aegon HY (share class faltante en el
  legado), Pearl Diver (excluido por bug de filtro en el legado), derivados en
  Foreign DI. Detalle en `PIPELINE_DATA_GAPS.md` y en los comentarios de las
  vistas.
- **`historial_carteras` en Supabase ya viene filtrado** a instrumentos
  alternativos (`Filtro1 = 'Si'`) desde el sync; no es la tabla cruda.
- **Convención de nombres**: cada cubo del reporte vive en una vista `v_<cubo>`
  en Supabase; `validacion/compare_views.py` es el mapeo canónico
  hoja-Excel ↔ vista ↔ tolerancia.
- SQL Server es la **fuente de verdad** con historia completa; Supabase es un
  espejo con ventana acotada (free tier = 500 MB). Ante dudas de datos,
  auditar contra SQL Server.

---

## 7. Mapa de documentación

| Documento | Qué contiene |
|---|---|
| `README.md` | Visión general, stack, layout del repo |
| `PLAN_MIGRACION_GCP.md` | **Migración a GCP**: decisiones D1–D7, fases, mapeo objeto por objeto |
| `docs/GCP_RUNBOOK.md` | **Operación en GCP**: corrida mensual (Scheduler / run-sync), logs, fallos, secretos, IP NAT, costos |
| `infra/README.md` | Ticket a infra, allowlist de la IP NAT, config de GitHub, fallback Cloud Build |
| `CLAUDE.md` | Arquitectura, restricciones no obvias, comandos (el más denso; leerlo entero) |
| `MANUAL_AFP_CL_ALTERNATIVE_ASSETS.md` | El proceso mensual legado (qué debe calcular el reporte) |
| `LINEAGE.md` | Linaje de datos: de qué tabla/vista sale cada sección del dashboard |
| `PIPELINE_DATA_GAPS.md` | Diferencias conocidas y justificadas vs el PDF legado |
| `PLAN_SQL_SINGLE_SOURCE.md` | Diseño de la migración a SQL Server como fuente única |
| `sync/*.sql` | DDL de tablas y vistas (SQL Server y Supabase) |
| `Codigos_legacy/` | Pipeline Python legado, referencia de cálculo (solo lectura) |

---

*Generado 2026-07-09 como parte del traspaso del proyecto. Encabezado "Estado 2026-09" y mapa de documentación actualizados el 2026-09-28 por la migración a GCP.*
