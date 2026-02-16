# Research Match — Plan de Accion
## Sesion Inicial: 15 de Febrero de 2026 | Actualizado: 16 de Febrero de 2026

---

## 1. Resumen de la Sesion Inicial (15-Feb)

### 1.1 Objetivo
Evaluar el estado del servidor MCP de Research Match, testearlo end-to-end, y usar la cold search para descubrir repositorios de referencia que puedan aportar al proyecto.

### 1.2 Lo que se logro

#### A. Correccion del Entry Point del Servidor
- **Bug encontrado:** El transport string usaba `"streamable_http"` (underscore) pero FastMCP espera `"streamable-http"` (guion).
- **Bug encontrado:** Se pasaba `port=` como parametro a `mcp.run()`, pero la firma solo acepta `transport` y `mount_path`.
- **Fix aplicado:** `mcp.settings.port = port` + `mcp.run(transport="streamable-http")`.

#### B. Ejecucion de Simulacion Completa
Flujo completo con 4 investigadores en molecular biology / protein folding. Todos los matches dieron YELLOW — necesitaba calibracion.

#### C. Cold Search y Analisis de 4 Repos de Referencia
- `MastersThesis` — exponential smoothing reputation, blockchain audit trail
- `fhe-ml` — TenSEAL CKKS homomorphic encryption, 200x slowdown
- `claude-skills-mcp` — MCP patterns, tool descriptions, health endpoint
- `Researcher-Tool-AI` — low value, solo UI patterns

---

## 2. Estado Actual del Proyecto (v2.8.0-contracts)

### 2.1 Lo que funciona
- 24 MCP tools implementadas y funcionales
- Registro pseudonimico con email hasheado (SHA-256)
- Research Commit con evaluacion OT/OFC + solidity multipliers
- Matching por complementariedad con semaforo bilateral calibrado (5 reglas)
- Sistema de rating anti-retaliacion (anonimo hasta que ambos califican)
- ReputationEngine con exponential smoothing O(1) + anti-abuso
- Cold search (DB interna + GitHub)
- Deep search (clona + analiza repos GitHub, 4 capas)
- Prepare commit (proforma universal: extract/validate/submit)
- Collaboration layer: tickets, reveals, file sharing, audit log
- Licencias automaticas: joint-equal, joint-weighted, advisory-only, time-limited
- **Contratos git-verificables con confirmacion bilateral**
- Transporte stdio y streamable-http
- Health endpoint (`/health`) con stats completos
- Logging estructurado (JSON/text, configurable)
- 198 tests unitarios (pytest)
- Simulacion E2E (test_simulation.py) ejercitando 19/22 tools

### 2.2 Pendientes
- `OriginalityEvaluator` usa heuristicas (Jaccard fallback para tests, sentence-transformers para produccion)
- Claude Desktop integration bloqueada (requiere DXT extension)
- FHE para scoring no evaluado aun (P2)

---

## 3. Historial de Implementacion

### Sesion 01 (15-Feb) — Discovery + Fix
- Fix entry point (transport string + port)
- Simulacion completa, cold search, analisis de 4 repos de referencia
- Creacion de PLAN_DE_ACCION.md

### Sesion 02-04 (15-Feb) — P0: Foundation
- Tool descriptions reescritas (400-800 chars con flujo + ejemplos)
- Health endpoint `/health`
- EmbeddingEngine con sentence-transformers (lazy-load, thread-safe, Jaccard fallback)

### Sesion 05-06 (15-Feb) — P1: Calibration + Tests
- Semaforo calibrado: 5 reglas, weakness_bonus 0.3→0.15, GREEN_MIN_GAIN_FLOOR=4
- ReputationEngine: exponential smoothing (alpha=0.2), running averages
- 67 unit tests (pytest), conftest.py con JaccardOnlyEmbeddingEngine
- Logging estructurado: JSON/text, env vars

### Sesion 07 (16-Feb) — v2.4.0: Collaboration Layer Step 1
- 4 tablas SQL: team_tickets, reveal_consents, shared_files, audit_log
- 3 tools: needs_create, needs_list, needs_resolve
- _write_audit_log helper, reputation effort boost
- 17 tests nuevos (total: 84)

### Sesion 08 (16-Feb) — NEED-02: Level 3 Reveal System
- 3 tools: reveal_request, reveal_respond, reveal_status
- Bilateral consent para contenido de commits
- reveal_status incluye contenido completo + reveal_matrix
- 17 tests nuevos (total: 84 → ya incluidos)

### Sesion 09 (16-Feb) — NEED-03: Automatic Licensing
- `_compute_license()`: 5 reglas (joint-equal, advisory-only, joint-weighted, time-limited)
- `research_match_team_license` tool
- Hooks en reveal_respond + needs_resolve
- 12 tests nuevos (total: 96)

### Sesion 10 (16-Feb) — NEED-04/05: File Sharing + Audit
- 2 tools: share_file, shared_files (metadata registry, bilateral L3 gate)
- 1 tool: audit_log (read-only viewer)
- MAD re-sharing detection (hash-based, tanks honesty)
- 34 tests nuevos (total: 130)

### Sesion 11 (16-Feb) — NEED-06: Deep Repository Analysis
- 1 tool: deep_search (stateless, clona + 4-layer analysis)
- analyze_repo.py (1217 lineas): git metadata, file tree, MCP extraction, gap analysis, OT/OFC scoring
- 18 tests nuevos (total: 148)

### Sesion 12 (16-Feb) — NEED-07: Universal Project Proforma
- 1 tool: prepare_commit (3 modos: extract/validate/submit)
- Extraccion automatica de proyecto + prompt universal + validacion + submission
- 25 tests nuevos (total: 173)

### Sesion 12b (16-Feb) — E2E Simulation v2
- test_simulation.py actualizado: 2 usuarios, 19/22 tools ejercitados
- Flujo completo: register → commit → match → request → team → tickets → reveals → files → ratings → audit

### Sesion 13 (16-Feb) — NEED-08: Git-Verifiable Collaboration Contracts
- 2 tools: export_contract, confirm_contract
- Tabla `collaboration_contracts` con slots bilaterales (A/B)
- `_generate_contract_content()`: markdown con parties, scores, license, verification
- `SubmitCommitInput` + migration: git_repo_url, git_commit_hash
- 4 tools actualizados: submit_commit, respond_request, team_license, health
- 25 tests nuevos (total: 198)

---

## 4. NEED-08 — Git-Verifiable Collaboration Contracts (Detalle)

### 4.1 Problema
Las licencias automaticas (NEED-03) funcionan dentro de Research Match pero no tienen enforcement externo. Si el servidor desaparece, no hay evidencia de los acuerdos.

### 4.2 Solucion
**Git como blockchain para codigo.** El contrato se genera como markdown legible, ambas partes lo commitean a sus repos, y:
- Si lo borran, la eliminacion queda en `git log`
- Disputas se resuelven leyendo commit-by-commit
- No necesita terceros ni blockchain real — git ya es inmutable

### 4.3 Componentes Implementados

| Componente | Cantidad | Detalle |
|---|---|---|
| Constantes | 5 | CONTRACT_VERSION, CONTRACT_DIR_NAME, CONTRACT_FILE_PREFIX, GIT_COMMIT_HASH_PATTERN, MAX_CONTRACT_CONFIRMATIONS_PER_TEAM |
| Tabla SQL | 1 | `collaboration_contracts` (18 columnas, bilateral confirmation slots) |
| Migration | 2 cols | `research_commits.git_repo_url`, `research_commits.git_commit_hash` |
| Pydantic models | 2 nuevos | ExportContractInput, ConfirmContractInput (con SHA-1 validator) |
| Pydantic update | 1 | SubmitCommitInput + git_repo_url + git_commit_hash |
| Helper | 1 | `_generate_contract_content()` → markdown string |
| MCP tools nuevos | 2 | export_contract, confirm_contract |
| MCP tools actualizados | 4 | submit_commit, respond_request, team_license, health |
| Tests | 25 | 6 clases: Generation, Confirmation, Content, GitRef, Pydantic, Schema |
| Index | 1 | `idx_contracts_team(team_id, status)` |

### 4.4 Flujo del Contrato

```
1. export_contract(team_id)
   → Computa licencia actual
   → Genera markdown con parties, scores, terms, verification
   → SHA-256 del contenido
   → INSERT con status='pending'
   → Retorna: contract_id, contenido, suggested_path, instrucciones

2. Cada parte guarda el archivo:
   mkdir -p .research-match/
   cp contract.md .research-match/CONTRACT_team-abc123.md
   git add . && git commit -m "Add collaboration contract"

3. confirm_contract(team_id, contract_id, git_commit_hash)
   → Primera parte: status='partial'
   → Segunda parte: status='confirmed'
   → Idempotente por usuario (mismo slot)
```

### 4.5 Status Flow del Contrato

```
pending → partial → confirmed
    ↓
superseded (si se genera nueva version)
```

### 4.6 Contenido del Contrato (markdown)

```markdown
# Research Match Collaboration Contract

**Contract ID:** `team_id-v1`
**Team / Generated / Version / License Type**

## Parties
  - Pseudonym, Role, Contribution%, Reputation
  - Latest Commit: domain, hash, OT/OFC, solidity, git refs

## License Terms
  - Type, Rationale, 4 terms

## Contribution Split
  - Porcentaje por miembro

## Collaboration State
  - Reveal state, Tickets resolved

## Verification
  - Valid when committed to BOTH repos
  - Deletion tracked by git history
  - Generated by Research Match vX.Y.Z
```

### 4.7 Decisiones de Diseno

1. **Audit action reutilizada** — `license_generated` con `details.trigger` (contract_generated / contract_confirmed). Evita migrar CHECK constraint.
2. **On-demand, no automatico** — El contrato se genera cuando el usuario lo pide, no al crear team.
3. **Versioning con supersede** — Cada export invalida contratos pending/partial anteriores.
4. **Bilateral confirmation** — Dos slots (A, B) en la misma row, idempotente por usuario.
5. **git_ref opcional** — Backward compatible, commits existentes sin git refs siguen funcionando.
6. **Markdown human-readable** — Renderiza en GitHub, legible sin herramientas especiales.

---

## 5. Plan de Accion Futuro

### Completado
- ~~P0.1 — Tool Descriptions~~ (sesion 02)
- ~~P0.2 — Health Endpoint~~ (sesion 03)
- ~~P0.3 — Sentence-Transformers~~ (sesion 04)
- ~~P1.1 — ReputationEngine exponential smoothing~~ (sesion 05)
- ~~P1.2 — Calibrar Semaforo~~ (sesion 05)
- ~~P1.3 — Tests Unitarios~~ (sesion 05, 198 tests)
- ~~P1.4 — Logging Estructurado~~ (sesion 06)
- ~~NEED-02 — Level 3 Reveal System~~ (sesion 08)
- ~~NEED-03 — Automatic Licensing~~ (sesion 09)
- ~~NEED-04 — File Sharing~~ (sesion 10)
- ~~NEED-05 — Audit Log + MAD Re-sharing~~ (sesion 10)
- ~~NEED-06 — Deep Repository Analysis~~ (sesion 11)
- ~~NEED-07 — Universal Project Proforma~~ (sesion 12)
- ~~NEED-08 — Git-Verifiable Contracts~~ (sesion 13)

### Pendiente

#### P2 — Medio Plazo (Privacy/Crypto)
- P2.1 — Evaluar viabilidad de FHE para scoring (TenSEAL benchmark)
- P2.2 — Alternativas: differential privacy, TEE, hybrid

#### P3 — Distribucion
- P3.1 — DXT extension para Claude Desktop marketplace
- P3.2 — Publicar en npm/pypi como paquete instalable

#### NEED-09+ — Features Potenciales
- Multi-party contracts (3+ members)
- Contract amendment flow (modify without supersede)
- Dispute resolution tool (reads git history)
- arXiv/Semantic Scholar integration en cold_search
- WebSocket notifications para eventos de team
- Dashboard web con visualizacion de scores

---

## 6. Metricas del Proyecto

| Metrica | v2.1.0 (15-Feb) | v2.8.0 (16-Feb) |
|---|---|---|
| MCP tools | 9 | 24 |
| SQL tables | 7 | 11 |
| Unit tests | 0 | 198 |
| Server lines | ~1400 | ~5600 |
| Test lines | 0 | ~2800 |
| Pydantic models | 6 | 18 |
| Helpers | ~10 | ~30 |
| Session docs | 1 | 13 |

---

*Proximo paso sugerido: P3.1 (DXT extension) o NEED-09 (multi-party contracts)*
