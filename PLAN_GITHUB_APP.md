# Plan: GitHub App para Intercambio Automático de Repositorios

## Problema
Cuando dos investigadores firman un contrato de colaboración, el intercambio de código es manual (email, zip, etc.). Esto crea un riesgo de estafa: uno puede no compartir después de ver el trabajo del otro. Research Match necesita un mecanismo automático de acceso bilateral a repositorios que se active al confirmar el contrato.

## Solución: GitHub App como Intermediario

Una GitHub App instalada por cada investigador en su(s) repo(s). Al confirmar el contrato bilateral (`confirm_contract`), la App automáticamente otorga acceso read-only al otro investigador. Si el contrato se rompe o expira, la App revoca el acceso.

---

## Fase 1: Registrar la GitHub App

### 1.1 Crear GitHub App en GitHub Settings
- Nombre: `Research Match Collaborator` (o similar)
- Homepage URL: `https://github.com/faustojdb/ResearchMatch`
- Callback URL: `https://research-match-77626397872.us-central1.run.app/github/callback`
- Webhook URL: `https://research-match-77626397872.us-central1.run.app/github/webhook` (opcional, fase 2+)
- Permisos requeridos:
  - **Repository permissions:**
    - `Administration`: Read & Write (para agregar collaborators)
    - `Contents`: Read-only (para verificar que el repo existe)
    - `Metadata`: Read-only (siempre requerido)
  - **Account permissions:**
    - `Email addresses`: Read-only (para vincular con el perfil de RM)

### 1.2 Almacenar credenciales
- `GITHUB_APP_ID` → Secret Manager
- `GITHUB_APP_PRIVATE_KEY` → Secret Manager (PEM)
- `GITHUB_APP_CLIENT_ID` → Secret Manager
- `GITHUB_APP_CLIENT_SECRET` → Secret Manager

---

## Fase 2: Flujo de Instalación del Usuario

### 2.1 Nuevo tool: `research_match_connect_github`
- El usuario llama este tool para vincular su cuenta de GitHub
- El tool retorna una URL de instalación de la GitHub App
- El usuario instala la App en su repo(s) desde el browser
- La App envía un webhook `installation.created` con los repos autorizados
- Alternativa sin webhook: el tool verifica la instalación via API

### 2.2 Almacenamiento (Firestore)
```
users/{user_id}/github_connections/{connection_id}:
  github_username: str
  installation_id: int          # GitHub App installation ID
  authorized_repos: [str]       # ["owner/repo1", "owner/repo2"]
  connected_at: timestamp
  access_token_encrypted: str   # Installation access token (rotable)
```

### 2.3 Vincular repo al Research Commit
- `submit_commit` ya tiene campos `git_repo_url` y `git_commit_hash`
- Validar que el `git_repo_url` esté en `authorized_repos`
- Si no, sugerir al usuario que instale la App en ese repo

---

## Fase 3: Acceso Automático al Confirmar Contrato

### 3.1 Hook en `confirm_contract`
Cuando el contrato alcanza status `confirmed` (ambas partes confirmaron):

```python
async def _grant_bilateral_repo_access(datastore, team_id, contract):
    """Grant read-only access to each other's repos via GitHub App."""
    members = await datastore.get_team_members_with_profiles(team_id)

    for member in members:
        # Get their GitHub connection
        gh_conn = await datastore.get_github_connection(member["user_id"])
        if not gh_conn:
            continue

        # Get the other member's GitHub username
        other = [m for m in members if m["user_id"] != member["user_id"]][0]
        other_gh = await datastore.get_github_connection(other["user_id"])
        if not other_gh:
            continue

        # Add other user as read-only collaborator to member's repos
        for repo in gh_conn["authorized_repos"]:
            await github_api.add_collaborator(
                installation_id=gh_conn["installation_id"],
                repo=repo,
                username=other_gh["github_username"],
                permission="pull"  # read-only
            )

    # Log in audit trail
    await datastore.write_audit_log(team_id, "repo_access_granted", ...)
```

### 3.2 Notificación
- El tool retorna info sobre los repos compartidos
- Cada usuario recibe un invite de GitHub (standard flow)
- El audit_log registra `repo_access_granted`

---

## Fase 4: Revocación de Acceso

### 4.1 Nuevo tool: `research_match_disconnect_github`
- Revoca acceso del collaborator en todos los repos vinculados al equipo
- Desinstala la App si el usuario lo desea
- Registra `repo_access_revoked` en audit_log

### 4.2 Revocación automática
- Si un miembro recibe una violación MAD (re-sharing detectado) → revocar acceso automáticamente
- Si el team_license expira (time-limited rule, 30 días) → revocar
- Si un miembro reporta abuso → revocar y notificar

### 4.3 Hook en rating negativo
- Si `rate_user` con honesty=1 → flag para revisión
- Si ambos dan ratings <2 → revocación automática

---

## Fase 5: Seguridad y Edge Cases

### 5.1 Permisos mínimos
- Solo `pull` (read-only) — nunca `push`
- Solo repos explícitamente autorizados por el usuario
- Token de instalación rotado automáticamente por GitHub (1 hora)

### 5.2 Repo privados
- La App necesita estar instalada en el repo privado para funcionar
- El usuario elige qué repos autorizar durante la instalación

### 5.3 Protección contra abuso
- Rate limiting: máximo 5 repos por equipo
- Verificación de ownership: solo puedes autorizar repos donde eres owner/admin
- Audit trail completo de cada grant/revoke

### 5.4 Sin GitHub
- Usuarios sin GitHub siguen usando el flujo manual (share_file metadata)
- `connect_github` es opcional, no bloqueante

---

## Nuevos Tools (resumen)

| # | Tool | Descripción |
|---|------|-------------|
| 25 | `connect_github` | Vincular cuenta de GitHub e instalar la App |
| 26 | `disconnect_github` | Revocar acceso y desvincular |

## Nuevos Secrets

| Secret | Uso |
|--------|-----|
| `GITHUB_APP_ID` | App ID |
| `GITHUB_APP_PRIVATE_KEY` | PEM key para generar JWT |
| `GITHUB_APP_CLIENT_ID` | OAuth client ID |
| `GITHUB_APP_CLIENT_SECRET` | OAuth client secret |

## Schema Changes (Firestore)

```
users/{user_id}/github_connections/{connection_id}:
  github_username: str
  installation_id: int
  authorized_repos: [str]
  connected_at: str (ISO)

audit_log entries:
  action: "repo_access_granted" | "repo_access_revoked"
```

## Dependencias

- `PyGithub>=2.0` o `githubkit>=0.11` (async GitHub API client)
- `PyJWT>=2.0` (para generar JWT de la GitHub App)

## Estimación de complejidad

- Fase 1 (App registration): config manual en GitHub + secrets
- Fase 2 (connect_github): 1 tool + Firestore schema + GitHub API integration
- Fase 3 (auto-grant): hook en confirm_contract + GitHub collaborator API
- Fase 4 (revocation): 1 tool + hooks en rate_user/MAD
- Fase 5 (security): validations + tests

## Prioridades

1. **Fase 1+2+3** son el MVP — sin esto no hay intercambio automático
2. **Fase 4** es crítica para seguridad — sin revocación no se puede confiar en el sistema
3. **Fase 5** es hardening — importante pero puede iterarse

---

*Creado: 2026-02-19 | Versión: draft*
