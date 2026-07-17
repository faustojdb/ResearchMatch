# Plan de Publicacion — Claude Desktop Marketplace

## Estado actual
- **Research Match v3.1.0** desplegado en Cloud Run (26 tools, GitHub App)
- **MCPB v3.1.0 generado** (`research-match-3.1.0.mcpb` — 96KB, 13 archivos)
- DXT v3.1.0 generado (`research-match-3.1.0.dxt` — legacy)
- Release publicada en GitHub: https://github.com/faustojdb/ResearchMatch/releases/tag/v3.1.0
- GitHub App registrada: https://github.com/apps/research-match-collaborator
- `.mcpbignore` configurado para excluir archivos innecesarios del bundle

---

## IMPORTANTE: Rebranding DXT → MCPB

Anthropic renombro el formato de **DXT (Desktop Extensions)** a **MCPB (MCP Bundles)**:

| Antes | Ahora |
|-------|-------|
| `@anthropic-ai/dxt` | `@anthropic-ai/mcpb` |
| `dxt init` / `dxt pack` | `mcpb init` / `mcpb pack` |
| `.dxt` archivos | `.mcpb` archivos |

Los `.dxt` existentes siguen funcionando, pero nuevas submissions deben usar `.mcpb`.

---

## Paso 1: Instalar toolchain MCPB

```bash
npm install -g @anthropic-ai/mcpb
```

## Paso 2: Generar manifest.json con mcpb init

Ya tenemos `manifest.json` — verificar que cumple con la spec actual:

```bash
cd /mnt/d/ResearchMatch_repo
mcpb init  # Interactivo — comparar con nuestro manifest.json existente
```

**Campos requeridos del manifest.json:**
- `manifest_version`: actualmente `"0.4"` — verificar version actual de la spec
- `name`: `"research-match"`
- `version`: `"3.1.0"`
- `description`: corta (< 200 chars)
- `long_description`: detallada con features
- `author`: nombre + url
- `server.type`: `"uv"` (Python con UV)
- `server.entry_point`: `"src/research_match_server.py"`
- `tools[]`: array con los 26 tools
- `icon`: `"assets/icon.png"` (requerido para marketplace)

## Paso 3: Empaquetar con mcpb pack

```bash
mcpb pack
# Genera: research-match.mcpb (archivo ZIP renombrado)
```

**Verificar que incluye:**
- `manifest.json`
- `src/*.py` (todos los modulos)
- `pyproject.toml`
- `README.md`
- `LICENSE`
- `assets/icon.png`

**NO debe incluir:**
- `.env`, `*.pem`, `firebase-credentials.json` (secrets)
- `venv/`, `__pycache__/`, `*.db`
- `research_refs/`, `sessions/`

## Paso 4: Testing local del .mcpb

```bash
# Instalar localmente en Claude Desktop
# macOS: doble-click en el .mcpb
# Windows: abrir con Claude Desktop

# Verificar que los 26 tools aparecen
# Probar: "Register me on Research Match"
```

## Paso 5: Testing cross-platform

Antes de enviar al marketplace, verificar en:
- [ ] **Windows** — Claude Desktop con .mcpb
- [ ] **macOS** — Claude Desktop con .mcpb
- [ ] **Cloud Run** — Via Connectors (ya verificado)

**Nota sobre Python**: El .mcpb con `server.type: "uv"` requiere que el usuario tenga UV instalado. Esto es una friccion vs Node.js que viene pre-instalado con Claude Desktop. Documentar claramente en la descripcion.

## Paso 6: Enviar al Marketplace

### Formulario de submission
- **URL**: https://docs.google.com/forms/d/14_Dmcig4z8NeRMB_e7TOyrKzuZ88-BLYdLvS6LPhiZU/edit
- El equipo de Anthropic revisa calidad y seguridad
- No hay timeline publicado para la revision

### Informacion a preparar para el formulario:
1. **Nombre**: Research Match
2. **Descripcion corta**: MCP server that connects isolated researchers via literature-grounded originality scoring and bilateral matching
3. **Repositorio**: https://github.com/faustojdb/ResearchMatch
4. **Archivo .mcpb**: URL de la release o upload directo
5. **Icono**: `assets/icon.png` (ya existe)
6. **Categorias**: Research, Collaboration, AI, Academic
7. **Plataformas**: Windows, macOS, Linux
8. **Runtime**: Python 3.12+ (via UV)

### Tips para aprobacion:
- Asegurar que el README es claro y completo
- Tool descriptions deben ser descriptivas y seguir convenciones MCP
- No hardcodear secrets ni credenciales
- Manejar errores gracefully (ya lo hacemos)
- Licencia clara (BSL-1.1 — verificar si aceptan licencias no-OSI)

## Paso 7: Alternativas de distribucion

Si el marketplace tarda o rechaza, hay canales alternativos:

1. **GitHub Releases** (ya activo): https://github.com/faustojdb/ResearchMatch/releases
2. **mcp.so/dxt**: Directorio comunitario de DXT/MCPB
3. **awesome-claude-dxt**: https://github.com/milisp/awesome-claude-dxt (PR para inclusion)
4. **MCPStar/awesome-dxt-mcp**: https://github.com/MCPStar/awesome-dxt-mcp (PR)
5. **Cloud Run directo**: Siempre funciona via Connectors sin necesidad de .mcpb

---

## Checklist pre-submission

- [x] README.md actualizado (26 tools, GitHub App, install instructions)
- [x] manifest.json v3.1.0 con 26 tools
- [x] pyproject.toml con todas las dependencias (PyJWT, cryptography)
- [x] Icono en assets/icon.png
- [x] LICENSE (BSL-1.1)
- [x] Release v3.1.0 en GitHub con artifacts
- [x] Cloud Run desplegado y verificado
- [x] Health endpoint funcional
- [x] GitHub App registrada y testeada
- [x] Generar .mcpb con `mcpb pack` (96KB, 13 archivos, validado)
- [x] `.mcpbignore` configurado y commiteado
- [x] `.mcpb` subido a release v3.1.0 en GitHub
- [x] Test en Windows con Claude Desktop (instalado via doble-click)
- [ ] Test en macOS con Claude Desktop
- [ ] Enviar formulario de submission
- [ ] PR a awesome-claude-dxt y MCPStar/awesome-dxt-mcp

---

## Comandos rapidos (resumen)

```bash
# Instalar toolchain
npm install -g @anthropic-ai/mcpb

# Generar bundle
cd /mnt/d/ResearchMatch_repo
mcpb pack

# Testear localmente (Windows)
# Abrir research-match.mcpb con Claude Desktop

# Cloud Run (ya desplegado)
curl https://research-match-77626397872.us-central1.run.app/health
```

## Sources
- Anthropic DXT/MCPB repo: https://github.com/anthropics/dxt
- Blog post: https://www.anthropic.com/engineering/desktop-extensions
- Submission form: https://docs.google.com/forms/d/14_Dmcig4z8NeRMB_e7TOyrKzuZ88-BLYdLvS6LPhiZU/edit
- Directorio comunitario: https://mcp.so/dxt
- awesome-claude-dxt: https://github.com/milisp/awesome-claude-dxt
