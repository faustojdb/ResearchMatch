# Sesion 08 — 2026-02-16 (noche)

## Resumen
Dogfooding post-NEED-04: re-evaluacion completa del proyecto v2.5.0 con cold search masivo (18 queries GitHub). Confirmacion de que Research Match ocupa un nicho completamente vacio. Descubrimiento de `mcp_agent_mail` como sibling arquitectonico clave.

---

## 1. Research Commit — Research Match v2.5.0

### Descripcion completa del proyecto (para cold search y dogfooding)

**Dominio:** Software Engineering / Decentralized Research Collaboration
**Subdominio:** AI-powered Originality Scoring + Bilateral Matching + IP Protection
**Problema:** Como conectar investigadores aislados trabajando en problemas similares, evaluar la originalidad de su trabajo con IA, facilitar colaboracion segura con propiedad intelectual protegida, y generar licencias automaticas — todo sin infraestructura centralizada.

**Hipotesis:** Un servidor MCP (Model Context Protocol) con evaluacion dual-axis de originalidad (OT/OFC), matching bilateral por complementariedad (no similaridad), revelacion progresiva de 4 niveles con consentimiento mutuo, tickets estructurados (sin chat), licenciamiento automatico basado en actividad, y registro de archivos con gate bilateral resuelve el problema de colaboracion investigativa descentralizada.

**Stack:** Python 3.12, FastMCP, SQLite WAL, sentence-transformers (all-MiniLM-L6-v2), Pydantic, numpy, pytest

### Sistemas implementados (v2.5.0)

| Sistema | Descripcion | Tools |
|---------|-------------|-------|
| **Registro pseudonimico** | Email hasheado SHA-256, pseudonimos unicos | register, my_profile |
| **Research Commits** | Submision estructurada con dominio, hipotesis, teoria, demos, adhoc, cherry-picking, solidez por componente | submit_commit |
| **Evaluacion de originalidad** | Dual-axis: OT (Theoretical) y OFC (Formal-Computational) con multiplicadores de solidez (proven→cherry_picked) | analyze_work |
| **Sentence-transformers** | Cosine similarity semantica con lazy-load thread-safe, Jaccard fallback | (interno) |
| **Matching bilateral** | Semaforo 5-reglas (GREEN/YELLOW/RED), ganancia por complementariedad con weakness_bonus, badge de reputacion | find_collaborators |
| **Reputacion** | Exponential smoothing O(1), 3 ejes (honesty 50%, quality 30%, effort 20%), anti-retaliacion, deteccion de abuso | rate_user |
| **Cold search** | Dual obligatorio: DB interna + GitHub API, no requiere registro | cold_search |
| **NEED-01: Tickets** | Structured tickets (need_help, can_offer, warning, question) en 5 areas, reemplazan chat libre | needs_create/list/resolve |
| **NEED-02: Reveal L3** | Consentimiento bilateral explicito para ver Research Commit completo, reveal matrix, contenido revelado en status | reveal_request/respond/status |
| **NEED-03: Licensing** | 5 reglas automaticas (joint-equal, advisory-only, joint-weighted, time-limited), floor 25%, recalculo lazy | team_license |
| **NEED-04: File sharing** | Registro de metadata (path + hash + desc), gate bilateral L3, dedup idempotente, 50 files/team | share_file, shared_files |
| **Audit trail** | Inmutable por insercion (INSERT-only), 10 action types, indexado por team y actor | (interno) |
| **Health endpoint** | GET /health con stats completos (users, commits, matches, teams, tickets, shared_files, audit) | (HTTP) |
| **Logging estructurado** | JSON/text configurable, _log_tool_call decorator en 19 tools | (interno) |

### Metricas
- **19 MCP tools** (10 core + 9 collaboration layer)
- **113 tests** (pytest, Jaccard-only para determinismo)
- **~3700 LOC** server principal
- **8 tablas SQL** (users, research_commits, matches, collaboration_requests, ratings, teams+team_members, team_tickets, reveal_consents, shared_files, audit_log)
- **Transporte:** stdio (default) + streamable-http

### Conexiones interdisciplinarias
- **Game Theory:** MAD (destruccion mutua asegurada) como deterrent de re-sharing
- **Contract Law:** Licenciamiento automatico replica patrones de contratos marco
- **Information Theory:** Evaluacion de originalidad basada en divergencia del corpus
- **Mechanism Design:** Semaforo bilateral como mecanismo de truthful revelation
- **Signal Protocol:** Reveal progresivo inspirado en forward secrecy (4 niveles)

---

## 2. Cold Search — 18 queries GitHub

### Queries especificas (combinaciones exactas del proyecto)

| # | Query | Resultados | Assessment |
|---|-------|------------|------------|
| 1 | MCP server audit trail immutable log sqlite | **0** | Nicho vacio |
| 2 | bilateral consent re-sharing violation detection IP | **0** | Nicho vacio |
| 3 | research collaboration IP protection bilateral matching | **0** | Nicho vacio |
| 4 | MCP server file sharing metadata registry consent | **0** | Nicho vacio |
| 5 | sqlite audit trigger automatic immutable trail python | **0** | Nicho vacio |
| 6 | Gale-Shapley stable matching complementarity bilateral | **0** (16 broad) | Solo textbook implementations |
| 7 | progressive disclosure consent system MCP tool | **0** | Nicho vacio |
| 8 | research matching originality scoring MCP | **0** (5 broad) | Solo plagiarism checkers basicos |

**Conclusion:** 8/8 queries exactas retornan 0. El feature set combinado de Research Match no existe en ningun otro proyecto open-source.

### Queries amplias (busqueda de componentes adoptables)

| # | Query | Top result | Stars | Relevancia |
|---|-------|-----------|-------|------------|
| 9 | fastmcp | jlowin/fastmcp | 22,867 | Framework (ya adoptado) |
| 10 | fastmcp collaboration | **Dicklesworthstone/mcp_agent_mail** | **1,692** | **ALTA — sibling arquitectonico** |
| 11 | sqlite audit trail | simon-weber/Instant-SQLite-Audit-Trail | 16 | MEDIA — trigger-based audit |
| 12 | license generator automatic | cpm-cmake/CPMLicenses.cmake | 41 | BAJA — context diferente |
| 13 | researcher matching collaboration | **purnamaanaking/sparring** | 1 | MEDIA — matching de investigadores |
| 14 | consent management system | dmind-gmbh/extension-cookieman | 37 | BAJA — GDPR cookies |
| 15 | MCP pydantic python server | ShunyaAI/snow-mcp | 5 | BAJA — 60 tools ServiceNow |
| 16 | reputation scoring system trust | KOSASIH/MatrixAI-Core | 17 | BAJA — blockchain trust |
| 17 | skill gap analysis matching | ananttripathi/Resume-Analyzer-MLOps | 6 | BAJA — job matching |
| 18 | DXT extension claude desktop | **milisp/awesome-claude-dxt** | **154** | ALTA — marketplace reference |

---

## 3. Repos descubiertos — Analisis de relevancia

### TIER 1 — Estudiar a fondo

#### `Dicklesworthstone/mcp_agent_mail` (1,692 stars)
**El hallazgo mas importante de esta cold search.**
- FastMCP + Git + SQLite (MISMO STACK)
- Coordination layer para AI agents con identidades, inboxes, threads
- Advisory file leases (similar a nuestro consent system)
- 1,692 stars indica calidad y comunidad
- **Adoptar:** message queuing patterns, file lease advisory, multi-tool organization
- **Diferencia clave:** ellos coordinan AI agents, nosotros coordinamos investigadores humanos

#### `milisp/awesome-claude-dxt` (154 stars)
- Lista curada de Claude Desktop Extensions
- Referencia esencial para packaging y publishing DXT
- Formato, convenciones, lo que funciona en el marketplace
- **Accion:** estudiar top extensions para entender standards

### TIER 2 — Revisar selectivamente

#### `purnamaanaking/sparring` (1 star, PHP)
- "Matching Research Partner System based on Relevance of Research Topics"
- Competidor conceptual directo (research matching)
- PHP, probablemente basico, pero ver como modelan el matching

#### `simon-weber/Instant-SQLite-Audit-Trail` (16 stars)
- Ya identificado en sesion 04
- Trigger-based audit (mas tamper-resistant que application-level INSERT)
- Evaluado: util pero nuestro approach actual funciona bien para MVP

#### `yash3567/Collab-Hub` (8 stars, JavaScript)
- Matching por interests, skills, goals
- Posible inspiracion para complementarity scoring

#### `nowledge-co/claude-dxt` (4 stars, Python)
- Claude DXT en Python — referencia de packaging para nuestro caso exacto

### TIER 3 — Descartados / baja prioridad
- `WildMeOrg/Wildbook` (128 stars) — wildlife conservation, dominio diferente
- `ShunyaAI/snow-mcp` (5 stars) — ServiceNow, util solo como ejemplo de MCP grande
- Los plagiarism checkers (DocInsight, etc.) — no manejan Research Commits ni dual-axis

---

## 4. Lo que buscamos / nos falta (roadmap v3.0)

### A. Re-sharing Control (NEED-05 del manifesto original)
**Busca:** violation detection, origin_user_id enforcement, MAD mechanism
**Found:** NADA en GitHub. Tenemos que inventarlo.
**Implementacion propuesta:**
- `_check_resharing_violation(db, team_id, file_hash)` — detecta si alguien comparte archivo de otro
- Penalty automatica: honesty=1, perdida de derechos
- `research_match_audit_log` tool para inspeccionar trail

### B. Audit Log Viewer (tool pendiente)
**Busca:** MCP tool read-only para ver el audit trail
**Found:** simon-weber/Instant-SQLite-Audit-Trail (trigger-based)
**Implementacion propuesta:**
- `research_match_audit_log` — listar entradas del audit trail con filtros (action, actor, date range)
- Read-only, no modifica nada

### C. Improved Matching Algorithm
**Busca:** Gale-Shapley, complementarity-based, not similarity-based
**Found:** Solo textbook implementations (max 3 stars)
**Implementacion propuesta:**
- Evaluar `greedy_max_weighted_matching()` del paper ECMLPKDD2025 (ya clonado en sesion 04)
- Weight = complementariedad OT/OFC entre dos researchers
- Mantener semaforo actual como scoring, agregar Gale-Shapley como assignment opcional

### D. DXT Marketplace Publishing
**Busca:** Como empaquetar un FastMCP Python server como DXT
**Found:** awesome-claude-dxt (154 stars), nowledge-co/claude-dxt (4 stars, Python)
**Implementacion propuesta:**
- Estudiar nowledge-co/claude-dxt como template
- Adaptar manifest.json y packaging
- Publicar en marketplace

### E. Deep Search (NEED-06)
**Busca:** cold_search que clona + analyze_repo.py automatico
**Found:** NADA equivalente
**Implementacion propuesta:**
- Nuevo tool `research_match_deep_search` que dado un repo URL:
  1. Clona shallow (--depth 1) a /tmp
  2. Corre analyze_repo.py
  3. Compara contra nuestro proyecto
  4. Retorna analisis estructurado

### F. mcp_agent_mail integration study
**Nuevo descubrimiento de esta sesion.**
- Estudiar patterns de Dicklesworthstone/mcp_agent_mail (1,692 stars)
- Focus: cómo organizan 40+ tools, file lease system, message threading
- Evaluar si algún pattern mejora nuestra collaboration layer

---

## 5. Conclusiones

1. **Research Match v2.5.0 ocupa un nicho completamente vacio en GitHub.** 8/8 queries combinadas retornan 0 resultados. No existe otro proyecto que combine MCP + originality scoring + bilateral matching + consent reveals + automatic licensing.

2. **El sibling mas cercano es `mcp_agent_mail`** (1,692 stars) — mismo stack (FastMCP + SQLite + Python), problema relacionado (coordination layer), pero para AI agents en vez de investigadores humanos.

3. **La capa de colaboracion (NEED-01 a NEED-04) distingue al proyecto de v2.2.** Antes eramos "yet another MCP server". Ahora el sistema de tickets + reveals + licensing + file sharing es un stack completo sin equivalente.

4. **Los gaps restantes no tienen solucion open-source.** Re-sharing control (MAD), audit viewer, deep search — son features que tenemos que inventar.

5. **La oportunidad DXT es real.** El ecosistema tiene solo ~15 repos, awesome-claude-dxt tiene 154 stars. Publicar temprano nos da visibilidad.
