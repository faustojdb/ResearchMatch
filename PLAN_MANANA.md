# Plan de Trabajo — Cloud Run Deploy + DXT Marketplace

## Estado Actual (2026-02-18)

| Componente | Estado |
|-----------|--------|
| Firebase project `research-match-41e91` | Activo, Firestore us-central1 |
| 24 MCP tools (dual-backend) | Completo, E2E verificado |
| Algolia `research_commits` | Configurado, SDK v4 fix aplicado |
| 98 tests (emulador) | PASS |
| Firestore indexes + rules | Desplegados |
| `.env` + credentials | Configurados localmente |

### Version Mismatch (resolver primero)

| Archivo | Version actual | Deberia ser |
|---------|---------------|-------------|
| `pyproject.toml` | 3.0.0-alpha.2 | 3.0.0 |
| `manifest.json` | 2.8.0 | 3.0.0 |
| `SERVER_VERSION` (server.py) | 2.8.0-contracts | 3.0.0 |
| `build_alpha.sh` | 2.8.0 | 3.0.0 |

---

## FASE 1: Version Sync + Cleanup (~30 min)

### 1.1 Sincronizar versiones a 3.0.0
- `pyproject.toml`: version = "3.0.0"
- `manifest.json`: version = "3.0.0"
- `src/research_match_server.py`: SERVER_VERSION = "3.0.0"
- `build_alpha.sh`: actualizar version string

### 1.2 Limpiar archivos obsoletos
- Eliminar `sessions/2026-02-17_sesion-16-firebase-migration-plan.md` (plan completado)
- Verificar que `.gitignore` tiene todo cubierto
- Eliminar `firebase-credentials.json` del tracking si aplica

---

## FASE 2: Cloud Run Deploy (~3-4 horas)

### 2.1 Crear Dockerfile

```dockerfile
# Multi-stage: deps + app
FROM python:3.12-slim AS builder
RUN pip install uv
WORKDIR /app
COPY pyproject.toml .
RUN uv pip install --system -r pyproject.toml

FROM python:3.12-slim
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY src/ src/
COPY pyproject.toml .

# sentence-transformers model pre-download
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

ENV PORT=8080
EXPOSE 8080
CMD ["python", "-m", "src.research_match_server", "--http", "8080"]
```

**Nota:** Cloud Run provee Application Default Credentials (ADC) automaticamente.
No necesita `GOOGLE_APPLICATION_CREDENTIALS` — usa el service account del proyecto.

### 2.2 Crear .dockerignore

```
venv/
.venv/
*.db
*.db-shm
*.db-wal
__pycache__/
.git/
.claude/
research_refs/
sessions/
tests/
*.dxt
*.zip
firebase-credentials.json
.env
```

### 2.3 Google Cloud Setup

```bash
# 1. Habilitar APIs necesarias
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com

# 2. Crear Artifact Registry (Docker)
gcloud artifacts repositories create research-match \
  --repository-format=docker \
  --location=us-central1

# 3. Almacenar secretos en Secret Manager
echo -n "1TAPVC99Z1" | gcloud secrets create ALGOLIA_APP_ID --data-file=-
echo -n "<api-key>" | gcloud secrets create ALGOLIA_API_KEY --data-file=-

# 4. Dar permisos al service account de Cloud Run
PROJECT_NUM=$(gcloud projects describe research-match-41e91 --format='value(projectNumber)')
SA="${PROJECT_NUM}-compute@developer.gserviceaccount.com"

gcloud projects add-iam-policy-binding research-match-41e91 \
  --member="serviceAccount:${SA}" \
  --role="roles/datastore.user"

gcloud secrets add-iam-policy-binding ALGOLIA_APP_ID \
  --member="serviceAccount:${SA}" \
  --role="roles/secretmanager.secretAccessor"

gcloud secrets add-iam-policy-binding ALGOLIA_API_KEY \
  --member="serviceAccount:${SA}" \
  --role="roles/secretmanager.secretAccessor"
```

### 2.4 Build + Deploy

```bash
# Build local (test)
docker build -t research-match .
docker run -p 8080:8080 research-match
curl http://localhost:8080/health

# Build y push a Artifact Registry
gcloud builds submit --tag us-central1-docker.pkg.dev/research-match-41e91/research-match/server:v3.0.0

# Deploy a Cloud Run
gcloud run deploy research-match \
  --image us-central1-docker.pkg.dev/research-match-41e91/research-match/server:v3.0.0 \
  --platform managed \
  --region us-central1 \
  --memory 4Gi \
  --cpu 2 \
  --timeout 300 \
  --min-instances 0 \
  --max-instances 10 \
  --set-env-vars "ALGOLIA_INDEX_NAME=research_commits,RESEARCH_MATCH_LOG_FORMAT=json" \
  --set-secrets "ALGOLIA_APP_ID=ALGOLIA_APP_ID:latest,ALGOLIA_API_KEY=ALGOLIA_API_KEY:latest" \
  --allow-unauthenticated
```

### 2.5 Verificacion

```bash
# Health check
SERVICE_URL=$(gcloud run services describe research-match --region us-central1 --format='value(status.url)')
curl ${SERVICE_URL}/health

# MCP test (streamable-http)
# Usar el script E2E de session 15 apuntando a SERVICE_URL
```

### 2.6 Consideraciones Cloud Run

| Parametro | Valor | Razon |
|-----------|-------|-------|
| Memory | 4 GB | sentence-transformers (~1.5GB) + Firestore SDK |
| CPU | 2 vCPU | async processing |
| Min instances | 0 | Ahorro de costos (cold start ~30s) |
| Max instances | 10 | Escala automatica |
| Timeout | 300s | deep_search puede tardar |
| Concurrency | 80 | Default, MCP es lightweight |
| ADC | Automatico | Cloud Run service account tiene acceso a Firestore |

### 2.7 Adaptar firebase_init.py para ADC

El codigo actual ya soporta ADC:
```python
if cred_path and os.path.isfile(cred_path):
    cred = credentials.Certificate(cred_path)
else:
    _app = firebase_admin.initialize_app()  # <-- ADC automatico en Cloud Run
```

Pero `GOOGLE_APPLICATION_CREDENTIALS` se usa para decidir Firestore vs SQLite:
```python
use_firestore = bool(os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"))
```

**Fix necesario:** Agregar env var `RESEARCH_MATCH_BACKEND=firestore|sqlite` como alternativa:
```python
backend = os.environ.get("RESEARCH_MATCH_BACKEND", "")
use_firestore = backend == "firestore" or bool(os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"))
```

---

## FASE 3: DXT Marketplace Update (~1-2 horas)

### 3.1 Actualizar manifest.json
- Version: 3.0.0
- Agregar `algoliasearch>=4.0.0` a dependencies si no esta
- Verificar que `mcp_config.env` incluye las env vars necesarias

### 3.2 Actualizar user_config en manifest.json
Agregar opcion para Cloud Run backend:
```json
"user_config": {
  "backend": {
    "type": "string",
    "default": "sqlite",
    "description": "Backend: 'sqlite' (local) or 'firestore' (cloud)"
  },
  "database_path": {
    "type": "string",
    "default": "",
    "description": "SQLite database path (only for sqlite backend)"
  }
}
```

### 3.3 Rebuild DXT
```bash
./build_alpha.sh  # Genera research-match-3.0.0.dxt
```

### 3.4 Test en Claude Desktop
1. Instalar DXT en Claude Desktop
2. Verificar que los 24 tools aparecen
3. Test: register → submit_commit → cold_search

### 3.5 Crear GitHub Release
```bash
gh release create v3.0.0 \
  research-match-3.0.0.dxt \
  --title "Research Match v3.0.0 — Firebase + Cloud Run" \
  --notes "..."
```

---

## FASE 4: CI/CD (opcional, post-deploy) (~2 horas)

### 4.1 GitHub Actions: Test on PR
`.github/workflows/test.yml`
- Trigger: pull_request
- Steps: start Firestore emulator, run pytest

### 4.2 GitHub Actions: Deploy on Push
`.github/workflows/deploy.yml`
- Trigger: push to main
- Steps: build Docker, push to Artifact Registry, deploy to Cloud Run

---

## Resumen de Entregables

| # | Entregable | Fase | Prioridad |
|---|-----------|------|-----------|
| 1 | Version sync (3.0.0) | 1 | Alta |
| 2 | Dockerfile + .dockerignore | 2 | Alta |
| 3 | Backend env var fix | 2 | Alta |
| 4 | Cloud Run deploy + verificacion | 2 | Alta |
| 5 | DXT rebuild v3.0.0 | 3 | Alta |
| 6 | Test en Claude Desktop | 3 | Alta |
| 7 | GitHub Release | 3 | Media |
| 8 | CI/CD workflows | 4 | Baja |

## Riesgos

| Riesgo | Mitigacion |
|--------|-----------|
| sentence-transformers build lento (~5min) | Multi-stage Dockerfile, model pre-download en build |
| Cold start Cloud Run (~30s) | Min instances=1 si latencia importa ($$$) |
| Algolia API key en logs | Usar Secret Manager, nunca env vars directos |
| DXT size crece por Algolia dep | El SDK es ligero (~200KB), no impacta |
| ADC no funciona en Cloud Run | Verificar que service account tiene roles correctos |

## Prerequisitos

```bash
# Google Cloud CLI
gcloud --version        # >= 400.0.0
gcloud auth login
gcloud config set project research-match-41e91

# Docker (para build local)
docker --version        # >= 20.0

# GitHub CLI (para release)
gh --version            # >= 2.0
```
