# Plan: Publicar Research Match como Claude Desktop Extension

## Contexto
Claude Desktop (Windows Store v1.1.3189.0) NO soporta:
- `mcpServers` en claude_desktop_config.json (ignorado silenciosamente)
- `url` field (crashea la app)
- Extensions manuales inyectadas (requieren validación via API)
- "Agregar desde URL" (red bloqueada para localhost y dominios externos)

La ÚNICA via es publicar como **Desktop Extension (DXT)** en el marketplace.

## Pasos

### 1. Crear manifest.json (formato DXT v0.2)
Basado en el formato de Windows-MCP que ya funciona:
```json
{
  "manifest_version": "0.2",
  "name": "Research Match",
  "version": "2.3.0",
  "description": "...",
  "author": {"name": "faustojdb", "url": "https://github.com/faustojdb"},
  "repository": {"type": "git", "url": "https://github.com/faustojdb/ResearchMatch"},
  "server": {
    "type": "python",
    "entry_point": "./src/research_match_server.py",
    "mcp_config": {
      "command": "uv",
      "args": ["--directory", "${__dirname}", "run", "research-match"]
    }
  },
  "tools": [...las 10 tools...],
  "compatibility": {"platforms": ["win32", "linux", "darwin"]},
  "license": "MIT"
}
```

### 2. Configurar como paquete UV/pip
- Crear `pyproject.toml` con entry point `research-match`
- El server debe ser instalable via `uv run research-match`

### 3. Crear archivo .dxt
El formato DXT es un zip con:
- manifest.json
- src/research_match_server.py
- requirements o pyproject.toml
- README.md (opcional)
- assets/icon.png (opcional)

### 4. Publicar en GitHub
- Tag release v2.3.0
- Subir .dxt como release asset
- Claude Desktop puede instalar desde "agregar marketplace desde GitHub"

### 5. Testing
- Instalar desde GitHub URL en Claude Desktop
- Verificar que las 10 tools aparecen
- Probar flujo completo: register → submit → find → request

## Referencia
- Extension existente funcional: `ant.dir.cursortouch.windows-mcp`
- Manifest en: `/mnt/c/Users/faustojdb/AppData/Roaming/Claude/Claude Extensions/ant.dir.cursortouch.windows-mcp/manifest.json`
- Config key del server: usa `uv` como command, `${__dirname}` para path relativo

## Archivos Clave del Repo
- `src/research_match_server.py` — servidor principal (~2400 líneas)
- `requirements.txt` — dependencias
- `tests/` — 44 tests (conftest.py + 4 test files)
- `test_simulation.py` — simulación e2e

## Notas
- Necesitamos `pyproject.toml` para que `uv run` funcione
- El modelo sentence-transformers se descarga en primera ejecución (~90MB)
- DB se crea automáticamente al iniciar (fix en __main__)
