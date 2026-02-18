# Plan de Trabajo para Manana - Research Match Firebase Migration

## Estado Actual (Punto de Partida)

### Lo que YA esta hecho (Fases 0-5):

| Fase | Estado | Commit |
|------|--------|--------|
| 0: DataStore abstraction | COMPLETA | `83a5d04` |
| 1: Multi-user identity | COMPLETA | `70cbabe` |
| 2: Firebase + Algolia init | COMPLETA | `83a5d04` |
| 3: Engine classes (async) | COMPLETA | `70cbabe` |
| 4: Helper functions | COMPLETA | `70cbabe` |
| 5: 24 MCP tools (dual-backend) | COMPLETA | `70cbabe` |

### Archivos actuales:

```
src/
  __init__.py                    (0 lineas)
  algolia_client.py              (75 lineas)   -- Algolia init + index config
  datastore.py                   (932 lineas)  -- Protocolo abstracto + 25 aliases
  firebase_init.py               (37 lineas)   -- Firebase Admin SDK init
  firestore_datastore.py         (1420 lineas) -- Implementacion Firestore + Algolia
  research_match_server.py       (6246 lineas) -- 24 tools migradas, dual-backend
firestore.indexes.json           (117 lineas)  -- 14 composite indexes
pyproject.toml                                 -- v3.0.0-alpha.1 con deps Firebase
```

### Lo que FALTA (Fases 6-8):

| Fase | Trabajo restante |
|------|-----------------|
| 6: Indexes + Security Rules | `firestore.indexes.json` YA existe. Falta: `firestore.rules`, `firebase.json`, deploy config |
| 7: Testing | TODO: tests unitarios + integracion con Firestore Emulator |
| 8: Build + Deploy | Falta: reinstalar deps, verificar server arranca, test end-to-end manual |

---

## Plan Detallado para Manana

### BLOQUE 1: Infraestructura Firebase (~30 min)

**Objetivo:** Poder correr el Firestore Emulator localmente para testing.

**1.1 Instalar Firebase CLI**
```bash
npm install -g firebase-tools
firebase --version
```

**1.2 Inicializar proyecto Firebase**
```bash
cd research-match
firebase init
# Seleccionar: Firestore (emulator), Firestore Indexes, Firestore Rules
# Proyecto: crear uno nuevo o usar existente
```

Esto genera:
- `firebase.json` — config del proyecto (emulators port, etc.)
- `firestore.rules` — reglas de seguridad

**1.3 Crear `firestore.rules`**
```
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    // Solo Admin SDK — sin acceso cliente directo
    match /{document=**} {
      allow read, write: if false;
    }
  }
}
```

**1.4 Verificar emulator arranca**
```bash
firebase emulators:start --only firestore
# Debe arrancar en localhost:8080
```

**Punto de control:** Emulator corriendo, UI en http://localhost:4000

---

### BLOQUE 2: Configurar entorno de testing (~30 min)

**Objetivo:** Tener un entorno donde los tests se conecten al emulator.

**2.1 Instalar dependencias de test**
```bash
cd research-match
uv pip install pytest pytest-asyncio
```

**2.2 Crear `conftest.py` raiz**
```python
# conftest.py
import os
os.environ["FIRESTORE_EMULATOR_HOST"] = "localhost:8080"
os.environ["RESEARCH_MATCH_USER_EMAIL"] = "test@example.com"
```

**2.3 Crear estructura de tests**
```
tests/
  __init__.py
  conftest.py                    -- fixtures compartidos
  test_firestore_datastore.py    -- unit tests para DataStore
  test_tools_integration.py      -- integration tests de flujos completos
```

**2.4 Crear fixture para DataStore limpio**
```python
# tests/conftest.py
@pytest.fixture
async def datastore():
    """Fresh FirestoreDataStore connected to emulator."""
    os.environ["FIRESTORE_EMULATOR_HOST"] = "localhost:8080"
    ds = FirestoreDataStore()
    await ds.initialize()
    yield ds
    # Cleanup: delete all collections
    await ds.close()
```

**Punto de control:** `pytest --co tests/` muestra tests descubiertos sin errores.

---

### BLOQUE 3: Tests unitarios del DataStore (~2 horas)

**Objetivo:** Verificar que cada metodo del FirestoreDataStore funciona contra el emulator.

Organizar tests por dominio, en orden de dependencia:

**3.1 Users (13 metodos)**
```python
class TestUsers:
    async def test_insert_and_find_by_email_hash()
    async def test_get_user_by_id()
    async def test_get_user_pseudonym()
    async def test_get_most_recent_user()
    async def test_update_running_averages()
    async def test_update_running_effort()
    async def test_update_reputation_stats()
    async def test_penalize_honesty()
    async def test_count_users()
```

**3.2 Research Commits (11 metodos)**
```python
class TestCommits:
    async def test_insert_and_get_by_id()
    async def test_get_latest_commit_by_user()
    async def test_get_max_commit_version()
    async def test_get_next_commit_version()        # alias
    async def test_get_all_commits_by_user()
    async def test_get_corpus_commits_excludes_user()
    async def test_find_candidate_commits_in_domain()
    async def test_search_commits_by_keywords()      # Firestore fallback (no Algolia en emulator)
    async def test_submit_commit_and_mark_latest()   # batch op
    async def test_count_commits()
```

**3.3 Matches (3 metodos)**
```python
class TestMatches:
    async def test_upsert_and_find()
    async def test_find_match_bidirectional()
    async def test_count_matches()
```

**3.4 Collaboration Requests (7 metodos + aliases)**
```python
class TestRequests:
    async def test_insert_and_find_pending()
    async def test_create_collaboration_request_dict()   # alias
    async def test_get_incoming_requests_with_details()   # alias
    async def test_get_outgoing_requests_with_details()   # alias
    async def test_update_request_status_with_timestamp()
    async def test_get_request_for_recipient()
    async def test_count_pending_requests()
```

**3.5 Teams + Members (16 metodos)**
```python
class TestTeams:
    async def test_create_team_with_members_positional()
    async def test_create_team_with_members_dict()       # dict kwargs
    async def test_get_team_by_id()
    async def test_get_team_member()                     # alias
    async def test_get_team_member_ids()
    async def test_get_team_member_pseudonyms()
    async def test_get_team_members_with_profiles()
    async def test_get_teams_for_user()                  # alias
    async def test_update_team_license_with_timestamp()
    async def test_update_member_contribution()
    async def test_count_teams_and_members()
```

**3.6 Ratings (8 metodos)**
```python
class TestRatings:
    async def test_insert_and_find_rating()
    async def test_get_rating()
    async def test_get_ratings_received_desc()
    async def test_get_ratings_given_desc()
    async def test_count_ratings_received()
    async def test_reveal_team_ratings()
    async def test_count_ratings()
```

**3.7 Tickets (7 metodos + aliases)**
```python
class TestTickets:
    async def test_insert_and_get_by_id()
    async def test_count_open_tickets_by_user()         # alias
    async def test_list_tickets_with_filters()
    async def test_list_tickets_alias()                  # alias
    async def test_count_tickets_by_status()             # alias
    async def test_update_ticket_status()                # alias → resolve_ticket
    async def test_count_resolved_tickets_by_member()
```

**3.8 Reveal Consents (11 metodos + aliases)**
```python
class TestReveals:
    async def test_insert_and_find_pending()
    async def test_find_reveal_consent_unified()         # alias
    async def test_find_approved_reveal()
    async def test_find_approved_reveal_for_pair()
    async def test_update_reveal_consent_status_with_team_id()
    async def test_get_reveal_consents_with_pseudonyms() # alias
    async def test_get_approved_reveal_targets()         # alias
    async def test_count_pending_reveals()
    async def test_count_approved_reveals_direction()
```

**3.9 Shared Files (6 metodos + aliases)**
```python
class TestSharedFiles:
    async def test_insert_and_find_by_path()
    async def test_find_shared_file_alias()              # alias
    async def test_find_file_by_hash_other_user()
    async def test_count_shared_files_global_and_team()
    async def test_get_shared_files_with_pseudonyms()    # alias
```

**3.10 Audit Log (4 metodos + alias)**
```python
class TestAudit:
    async def test_insert_and_list()
    async def test_list_filtered()
    async def test_get_audit_entries_unified()            # alias
    async def test_get_license_change_history()
    async def test_count_audit_entries()
```

**3.11 Contracts (9 metodos + aliases)**
```python
class TestContracts:
    async def test_insert_and_get_by_id()
    async def test_get_contract_alias()                  # alias
    async def test_get_next_contract_version()           # alias
    async def test_supersede_pending()
    async def test_update_contract_confirmation_slot_a()  # alias
    async def test_update_contract_confirmation_slot_b()  # alias
    async def test_update_contract_status()
    async def test_count_confirmed_contracts_for_team()
```

**3.12 Utility + Health**
```python
class TestUtility:
    async def test_compute_age_in_days()
    async def test_health_stats()
```

**Total: ~65 tests unitarios**

**Punto de control:** `pytest tests/test_firestore_datastore.py -v` — todos pasan en verde.

---

### BLOQUE 4: Tests de integracion de flujos completos (~1.5 horas)

**Objetivo:** Verificar los flujos end-to-end que tocan multiples herramientas MCP.

**4.1 Flujo de registro y submit**
```python
async def test_flow_register_submit():
    """register → submit_commit → my_profile"""
    # 1. Register user A
    # 2. Submit commit for user A
    # 3. Verify my_profile shows commit + scores
    # 4. Submit v2 → verify is_latest flag updates
```

**4.2 Flujo de matching y colaboracion**
```python
async def test_flow_matching():
    """register x2 → submit x2 → find_collaborators → send_request → inbox → respond_request"""
    # 1. Register user A, submit commit (domain: "machine learning")
    # 2. Register user B, submit commit (same domain)
    # 3. User A: find_collaborators → should find user B
    # 4. User A: send_request to user B
    # 5. User B: inbox → should see request
    # 6. User B: respond_request(accept)
    # 7. Verify team created with both members
```

**4.3 Flujo de ratings**
```python
async def test_flow_ratings():
    """rate_user bilateral → reputation update"""
    # 1. Setup: team with A and B
    # 2. User A rates user B
    # 3. User B rates user A
    # 4. Verify ratings revealed
    # 5. Verify reputation scores updated
```

**4.4 Flujo de reveals**
```python
async def test_flow_reveals():
    """reveal_request → reveal_respond → reveal_status"""
    # 1. Setup: team with A and B, both have commits
    # 2. User A: reveal_request(target: B)
    # 3. User B: reveal_respond(approve)
    # 4. User A: reveal_status → should see B's commit content
    # 5. Bilateral: B requests A, A approves
    # 6. Verify bilateral reveals complete
```

**4.5 Flujo de tickets**
```python
async def test_flow_tickets():
    """needs_create → needs_list → needs_resolve"""
    # 1. Setup: team with A and B
    # 2. User A: create ticket (need_help, code, critical)
    # 3. Both: list tickets → should see it
    # 4. User B: resolve ticket
    # 5. Verify effort boost for resolver
```

**4.6 Flujo de contratos**
```python
async def test_flow_contracts():
    """export_contract → confirm_contract bilateral"""
    # 1. Setup: team with bilateral reveals
    # 2. User A: export_contract
    # 3. User A: confirm_contract(git_hash)
    # 4. User B: confirm_contract(git_hash)
    # 5. Verify contract status = "confirmed"
```

**4.7 Flujo de shared files**
```python
async def test_flow_shared_files():
    """share_file → shared_files → resharing detection"""
    # 1. Setup: team with bilateral reveals
    # 2. User A: share_file
    # 3. User A: shared_files → should see file
    # 4. Test resharing violation detection
```

**Punto de control:** `pytest tests/test_tools_integration.py -v` — todos pasan.

---

### BLOQUE 5: Smoke test con servidor real (~30 min)

**Objetivo:** Verificar que el servidor MCP arranca y responde en modo Firestore.

**5.1 Configurar env vars**
```bash
# Terminal 1: Emulator
firebase emulators:start --only firestore

# Terminal 2: Servidor
export FIRESTORE_EMULATOR_HOST=localhost:8080
export GOOGLE_APPLICATION_CREDENTIALS=dummy  # trigger Firestore mode
export RESEARCH_MATCH_USER_EMAIL=test@example.com
uv run research-match
```

**5.2 Test manual via Claude Desktop**
(Si el server arranca, usar las tools directamente)
1. `register` → debe crear usuario
2. `submit_commit` → debe crear commit
3. `my_profile` → debe mostrar datos
4. `cold_search("test")` → debe retornar resultados (Firestore fallback)

**5.3 Verificar modo SQLite sigue funcionando**
```bash
# Sin GOOGLE_APPLICATION_CREDENTIALS
unset GOOGLE_APPLICATION_CREDENTIALS
uv run research-match
# Debe caer en SQLite como antes
```

**Punto de control:** Servidor arranca en ambos modos sin errores.

---

### BLOQUE 6: Limpieza y commit final (~30 min)

**Objetivo:** Dejar todo limpio y commiteado.

**6.1 Crear/actualizar archivos**
- `firestore.rules` — security rules
- `firebase.json` — project config
- `tests/` — todos los test files
- Actualizar `.gitignore` si hace falta

**6.2 Reinstalar dependencias**
```bash
uv pip install -e ".[dev]"  # o uv sync
```

**6.3 Commit final**
```bash
git add firestore.rules firebase.json tests/ ...
git commit -m "feat: add Firestore emulator tests + Firebase config (Fases 6-8)"
git push
```

**6.4 Actualizar version**
- `pyproject.toml`: `3.0.0-alpha.2` (con tests)

---

## Resumen de Entregables para Manana

| # | Entregable | Archivos |
|---|-----------|----------|
| 1 | Firebase project config | `firebase.json`, `firestore.rules` |
| 2 | Test infrastructure | `tests/conftest.py`, `tests/__init__.py` |
| 3 | Unit tests DataStore | `tests/test_firestore_datastore.py` (~65 tests) |
| 4 | Integration tests | `tests/test_tools_integration.py` (~7 flujos) |
| 5 | Smoke test verificado | Servidor arranca en Firestore + SQLite modes |
| 6 | Commit final | v3.0.0-alpha.2 |

## Riesgos para Manana

| Riesgo | Mitigacion |
|--------|-----------|
| Firebase CLI no instala en Windows | Usar `npx firebase-tools` como alternativa |
| Emulator no arranca | Verificar Java instalado (`java --version`), requerido por emulator |
| Algolia no disponible en emulator | Tests de search usan Firestore fallback; Algolia se testea por separado |
| pytest-asyncio config | Usar `asyncio_mode = "auto"` en `pyproject.toml` |
| Collection group queries fallan en emulator | Pueden necesitar crear indexes primero: `firebase deploy --only firestore:indexes` |

## Prerequisitos (verificar ANTES de empezar)

```bash
# 1. Java (requerido por Firestore Emulator)
java --version

# 2. Node.js (requerido por Firebase CLI)
node --version

# 3. Si no hay Java:
winget install Microsoft.OpenJDK.21

# 4. Si no hay Node:
winget install OpenJS.NodeJS.LTS
```
