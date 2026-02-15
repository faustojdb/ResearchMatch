# Research Match — Plan de Acción
## Sesión del 15 de Febrero de 2026

---

## 1. Resumen de la Sesión

### 1.1 Objetivo
Evaluar el estado del servidor MCP de Research Match, testearlo end-to-end, y usar la cold search para descubrir repositorios de referencia que puedan aportar al proyecto.

### 1.2 Lo que se logró

#### A. Corrección del Entry Point del Servidor
- **Bug encontrado:** El transport string en `research_match_server.py` usaba `"streamable_http"` (underscore) pero la API de FastMCP espera `"streamable-http"` (guión).
- **Bug encontrado:** Se pasaba `port=` como parámetro a `mcp.run()`, pero la firma solo acepta `transport` y `mount_path`.
- **Fix aplicado:** Se cambió a `mcp.settings.port = port` + `mcp.run(transport="streamable-http")`.
- **Archivo:** `src/research_match_server.py`, líneas 1870-1877.

#### B. Ejecución de Simulación Completa (test_simulation.py)
Se ejecutó el flujo completo con 4 investigadores simulados en biología molecular / protein folding:

| Investigador | Pseudónimo | OT Score | OFC Score | Solidez |
|---|---|---|---|---|
| Tú | ProteinTheorist_AR | 35.3% | 48.3% | speculative |
| María | CompBio_Maria | 53.8% | 74.6% | functional |
| Kenji | MathBio_Kenji | 57.1% | 64.1% | proven |
| Alex | BioGeneral_Alex | 19.2% | 19.6% | cherry_picked |

**Resultados de matching (desde perspectiva de ProteinTheorist_AR):**

| Candidato | Semáforo | Complementariedad | Tú ganás | Ellos ganan |
|---|---|---|---|---|
| CompBio_Maria | 🟡 YELLOW | 37.5% | 66.4% | 8.6% |
| MathBio_Kenji | 🟡 YELLOW | 32.3% | 54.9% | 9.7% |
| BioGeneral_Alex | 🟡 YELLOW | 28.1% | 6.8% | 49.5% |

**Observación importante:** Todos los matches dieron YELLOW con alta asimetría. Ningún match GREEN. Esto sugiere que los thresholds del semáforo o la fórmula de ganancia podrían necesitar calibración (ver sección 4).

**Flujo completo verificado:** registro → commit → evaluación → matching → solicitud → equipo → rating → reputación → detección de abuso. Todo funcional.

#### C. Servidor HTTP Levantado y Verificado
- El servidor arrancó correctamente en `localhost:8000`.
- Respondió con protocolo MCP (406 Not Acceptable para GET sin SSE headers = comportamiento correcto).
- Se verificó que el endpoint `/mcp` funciona.

#### D. Cold Search Ejecutada
Se probaron 10 queries diferentes contra la DB interna y GitHub.

**Resultados internos:** Funcionan correctamente para queries del dominio (protein folding, molecular biology). 4 de 4 investigadores encontrados.

**Resultados de GitHub — Repos seleccionados para análisis:**

| Repo | Tema | Tamaño | Archivos |
|---|---|---|---|
| `vjacynycz/MastersThesis` | Blockchain reputation for peer review | 47MB | 187 |
| `pixelsquirrel/fhe-ml` | Homomorphic encryption for ML | 1.5MB | 9 |
| `Vankill08/claude-skills-mcp` | MCP server reference implementation | 13MB | 56 |
| `Kishore7075/Researcher-Tool-AI` | AI plagiarism/originality detection | 124KB | 16 |

#### E. Análisis Profundo de los 4 Repos

Se clonaron en `/mnt/d/ResearchMatch_repo/research_refs/` y se analizaron en profundidad.

##### E.1 MastersThesis (Blockchain Reputation)
- Tesis UCM 2018, contratos Solidity (Ethereum) + IPFS
- **Reputación con exponential smoothing** (alpha=0.2): fórmula probada que previene cold-start
- **Ratings multi-stakeholder**: autores, editores, pares pueden calificar
- **Penalidades por deadline**: reputación baja si no cumplís plazos
- **Análisis de privacy tradeoffs**: blind vs open vs double-blind review
- **Limitaciones:** Solidity 0.4.x (viejo), no production-ready, sin frontend

##### E.2 fhe-ml (Homomorphic Encryption)
- Implementación completa con TenSEAL (CKKS scheme), 128-bit security
- **0% pérdida de accuracy** (86.13% plain = 86.13% encrypted)
- **200x slowdown** vs plaintext — prohibitivo para tiempo real
- Solo viable para modelos shallow (max ~6 multiplicaciones)
- Ciphertext expansion: 428KB por vector (de 38MB CSV a ~940MB encrypted)
- Sigmoid approximation con polinomio cúbico: `-0.004x³ + 0.197x + 0.5`
- **Conclusión:** FHE es viable para scoring pero necesita optimización seria

##### E.3 claude-skills-mcp (MCP Reference)
- Implementación de grado producción, la más madura
- **Two-package architecture:** frontend ligero (stdio, <5s startup) + backend pesado (HTTP)
- **Tool descriptions ultra-detalladas** con ejemplos y guías de uso para el LLM
- **Search semántico** con sentence-transformers (all-MiniLM-L6-v2, local, sin API keys)
- **Health endpoint** (`/health`) con status detallado
- **Background loading** con status messages al usuario
- **Auto-update** con rate limit awareness (GitHub API)
- **Thread-safe** state management con locks
- **15+ archivos de tests** con integration tests
- **Lazy document loading** y multi-level caching

##### E.4 Researcher-Tool-AI (AI Plagiarism)
- Frontend React/TypeScript que delega todo a Google Gemini API
- **NO tiene algoritmos propios** de originalidad/plagiarism
- Sin embeddings, sin similarity scoring, sin fingerprinting
- Útil solo por: visualización de scores (barras 0-100), parallel Promise.all, JSON schema enforcement
- **Conclusión:** No aporta al core de Research Match

---

## 2. Estado Actual del Proyecto

### 2.1 Lo que funciona (v2.1.0-mvp)
- ✅ 9 MCP tools implementadas y funcionales
- ✅ Registro pseudonímico con email hasheado (SHA-256)
- ✅ Research Commit con evaluación OT/OFC
- ✅ Niveles de solidez por componente con multiplicadores
- ✅ Matching por complementariedad con semáforo bilateral
- ✅ Sistema de rating anti-retaliación (anónimo hasta que ambos califican)
- ✅ Reputación ponderada temporalmente
- ✅ Detección de patrones de abuso en ratings
- ✅ Cold search (DB interna + GitHub)
- ✅ Transporte stdio y streamable-http
- ✅ Simulación de flujo completo (test_simulation.py)

### 2.2 Lo que necesita mejora
- ⚠️ `OriginalityEvaluator` usa heurísticas simples (word overlap / Jaccard)
- ⚠️ Tool descriptions genéricas — el LLM no sabe cuándo/cómo usarlas óptimamente
- ⚠️ Sin health endpoint para monitoreo
- ⚠️ Sin tests unitarios (solo simulación end-to-end)
- ⚠️ Sin logging estructurado
- ⚠️ Fórmula de ganancia puede necesitar calibración (todo sale YELLOW)
- ⚠️ Sin caching
- ⚠️ Sin manejo de errores robusto en tools

---

## 3. Plan de Acción Priorizado

### P0 — Implementar Ya (Esta Sesión)
**Fuente principal: claude-skills-mcp**

#### P0.1 — Mejorar Tool Descriptions
Reescribir las descriptions de las 9 tools con:
- Instrucciones explícitas de cuándo usar cada tool
- Ejemplos en las descriptions
- Guía de flujo (qué tool llamar primero, cuál después)
- Parameter descriptions con rango y defaults claros

#### P0.2 — Agregar Health Endpoint
Implementar endpoint `/health` que reporte:
- Versión del servidor
- Cantidad de usuarios registrados
- Cantidad de commits
- Cantidad de matches activos
- Estado de la DB
- Uptime

#### P0.3 — Integrar Sentence-Transformers para Similarity
Reemplazar el `_text_similarity()` basado en Jaccard por cosine similarity con embeddings:
- Usar `sentence-transformers` (all-MiniLM-L6-v2, 384 dims, ~90MB)
- Lazy-load del modelo (no bloquear startup)
- Aplicar en: `_text_similarity()`, `_commit_similarity()`, `_base_similarity()`
- Mantener Jaccard como fallback si el modelo no cargó

### P1 — Corto Plazo (Próximas sesiones)
**Fuente principal: MastersThesis**

#### P1.1 — Mejorar ReputationEngine
- Implementar exponential smoothing (alpha configurable)
- Agregar penalidades por inactividad/plazos
- Expandir quién puede calificar (no solo miembros del equipo)

#### P1.2 — Calibrar Semáforo y Fórmula de Ganancia
- Revisar thresholds: GREEN_THRESHOLD=30, YELLOW_ASYMMETRY=15, RED_THRESHOLD=15
- Ajustar `_calculate_gain()` para que no sea tan asimétrica
- Agregar tests con escenarios edge-case

#### P1.3 — Agregar Tests Unitarios
- Tests para OriginalityEvaluator
- Tests para MatchingEngine
- Tests para ReputationEngine
- Tests para cada MCP tool
- Usar pytest + fixtures

#### P1.4 — Logging Estructurado
- Configurar logging con niveles (DEBUG, INFO, WARNING, ERROR)
- Log de cada tool call con timing
- Log de evaluaciones y matches

### P2 — Medio Plazo
**Fuente principal: fhe-ml**

#### P2.1 — Evaluar Viabilidad de FHE para Scoring
- Benchmark del OriginalityEvaluator con TenSEAL
- Medir: tiempo de cifrado, tiempo de evaluación, accuracy loss
- Definir qué operaciones corren cifradas y cuáles no
- Documentar limitaciones (multiplicative depth budget)

#### P2.2 — Considerar Alternativas a FHE Puro
- Differential privacy (ruido calibrado, más rápido)
- TEE sin FHE (Intel SGX / ARM TrustZone, procesamiento en enclave)
- Hybrid: TEE para evaluación + FHE solo para almacenamiento

### P3 — Referencia Continua

#### P3.1 — Patrones de UI/UX (de Researcher-Tool-AI)
- Visualización de scores con barras y colores
- Parallel processing de análisis
- Progressive disclosure (tabs por tipo de análisis)

#### P3.2 — Blockchain Auditing (de MastersThesis)
- Solo si se decide implementar audit trail inmutable
- Contratos modulares como referencia arquitectónica
- IPFS para almacenamiento distribuido de commits cifrados

---

## 4. Observaciones Técnicas Pendientes

### 4.1 Calibración del Semáforo
En la simulación, todos los matches salieron YELLOW a pesar de tener complementariedad clara. Esto se debe a la fórmula de `_calculate_gain()` que penaliza fuerte cuando uno de los dos tiene scores más altos en ambos ejes. **Necesita revisión** — un teórico puro (OT alto, OFC bajo) debería dar GREEN con un computacional puro (OT bajo, OFC alto).

### 4.2 Reputación con 1 solo rating
El `MIN_RATINGS_FOR_REPUTATION = 2` hace que con 1 rating la reputación quede en default (100). La simulación mostró "New (no ratings yet)" incluso después de recibir ratings porque solo tenían 1 cada uno. **Funciona correctamente** — es un threshold de confianza.

### 4.3 Cold Search — Calidad de resultados
La búsqueda en GitHub devuelve repos por relevancia del query string, no por calidad. Queries como "research collaboration originality scoring" devolvieron 0 resultados. **La cold search es útil para exploración general pero no para descubrimiento preciso.** Considerar agregar más fuentes (arXiv, Semantic Scholar API).

---

## 5. Archivos Modificados en Esta Sesión

| Archivo | Cambio | Líneas |
|---|---|---|
| `src/research_match_server.py` | Fix entry point: transport string + port setting | 1870-1877 |

## 6. Archivos Nuevos Creados

| Archivo | Propósito |
|---|---|
| `research_refs/MastersThesis/` | Repo clonado — blockchain reputation |
| `research_refs/fhe-ml/` | Repo clonado — homomorphic encryption |
| `research_refs/claude-skills-mcp/` | Repo clonado — MCP reference |
| `research_refs/Researcher-Tool-AI/` | Repo clonado — AI plagiarism tool |
| `test_research_match.db` | DB de test generada por simulación |
| `PLAN_DE_ACCION.md` | Este documento |

---

*Próximo paso: Implementar P0 (tool descriptions, health endpoint, sentence-transformers)*
