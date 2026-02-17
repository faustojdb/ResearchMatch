# Plan: Migrar Research Match de SQLite a Firebase Firestore + Algolia

## Contexto

Research Match es un servidor MCP con 24 herramientas que conecta investigadores aislados mediante scoring de originalidad AI y matching bilateral. Actualmente usa SQLite local, lo que impide que usuarios en diferentes maquinas se descubran entre si. La migracion a Firebase Firestore + Algolia habilita multi-usuario real, busqueda rapida, y escalabilidad.

**Decisiones clave ya tomadas:**
- GitHub API se mantiene para `cold_search` externo (NO se indexan repos en Algolia)
- Algolia solo indexa research commits internos (usuarios registrados)
- El repo sera privado (credenciales via env vars)
- Las 24 herramientas MCP mantienen la misma API

---

## Fase 0: Capa de Abstraccion DataStore (~3 dias)

### Archivos a crear:
- `src/datastore.py` — Protocolo abstracto con ~65 metodos semanticos
- `src/firestore_datastore.py` — Implementacion Firestore + Algolia

### Concepto:
Reemplazar todos los `db.execute()` (146 llamadas en 30+ funciones) con metodos semanticos. Ejemplo:

```python
# ANTES (SQLite)
db.execute("SELECT * FROM users WHERE email_hash = ?", (hash,)).fetchone()

# DESPUES (DataStore)
datastore.get_user_by_email_hash(hash)
```

### Colecciones Firestore:
```
users/{user_id}                              — Top-level (busqueda por email_hash)
research_commits/{commit_id}                 — Top-level (busqueda cross-user por dominio)
matches/{match_id}                           — Top-level (busqueda por user_a/user_b)
collaboration_requests/{request_id}          — Top-level (busqueda por requester/recipient)
teams/{team_id}                              — Top-level
  /members/{user_id}                         — Subcollection
  /ratings/{rating_id}                       — Subcollection
  /tickets/{ticket_id}                       — Subcollection
  /reveal_consents/{consent_id}              — Subcollection
  /shared_files/{file_id}                    — Subcollection
  /audit_log/{log_id}                        — Subcollection
  /contracts/{contract_id}                   — Subcollection
```

**Por que top-level vs subcollection:** `research_commits`, `matches` y `collaboration_requests` necesitan queries cross-user (no dentro de un team), asi que van top-level. Todo lo demas es team-scoped.

### Desnormalizacion (sin JOINs en Firestore):
Almacenar `pseudonym` directamente en: requests, tickets, matches, audit_log, consents, shared_files. Los pseudonimos son inmutables (se asignan una vez en registro).

---

## Fase 1: Identidad Multi-Usuario (~1.5 dias)

### Problema:
`_get_current_user(db)` actual retorna "el usuario mas reciente" — solo funciona single-user.

### Solucion:
Variable de entorno `RESEARCH_MATCH_USER_EMAIL` por instancia. El servidor hashea el email al iniciar y lo usa para identificar al usuario en cada request.

```python
# En lifespan
email_hash = hashlib.sha256(os.environ["RESEARCH_MATCH_USER_EMAIL"]...).hexdigest()

# En cada tool
user = datastore.get_user_by_email_hash(ctx...lifespan_context["user_email_hash"])
```

### Variables de entorno (set completo):
```
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
ALGOLIA_APP_ID=xxx
ALGOLIA_API_KEY=xxx (admin, write)
ALGOLIA_INDEX_NAME=research_commits
RESEARCH_MATCH_USER_EMAIL=user@example.com
```

---

## Fase 2: Firebase + Algolia Init (~0.5 dias)

### Archivos a crear:
- `src/firebase_init.py` — Firebase Admin SDK init
- `src/algolia_client.py` — Algolia client init + index config

### Algolia Index: `research_commits`
```
Searchable:  domain, subdomain, problem, hypothesis, pseudonym
Facets:      domain, overall_solidity
Numeric:     ot_score, ofc_score, created_at_timestamp
```

### Como funciona Algolia en cold_search:
1. Usuario llama `cold_search("machine learning privacy")`
2. Servidor busca en paralelo:
   - **Algolia** → busca en research commits de TODOS los usuarios registrados (instantaneo, full-text, ranking)
   - **GitHub API** → busca repos publicos (como ya funciona)
3. Combina resultados y retorna

```python
# Algolia search (reemplaza _cold_search_internal con SQL LIKE)
results = algolia_client.search(requests=[{
    "indexName": "research_commits",
    "query": "machine learning privacy",
    "hitsPerPage": 10,
}])
```

### Sync Algolia en submit_commit:
Cada vez que un usuario envia un commit, se indexa automaticamente:
```python
algolia_client.save_object("research_commits", {
    "objectID": commit_id,
    "pseudonym": "faustojdb",
    "domain": "software engineering",
    "problem": "Privacy-disclosure paradox...",
    "ot_score": 63.3,
    ...
})
```

---

## Fase 3: Migrar Engine Classes (~1.5 dias)

### Archivos a modificar:
- `src/research_match_server.py` — OriginalityEvaluator, MatchingEngine, ReputationEngine

### Cambios por clase:

| Clase | db.execute calls | Cambio principal |
|-------|-----------------|------------------|
| OriginalityEvaluator | 3 | `self.db` -> `self.datastore`, `_get_corpus()` usa Firestore query por dominio |
| MatchingEngine | 3 | `get_candidates()` query Firestore + flag `is_latest: true` en commits |
| ReputationEngine | 14 | Mayor refactor: running averages, rating checks, abuse detection |

### Nota: `is_latest` flag
Para reemplazar el subquery SQL `GROUP BY user_id HAVING version = MAX(version)`, cada commit tendra un campo `is_latest: bool`. Al crear un nuevo commit, el anterior se marca `is_latest: false` atomicamente (batch write).

---

## Fase 4: Migrar Funciones Helper (~2 dias)

### Funciones a migrar:

| Funcion | db calls | Nota |
|---------|----------|------|
| `_get_or_create_user` | 3 | -> `datastore.get_user_by_email_hash()` + `create_user()` |
| `_get_current_user` | 1 | Rediseniada (Fase 1) |
| `_write_audit_log` | 1 | -> `datastore.write_audit_log()` |
| `_check_resharing_violation` | 1 | -> `datastore.get_shared_file_by_hash()` |
| `_generate_contract_content` | 4 | Multiples datastore calls |
| `_compute_license` | 8 | Compleja: members, reveals, tickets, team age |
| `_cold_search_internal` | 1 | **Reemplazada por Algolia** |

---

## Fase 5: Migrar 24 Herramientas MCP (~5 dias)

### Patron de migracion por tool:
```python
# ANTES
db = _get_db(ctx)
user = _get_current_user(db)

# DESPUES
datastore = _get_datastore(ctx)
user = _get_current_user(ctx)  # usa email_hash del lifespan
```

### Tools por complejidad:

**Simples (1-3 calls):** register, my_profile, analyze_work, cold_search, deep_search

**Medias (4-8 calls):** submit_commit (+Algolia sync), find_collaborators, send_request, inbox, respond_request, rate_user, needs_create, needs_list, needs_resolve

**Complejas (8+ calls):** reveal_request, reveal_respond, reveal_status, team_license, share_file, shared_files, audit_log, export_contract, confirm_contract, prepare_commit

### Batch writes para atomicidad:
- `respond_request`: crear team + 2 members + update request + audit -> 1 batch write
- `submit_commit`: crear commit + mark previous `is_latest=false` + Algolia sync

---

## Fase 6: Indexes y Security Rules (~0.5 dias)

### Firestore composite indexes (firestore.indexes.json):
- `research_commits`: (domain, user_id, version DESC)
- `research_commits`: (user_id, version DESC)
- `research_commits`: (is_latest, domain)
- `collaboration_requests`: (recipient_id, created_at DESC)
- `collaboration_requests`: (requester_id, created_at DESC)

### Security Rules:
```
allow read, write: if false;  // Solo Admin SDK, sin acceso cliente
```

---

## Fase 7: Testing (~3 dias)

### Estrategia:
1. **Firestore Emulator** para tests locales: `firebase emulators:start --only firestore`
2. **Unit tests** por cada metodo de DataStore (~65 tests)
3. **Integration tests** de flujos completos:
   - Register -> Submit -> Find Collaborators -> Send Request -> Respond -> Rate
   - Reveal flow completo
   - Ticket lifecycle
   - Contract bilateral
4. **Algolia tests** con indice de test separado
5. **Regression**: comparar output JSON de cada tool vs. version SQLite

---

## Fase 8: Dependencies y Build (~0.5 dias)

### pyproject.toml — nuevas dependencias:
```toml
dependencies = [
    # existentes...
    "firebase-admin>=6.0.0",
    "algoliasearch>=4.0.0",
]
```

### Estructura final:
```
src/
  research_match_server.py    # Modificado: 146 db.execute -> datastore calls
  datastore.py                # Protocolo abstracto (~65 metodos)
  firestore_datastore.py      # Implementacion Firestore + Algolia
  firebase_init.py            # Firebase Admin SDK init
  algolia_client.py           # Algolia client init
analyze_repo.py               # Sin cambios
tests/
  test_firestore_datastore.py
  test_tools_integration.py
firestore.indexes.json
```

---

## Estimacion Total

| Fase | Dias |
|------|------|
| 0: DataStore abstraction | 3 |
| 1: Multi-user identity | 1.5 |
| 2: Firebase + Algolia init | 0.5 |
| 3: Engine classes | 1.5 |
| 4: Helper functions | 2 |
| 5: 24 MCP tools | 5 |
| 6: Indexes + rules | 0.5 |
| 7: Testing | 3 |
| 8: Build | 0.5 |
| **Total** | **~18 dias** |

---

## Riesgos y Mitigaciones

| Riesgo | Mitigacion |
|--------|-----------|
| Firestore no tiene LIKE/full-text | Algolia para cold_search |
| Firestore no tiene JOINs | Desnormalizacion de pseudonimos |
| N+1 queries | Batch reads con `get_all()` |
| Algolia sync falla despues de Firestore write | Log + herramienta manual de re-index |
| Latencia de red vs SQLite local | Firestore tiene cache local; Algolia <50ms |
| Costo | Free tiers: Firestore (1GB), Algolia (10K records) |

---

## Verificacion

Para confirmar que la migracion funciona end-to-end:

1. `firebase emulators:start --only firestore`
2. Configurar env vars (Firebase + Algolia + email)
3. `uv run research-match` — servidor arranca sin errores
4. Probar: `cold_search("machine learning")` — retorna resultados de Algolia + GitHub
5. Probar: `register` + `submit_commit` — commit aparece en Firestore Y Algolia
6. Probar desde DOS instancias con diferentes emails: `find_collaborators` encuentra al otro usuario
7. Flujo completo: register -> submit -> find -> request -> respond -> rate -> reveal -> contract
