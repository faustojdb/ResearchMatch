# Research Match MCP Server — Guía de Instalación

## Requisitos

- Python 3.10+
- pip

## Instalación

```bash
pip install -r requirements.txt
```

## Uso

### Modo local (stdio) — para Claude Desktop

```bash
python src/research_match_server.py
```

### Modo HTTP — para Claude.ai o múltiples clientes

```bash
python src/research_match_server.py --http 8000
```

## Configuración en Claude Desktop

Agregá esto a tu archivo de configuración de Claude Desktop (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "research_match": {
      "command": "python",
      "args": ["<RUTA_COMPLETA>/src/research_match_server.py"],
      "env": {
        "RESEARCH_MATCH_DB": "<RUTA_COMPLETA>/data/research_match.db"
      }
    }
  }
}
```

## Tools Disponibles

| Tool | Descripción |
|------|------------|
| `research_match_register` | Registrar usuario con identidad pseudonímica |
| `research_match_submit_commit` | Enviar Research Commit para evaluación por IA |
| `research_match_my_profile` | Ver perfil de originalidad y scores |
| `research_match_find_collaborators` | Buscar investigadores complementarios |
| `research_match_send_request` | Enviar solicitud de colaboración |
| `research_match_inbox` | Ver solicitudes entrantes y salientes |
| `research_match_respond_request` | Aceptar o rechazar solicitudes |
| `research_match_analyze_work` | Plantilla para crear un commit desde el contexto actual |

## Flujo Típico

1. **Registrarse**: `research_match_register` con email
2. **Trabajar normalmente** en Claude
3. **Cuando quieras buscar colaboradores**: decí "analizá mi trabajo" → Claude usa `research_match_analyze_work` para estructurar tu Research Commit
4. **Submitear**: `research_match_submit_commit` → recibís scores OT y OFC
5. **Buscar matches**: `research_match_find_collaborators` → candidatos con semáforo
6. **Conectar**: `research_match_send_request` → solicitud de colaboración
7. **Aceptar**: ambas partes aceptan → equipo creado con licencia conjunta

## Seguridad (MVP)

En esta versión MVP:
- Los emails se hashean con SHA-256 (nunca se almacenan en texto plano)
- Los perfiles son pseudonímicos hasta que ambas partes aceptan
- Los datos se almacenan en SQLite local
- El contenido de los commits se hashea para verificación de integridad

En producción se añadirán:
- Cifrado AES-256 en reposo
- Enclaves seguros (TEE) para evaluación
- Cifrado homomórfico
- Fragmentación criptográfica distribuida
