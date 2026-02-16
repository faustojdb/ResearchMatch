# MANIFESTO: Capa de Colaboracion de Research Match

## Research Commit — El propio proyecto pide ayuda

**Dominio:** Software Engineering / Collaboration Platforms
**Subdominio:** Intellectual Property Protection in Decentralized Research Matching
**Problema:** Como permitir que dos investigadores que se descubren mutuamente puedan compartir trabajo de forma segura, con propiedad intelectual protegida, sin chat, y con licenciamiento automatico — sin depender de infraestructura centralizada costosa.

**Hipotesis:** Un sistema de tickets de necesidades (/needs/) + reveal progresivo de 4 niveles + licenciamiento joint-equal automatico + trail de auditoria inmutable resuelve el problema de colaboracion sin chat y sin riesgo de robo de IP.

---

## 1. El problema central

Research Match ya sabe ENCONTRAR personas trabajando en lo mismo. Ya sabe EVALUAR originalidad. Ya sabe CONECTAR con semaforo bilateral.

Pero despues del match, hay un vacio. Hoy el flujo es:

```
find_collaborators → send_request → respond_request(accept) → team creado → ???
```

El "???" es: como comparten trabajo sin exponerse, sin chat, sin intermediarios, y con garantias legales automaticas.

---

## 2. Necesidades concretas (lo que hay que construir)

### NEED-01: Sistema de Tickets / Necesidades (reemplaza al chat)

**Problema:** El chat genera ruido, sesgo grupal, y diluye la originalidad. Pero los colaboradores necesitan comunicarse ALGO.

**Solucion propuesta:** Un sistema de tickets estructurados donde cada usuario publica NECESIDADES especificas, no conversaciones.

```
Ticket {
    id, team_id, author_id
    type: "need_help" | "can_offer" | "warning" | "question"
    area: "theory" | "code" | "data" | "review" | "infrastructure"
    title: str (max 200 chars)
    description: str (max 2000 chars)
    priority: "critical" | "important" | "nice_to_have"
    status: "open" | "in_progress" | "resolved" | "wont_fix"
    attachments: List[str]  # referencias a archivos compartidos (nivel 4)
    resolved_by: Optional[user_id]
    created_at, updated_at
}
```

**Ejemplo real:**
- Ticket: "Necesito implementacion de exponential smoothing para sistema de reputacion"
- Tipo: need_help
- Area: code
- El otro usuario puede resolverlo y marcar como resuelto
- Esto se refleja en su rating y reputacion

**Reglas:**
- Sin conversacion libre — solo tickets estructurados
- Cada ticket es un "pull request intelectual"
- Los tickets resueltos alimentan el rating automaticamente
- Limite de tickets abiertos simultaneos (evita spam)

### NEED-02: Reveal Progresivo (4 niveles)

**Problema:** Compartir todo de golpe es peligroso. No compartir nada es inutil.

**Solucion:** 4 niveles de revelacion, cada uno requiere consentimiento explicito de AMBAS partes.

```
Nivel 1 — Indice (automatico al publicar)
    Visible: tags, dominio, subdominio, objetivo hasheado
    Quien ve: algoritmo de busqueda
    Consentimiento: automatico

Nivel 2 — Candidato (automatico en match)
    Visible: scores OT/OFC, semaforo, pseudonimo, solidez
    Quien ve: Claude local del otro usuario
    Consentimiento: automatico (datos anonimizados)

Nivel 3 — Detalle (requiere aprobacion mutua)
    Visible: Research Commit completo desencriptado
    Quien ve: Claude local + usuario
    Consentimiento: AMBOS deben aprobar
    Trigger: ticket "need_detail" o solicitud explicita

Nivel 4 — Codigo (seleccion manual)
    Visible: archivos seleccionados del repo
    Quien ve: ambos usuarios
    Consentimiento: seleccion manual archivo por archivo
    Trigger: ticket resuelto que requiere compartir codigo
```

**Tabla necesaria:**
```sql
CREATE TABLE IF NOT EXISTS reveal_consents (
    id TEXT PRIMARY KEY,
    team_id TEXT NOT NULL REFERENCES teams(id),
    level INTEGER NOT NULL CHECK(level BETWEEN 1 AND 4),
    requester_id TEXT NOT NULL REFERENCES users(id),
    approver_id TEXT NOT NULL REFERENCES users(id),
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK(status IN ('pending', 'approved', 'denied')),
    resource_type TEXT,  -- 'commit', 'file', 'dataset'
    resource_ref TEXT,   -- path o ID del recurso
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    resolved_at TEXT
);

CREATE TABLE IF NOT EXISTS shared_files (
    id TEXT PRIMARY KEY,
    team_id TEXT NOT NULL REFERENCES teams(id),
    consent_id TEXT NOT NULL REFERENCES reveal_consents(id),
    shared_by TEXT NOT NULL REFERENCES users(id),
    file_path TEXT NOT NULL,       -- path relativo en repo original
    file_hash TEXT NOT NULL,       -- SHA-256 del contenido
    shared_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

### NEED-03: Licenciamiento Automatico

**Problema:** Cuando dos personas comparten trabajo, quien es dueno de que?

**Solucion:** Licencia automatica generada al primer reveal nivel 3+.

**Tipos de licencia:**
```
joint-equal      — 50/50, ambos co-autores, ambos pueden publicar con credito
joint-weighted   — proporcional a contribucion (medida por tickets resueltos)
advisory-only    — uno solo consulta, no co-autor, credito en agradecimientos
time-limited     — acceso temporal para revision, expira automaticamente
```

**Regla clave:** La licencia se GENERA automaticamente basada en:
- Nivel de reveal alcanzado
- Tickets resueltos por cada parte
- Tipo de colaboracion (directo vs indirecto)

**El usuario NO negocia licencias manualmente.** El sistema las asigna y ambos pueden ver los terminos en cualquier momento.

### NEED-04: Control de Re-sharing (Propagacion)

**Problema:** Si A comparte con B, puede B compartir con C?

**Respuesta: NO.** Por diseno.

**Mecanismo:**
1. Todo contenido compartido tiene un `origin_user_id` inmutable
2. Solo el `origin_user_id` puede autorizar compartir con terceros
3. Si B intenta compartir trabajo de A con C:
   - El sistema lo detecta (file_hash tracking)
   - B viola la licencia joint-equal
   - B pierde TODOS los derechos sobre el trabajo compartido
   - B recibe rating automatico de honestidad=1
   - A es notificado

**Deterrent adicional:** B tambien perderia derechos sobre su PROPIO trabajo compartido con A. Es destruccion mutua asegurada (MAD) — no conviene traicionar porque perderia mas de lo que gana.

**Trail de auditoria:**
```sql
CREATE TABLE IF NOT EXISTS audit_log (
    id TEXT PRIMARY KEY,
    team_id TEXT NOT NULL,
    actor_id TEXT NOT NULL REFERENCES users(id),
    action TEXT NOT NULL,  -- 'reveal_requested', 'reveal_approved', 'file_shared',
                           -- 'file_accessed', 'license_generated', 'violation_detected'
    resource_ref TEXT,
    details TEXT,          -- JSON con metadata
    ip_hash TEXT,          -- hash del IP (no el IP real)
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

### NEED-05: Tools MCP necesarios

Nuevos tools para la capa de colaboracion:

```
research_match_needs_create    — Crear ticket de necesidad en un team
research_match_needs_list      — Listar tickets de un team (abiertos/resueltos)
research_match_needs_resolve   — Marcar ticket como resuelto
research_match_reveal_request  — Solicitar reveal de nivel 3 o 4
research_match_reveal_approve  — Aprobar/denegar solicitud de reveal
research_match_shared_files    — Listar archivos compartidos en un team
research_match_share_file      — Compartir un archivo especifico (nivel 4)
research_match_team_license    — Ver licencia actual del team
research_match_audit_log       — Ver trail de auditoria del team
```

---

## 3. Lo que NO hay que construir (todavia)

- Encriptacion E2E real (AES-256, TEE) — produccion, no MVP
- Cifrado homomorfico — fase 4
- Algolia/Meilisearch — el cold_search actual con SQLite alcanza para MVP
- UI web — todo opera via Claude/MCP

---

## 4. Solidez del planteo

| Componente | Nivel | Justificacion |
|-----------|-------|---------------|
| Tickets/needs | Especulativo | Definido conceptualmente, no implementado |
| Reveal progresivo | Especulativo | 4 niveles claros pero sin codigo |
| Licenciamiento auto | Especulativo | Tipos definidos, logica no escrita |
| Control re-sharing | Funcional (parcial) | La logica MAD es clara, el audit trail es disenable |
| Trail de auditoria | Especulativo | Schema definido, no implementado |
| Tools MCP | Especulativo | Nombres y funciones claras, implementacion pendiente |

**Overall solidity: speculative** — Tenemos la arquitectura clara pero cero lineas de codigo de la capa de colaboracion.

---

## 5. Conexiones interdisciplinarias

- **Game Theory (MAD):** El control de re-sharing usa destruccion mutua asegurada
- **Contract Law:** El licenciamiento automatico replica patrones de contratos marco
- **Version Control (Git):** El reveal progresivo es analogo a PRs con review obligatorio
- **Ticketing Systems (Jira/Linear):** El sistema de needs es un issue tracker minimalista
- **Blockchain Audit Trails:** El audit_log inmutable es conceptualmente similar a un ledger

---

## 6. Cherry-picking declarado

- El concepto de reveal progresivo viene de Signal Protocol (pero sin criptografia real en MVP)
- El sistema de tickets esta inspirado en GitHub Issues (pero sin conversacion libre)
- El MAD como deterrent viene de teoria de juegos clasica (Nash, 1950)
- El semaforo bilateral es original de Research Match

---

## 7. Pedido de ayuda (cold search)

**Busco:**
- Implementaciones de sistemas de licenciamiento automatico entre pares
- Patrones de reveal progresivo en plataformas de colaboracion
- Sistemas de tickets/needs sin chat libre
- Audit trails inmutables en SQLite
- Integraciones MCP que manejen compartir archivos entre usuarios

**Stack:** Python 3.12, FastMCP, SQLite, sentence-transformers
**Restriccion:** Debe funcionar 100% local, sin infra centralizada costosa

---

## 8. Resultados del cold search externo (GitHub, 2026-02-16)

Analisis automatizado con `analyze_repo.py` + busqueda GitHub sobre ~12 categorias.

### Repos directamente utiles

| Repo | Stars | Para que sirve | NEED |
|------|-------|---------------|------|
| **daffidwilde/matching** | ~100 | Algoritmos de stable matching (Gale-Shapley) en Python puro. BasePlayer/BaseGame/BaseMatching. Podemos adaptar para researcher pairing. | Matching |
| **Networks-Learning/human-AI-complementarity-matching** | -- | Paper ECMLPKDD2025: matching por COMPLEMENTARIEDAD, no similaridad. Maximum Weight Bipartite Capacity Matching con Gurobi. El concepto es exactamente lo que necesitamos. | Matching |
| **simon-weber/Instant-SQLite-Audit-Trail** | -- | Triggers SQLite que logean INSERT/UPDATE/DELETE a tabla de auditoria. Drop-in. | NEED-04 |
| **litements/litequeue** | ~300 | Cola persistente 100% SQLite, zero deps. Puede servir como base del sistema de tickets/needs. | NEED-01 |
| **harche/ProDisco** | -- | Progressive Disclosure MCP server para Kubernetes. Implementa el patron de reveal incremental a nivel de tools MCP. TypeScript, 34K LOC, bien testeado. | NEED-02 |
| **MarcusJellinghaus/mcp_server_filesystem** | ~38 | MCP filesystem Python con access control por directorio (strict/moderate/permissive). Patron de "reference projects" read-only vs "main project" read-write. | NEED-02, NEED-04 |
| **ragieai/dynamic-fastmcp** | -- | Tools MCP que adaptan su comportamiento per-user/tenant/request. DynamicToolManager extiende FastMCP ToolManager. 242 LOC core. | Arquitectura |

### Repos para analisis competitivo (WhatsApp)

| Repo | Stars | Diferencial |
|------|-------|------------|
| **lharries/whatsapp-mcp** | ~2K | Go bridge + Python FastMCP. Arquitectura similar pero sin Gmail, sin agente autonomo, sin transcripcion, sin image gen. Nuestro plugin lo supera en features. |
| **FelixIsaac/whatsapp-mcp-extended** | ~6 | Fork con 41 tools: reactions, polls, groups, newsletters. MUCHOS tools que nuestro plugin no tiene. Fuente de ideas. |
| **msaelices/whatsapp-mcp-server** | -- | Pure Python + FastMCP + GreenAPI. Stack identico al nuestro. |
| **eddmann/whatsapp-mcp** | -- | SQLite FTS5 full-text search. Tecnica adoptable para buscar en mensajes. |

### Hallazgo clave: espacio vacio

La categoria "Research Collaboration Matching" tuvo los MENOS resultados de todas. Solo `PaperMatch` (matching de papers con BERT) se acerca. Esto confirma que Research Match ocupa un gap genuino en el ecosistema open-source.

### NEED-06 (nuevo): cold_search siempre dual + deep_search futuro

**Problema detectado durante dogfooding:** El cold_search actual prioriza la DB interna y usa GitHub como fallback. Pero puede haber 1000 repos utiles afuera que nunca vemos si la DB interna tiene resultados.

**Solucion inmediata:** cold_search debe buscar SIEMPRE en ambas fuentes con peso igual, no priorizar una sobre otra.

**Solucion futura (deep_search):** Un tool que dado un repo de GitHub:
1. Lo clona shallow (`--depth 1`)
2. Corre `analyze_repo.py` sobre el
3. Si tiene MCP, extrae tools y compara contra nuestro proyecto
4. Devuelve analisis estructurado en vez de solo metadata

Esto convierte el cold_search de "busqueda superficial" a "analisis competitivo automatizado".
