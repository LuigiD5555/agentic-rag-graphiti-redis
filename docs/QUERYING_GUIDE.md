# Guía Detallada de Queries (CLI + API)

Este documento explica **cómo hacer queries** al sistema RAG (desde terminal y vía HTTP), con ejemplos y “flags”/parámetros. También incluye una verificación rápida de qué documentación del repo está vigente y qué partes quedaron desfasadas.

**Fecha de verificación**: 2026-02-02  
**Fuentes revisadas** (en este repo): `src/query/cli.py`, `src/api/app.py`, `src/api/routes/rag.py`, `src/api/models.py`, `src/api/models_ollama.py`, `src/api/compatibility/openai/*`, `src/api/compatibility/ollama/router.py`, `src/middleware/thread_manager.py`, `start-everything.sh`, `podman-compose.yml`, `docs/START_HERE.md`, `README.md`.

---

## 0) Requisitos mínimos (antes de preguntar)

Para que una query sea útil, necesitas:

0) **Dependencias Python instaladas** (si ejecutas CLI o API “local” en host):
```bash
pip install -r requirements.txt
```

1) **Servicios arriba** (mínimo Weaviate + Neo4j + LM Studio + RAG API):
- Weaviate: `http://localhost:8080`
- Neo4j: `http://localhost:7474` (HTTP) / `bolt://localhost:7687`
- LM Studio: `http://localhost:1234` (OpenAI-compatible)
- RAG API: por defecto el stack la expone en `http://localhost:8000` (ver `start-everything.sh` y `podman-compose.yml`).

2) **Haber ingerido documentos** (si no hay data en Weaviate, el RAG responderá “vacío” o con muy poca relevancia):
- Ingesta: `python -m src.main`

3) **Checks rápidos**:
```bash
curl -s http://localhost:8000/health | jq
curl -s http://localhost:8080/v1/.well-known/ready | jq
curl -s http://localhost:1234/v1/models | jq
```

---

## 1) ¿Qué interfaz de query usar?

### Opción A: CLI (terminal) — recomendado para pruebas rápidas
- Ideal si estás en la misma máquina donde corre el stack.
- No requiere saber payloads JSON.

### Opción B: HTTP “directo” (`POST /rag/query`) — recomendado para RAG puro y controlado
- Útil cuando quieres **RAG determinista** (query + top_k + filtros + prompt) sin el wrapper OpenAI/Ollama.
- Permite `filters` e `include_sources`.

### Opción C: OpenAI-compatible (`/v1/chat/completions` y `/v1/responses`)
- Recomendado si quieres integrar con clientes/SDKs “OpenAI style” (o herramientas que esperan ese contrato).
- Incluye **manejo de thread/user IDs** vía middleware (ver sección de headers).
- Soporta “streaming” SSE, pero **solo si el cliente acepta** `text/event-stream`.

### Opción D: Ollama-like (`/api/chat`, `/api/generate`)
- Recomendado si tu cliente ya habla “Ollama”.
- Tiene `rag.enabled` para prender/apagar RAG por request.

---

## 2) CLI: cómo hacer queries + flags

El CLI actual para queries está en `src/query/cli.py`.

### Ayuda rápida
```bash
python -m src.query.cli --help
```

### Modo interactivo (sin argumento)
```bash
python -m src.query.cli
```
- Salir: `exit`, `quit` o `q`

### Una sola pregunta (posicional)
```bash
python -m src.query.cli "Explica la arquitectura del sistema"
```

### Flags (CLI)
- `--top-k`, `-k`: cuántos chunks/documentos recuperar (default: `5` en CLI).
  ```bash
  python -m src.query.cli "Resume mis documentos de X" --top-k 10
  ```
- `--question`, `-q`: **deprecated** (sigue existiendo por compatibilidad; usa el argumento posicional).
  ```bash
  python -m src.query.cli --question "¿Qué dice el doc sobre Y?"
  ```

**Nota importante (vigencia / comportamiento):**
- El CLI crea el runtime con `enable_rag_gating=False` (o sea: **no “salta” RAG por intención**, siempre intenta retrieval). Esto es distinto a algunas rutas HTTP donde el gating puede estar activado dependiendo de settings.

---

## 3) HTTP: detectar puerto y modo real (OpenAI vs Ollama)

En este repo el modo HTTP depende de `API_MODE`:
- `API_MODE=openai` habilita `GET /v1/models`, `POST /v1/chat/completions`, `POST /v1/responses`, `POST /v1/embeddings`.
- `API_MODE=ollama` habilita `POST /api/chat`, `POST /api/generate`, `POST /api/embeddings`, etc.
- En **ambos** casos se incluye `POST /rag/query` y `POST /rag/ingest`.

### Ver el modo y endpoints expuestos (recomendado)
```bash
curl -s http://localhost:8000/ | jq
```
Esto retorna `api_mode` y un mapa de endpoints disponibles.

### Nota sobre puertos (vigencia)
- `start-everything.sh` y `podman-compose.yml` asumen **RAG API en `8000`**.
- Hay docs que todavía mencionan `5555` para la API; ese puerto suele ser **Open WebUI**, y además puede colisionar con el “socket server” TCP (ver sección 7).

---

## 4) Endpoint recomendado para RAG puro: `POST /rag/query`

Router: `src/api/routes/rag.py`

### Request (campos principales)
- `query` (string): tu pregunta
- `top_k` (int, opcional): cuántos resultados recuperar
- `filters` (dict, opcional): filtros por metadata (ver sección 6)
- `include_sources` (bool, default `true`)
- `temperature` (float, opcional)
- `max_tokens` (int, opcional)
- `system` (string, opcional): system prompt override
- **Nota**: el estilo de respuesta puede configurarse con **Answer Modes** (ver sección 8).

### Ejemplo (curl)
```bash
curl -sS -X POST http://localhost:8000/rag/query \
  -H "Content-Type: application/json" \
  -d '{
    "query": "¿Qué decisiones de arquitectura aparecen en los docs?",
    "top_k": 8,
    "include_sources": true,
    "temperature": 0.2
  }' | jq
```

### Ejemplo con `system` (control de estilo)
```bash
curl -sS -X POST http://localhost:8000/rag/query \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Resume los puntos clave",
    "system": "Responde en viñetas, con secciones cortas. No inventes. Cita rutas de archivos cuando aplique.",
    "top_k": 10
  }' | jq
```

---

## 5) OpenAI-compatible: `POST /v1/chat/completions`

Router: `src/api/compatibility/openai/chat.py`  
Modelos: `src/api/models.py`

### Campos útiles (además de los estándar)
- `top_k` (int): **RAG-specific** para retrieval
- `temperature`, `max_tokens`: se respetan y se pasan al orquestador
- `stream`: si `true`, intenta SSE (pero ver “streaming” abajo)

### Ejemplo (curl JSON)
```bash
curl -sS -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-User-ID: demo-user" \
  -H "X-Thread-ID: demo-thread-001" \
  -d '{
    "model": "rag-local",
    "messages": [
      {"role": "user", "content": "¿Qué hace este proyecto y cómo se consulta?"}
    ],
    "top_k": 8,
    "temperature": 0.3,
    "max_tokens": 800
  }' | jq
```

### Streaming (SSE) — requisito importante
El endpoint **solo emite SSE** si:
- `stream=true` en el body, **y**
- el cliente manda `Accept: text/event-stream`

Ejemplo:
```bash
curl -N -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{
    "model": "rag-local",
    "messages": [{"role": "user", "content": "Dame un resumen corto"}],
    "stream": true,
    "top_k": 5
  }'
```

### Headers de memoria: `X-User-ID` y `X-Thread-ID`
Middleware: `src/middleware/thread_manager.py`

- Si no envías headers, el servidor generará IDs (basados en IP/UA + contenido).
- Si quieres **memoria consistente** entre requests, envía siempre:
  - `X-User-ID`: para separar usuarios
  - `X-Thread-ID`: para agrupar conversación
- El servidor responde esos headers también (para que el cliente los reutilice).
- **Respuesta por modo**: el modo de respuesta (detallado/conciso u otros) se resuelve por conversación usando el `X-Thread-ID`.

---

## 6) Filtros (`filters`): cómo funcionan y ejemplos

Implementación: `src/workflows/query/retrieval/weaviate_retriever.py#L375` (método `_build_filters`)

Reglas:
- `filters` es un dict `{propiedad: valor}`.
- Si el valor es lista/tupla/set → `contains_any`.
- Si el valor es escalar → `equal`.
- Todos los filtros se combinan con AND.

### Propiedades típicas (depende del schema/ingesta)
En el vector store existen propiedades como: `source`, `file_id`, `file_path`, `chunk_index`, `owner_id`, `visibility`, etc. (ver `src/backends/storage/vector/__init__.py`).

### Ejemplos
Filtrar por un solo archivo (igualdad):
```json
{
  "filters": {"source": "/mnt/Documents/Documents/mi_doc.pdf"}
}
```

Filtrar por múltiples fuentes (OR dentro del campo):
```json
{
  "filters": {"source": ["/mnt/Documents/Documents/a.pdf", "/mnt/Documents/Documents/b.pdf"]}
}
```

Filtrar por `file_id`:
```json
{
  "filters": {"file_id": "abc123"}
}
```

---

## 7) Socket server (TCP) — estado y por qué casi no se usa

Existe un servidor TCP “tipo telnet” en `src/workflows/query/cli/socket.py` (y un `SocketServer` en `src/workflows/query/socket_server.py`), pero:
- No está integrado al flujo principal (compose / scripts).
- El `SOCKET_PORT` default es `5555`, que normalmente se usa para **Open WebUI** en este repo → **colisión de puertos**.
- Usa un camino más “legacy” (motor `RAGEngine`/`Agent`) distinto al API/Orchestrator moderno.

Si aun así quieres probarlo (solo local, experimental):
```bash
python -m src.workflows.query.cli.socket
```
Y luego conectar con:
```bash
nc 127.0.0.1 5555
```

Recomendación: preferir **HTTP** (`/rag/query` o `/v1/*` o `/api/*`).

---

## 8) Uso inteligente (prácticas recomendadas)

### Elegir `top_k` sin degradar calidad
- `top_k` chico (3–8): respuestas más rápidas y menos ruido.
- `top_k` grande (10–40): útil para preguntas amplias, pero puede meter contexto irrelevante.
- Si ves “respuesta genérica” o sin referencias claras: sube `top_k` un poco y/o usa `filters`.

### Forzar precisión con filtros
- Cuando sabes el archivo/carpeta objetivo, filtra por `source` o `file_path`.
- Para comparativas (“A vs B”), filtra por lista en `source`.

### Manejo de sesiones (memoria)
- Reusa el mismo `X-Thread-ID` cuando quieras seguimiento (“sigue explicando…”, “ahora hazlo para…”).
- Cambia de thread para temas no relacionados.

### Control de estilo con `system`
- En `/rag/query` puedes sobreescribir el system prompt por request (por ejemplo: “contesta solo con bullets, no inventes, cita rutas”).

### Modos de respuesta (Answer Modes) — runtime y por conversación
El sistema soporta **modos configurables** para el estilo de respuesta:
- `detailed` (default) y `concise` vienen listos.
- Puedes **crear/editar** modos en tiempo de ejecución (sin reinicio).
- El modo puede persistirse por conversación usando `X-Thread-ID`.

**Endpoints:**
- `GET /rag/answer-modes` → lista modos
- `PUT /rag/answer-modes` → actualiza todos (merge por defecto)
- `GET /rag/answer-modes/{mode}` → obtiene uno
- `PUT /rag/answer-modes/{mode}` → crea/actualiza uno
- `DELETE /rag/answer-modes/{mode}` → elimina uno

**Ejemplo: crear modo con pipeline y preanálisis**
```bash
curl -sS -X PUT "http://localhost:8000/rag/answer-modes/analitico?merge=true" \
  -H "Content-Type: application/json" \
  -d '{
    "description": "Respuesta con análisis previo.",
    "instruction_by_lang": {
      "es": "Responde con profundidad y estructura clara."
    },
    "triggers": ["modo analitico", "analitico"],
    "persist_triggers": ["modo", "por defecto", "desde ahora"],
    "pipeline": [
      {
        "type": "preanalysis",
        "config": {
          "enabled": true,
          "prompt_es": "Genera puntos clave, supuestos y datos faltantes en 3-5 bullets. Sin razonamiento paso a paso.",
          "temperature": 0.2,
          "max_tokens": 256,
          "include_context": true
        }
      },
      { "type": "answer" }
    ]
  }' | jq
```

**Cómo activar modo por conversación:**
- “Modo conciso desde ahora”
- “Modo analítico por defecto”

**Dónde se guardan:**
- `data/settings.json` → clave `ANSWER_MODES`

---

## 9) Qué docs están desfasadas (verificación de vigencia)

En este repo encontré estas discrepancias típicas:
- `README.md` mencionaba la API en `5555` y tiene secciones “Query the RAG / Socket Server Mode” como placeholders: el stack y scripts actuales apuntan a **API en `8000`**.
- `docs/START_HERE.md` tenía un comando de query que no corresponde al CLI actual (`python -m src.workflows.query.cli ...`). El CLI vigente para queries rápidas es `python -m src.query.cli`.

Este archivo busca ser la referencia vigente para “cómo hacer queries”.
