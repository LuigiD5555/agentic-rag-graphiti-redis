# Memory System

Sistema de memoria jerárquico para RAG con LangChain/LangGraph.

## 📦 Estado de Implementación

### ✅ Fase 1: Fundamentos (COMPLETADA)

**Componentes implementados**:

- ✅ **identifiers.py**: Generación criptográfica de user_id y thread_id
- ✅ **state.py**: Definición del estado de conversación (ConversationState)
- ✅ **checkpointer.py**: Redis checkpointer con TTL inteligente (48h + touch)
- ✅ **Tests**: Suites completas en `tests/memory/`

**Archivos creados**:

```
src/memory/
├── core/
│   ├── identifiers.py      ✅ User/Thread ID generation
│   ├── state.py            ✅ ConversationState definition
│   └── checkpointer.py     ✅ TTL Redis checkpointer
├── layers/                 (Fase 2)
├── compression/            (Fase 2)
├── artifacts/              (Fase 2)
└── context/                (Fase 3)
```

## 🚀 Instalación

### 1. Instalar dependencias

```bash
pip install -r requirements.txt
```

Dependencias añadidas:

```
langgraph
langgraph-checkpoint-redis
```

### 2. Verificar instalación

```bash
# Verificación rápida (sin Redis)
python3 verify_memory_phase1.py

# Tests completos (requiere pytest y Redis)
pytest tests/memory/ -v
```

## 📖 Uso de Fase 1

### Generación de Identidades

```python
from src.memory.core.identifiers import (
    generate_user_id,
    generate_thread_id,
    validate_user_id,
    validate_thread_id,
)

# Generar user_id (SHA-256 estable)
user_id = generate_user_id(
    client_info={"ip": "127.0.0.1", "ua": "Mozilla/5.0"}
)

# Generar thread_id (HMAC-SHA256 único)
thread_id = generate_thread_id(
    user_id=user_id,
    server_secret="your-secret-from-env"  # De THREAD_SECRET en .env
)

# Validar IDs
assert validate_user_id(user_id)
assert validate_thread_id(thread_id)
```

### Gestión de Estado

```python
from src.memory.core.state import (
    create_initial_state,
    add_tool_execution,
    get_recent_tool_executions,
    find_tool_execution_by_id,
    ToolExecution,
)
import time

# Crear estado inicial
state = create_initial_state(
    user_id=user_id,
    thread_id=thread_id
)

# Añadir ejecución de herramienta
execution: ToolExecution = {
    "tool": "office",
    "doc_id": "doc#1",
    "file_path": "/path/to/document.docx",
    "file_hash": "abc123...",
    "summary": "Q3 Financial Report",
    "structure": "12 pages",
    "timestamp": time.time(),
    "output_path": "/tmp/artifacts/thread-xxx/doc1.pdf"
}

state = add_tool_execution(state, execution)

# Recuperar ejecuciones recientes
recent = get_recent_tool_executions(state, n=5)
for exec in recent:
    print(f"{exec['doc_id']}: {exec['summary']}")

# Buscar por ID
doc = find_tool_execution_by_id(state, "doc#1")
```

### Persistencia con Redis (TTL inteligente)

```python
from src.memory.core.checkpointer import create_checkpointer

# Crear checkpointer (requiere Redis corriendo)
checkpointer = create_checkpointer(
    redis_host="127.0.0.1",
    redis_port=6379,
    ttl_seconds=172800  # 48 horas
)

# Usar con LangGraph
from langgraph.graph import StateGraph

graph = StateGraph(ConversationState)
# ... definir nodos ...
compiled = graph.compile(checkpointer=checkpointer)

# Guardar estado - TTL comienza
config = {"configurable": {"thread_id": thread_id}}
compiled.invoke(state, config=config)

# Recuperar estado - TTL se extiende a 48h (touch on access)
state = compiled.get_state(config)
```

## 🔑 Características Clave

### 1. Identidades Criptográficas

- **user_id**: SHA-256 estable (64 chars hex)
  - Generado a partir de client_info
  - Persistente entre sesiones
  - Validación estricta

- **thread_id**: HMAC-SHA256 único (64 chars hex)
  - Derivado de user_id + conversation_seed + server_secret
  - No predecible (seguro)
  - Único por conversación

### 2. Estado de Conversación

`ConversationState` contiene:

- **Identificadores**: user_id, thread_id
- **Mensajes**: Lista de mensajes (hereda de MessagesState)
- **Ventana reciente**: Últimos N mensajes completos
- **Resumen Pareto**: Historia comprimida (20%)
- **Tool memory**: Lista de herramientas usadas
- **Contexto actual**: Estado de la conversación
- **Metadata**: Timestamps, contadores

### 3. TTL Inteligente (Touch on Access)

El checkpointer Redis:

- **put()**: Guarda estado y aplica TTL de 48h
- **get()**: Recupera estado y EXTIENDE TTL a 48h
- **Resultado**: Conversaciones activas viven indefinidamente

**Ejemplo de flujo**:

```
Day 0: Create conversation → TTL = 48h
Day 1: Access conversation → TTL reset to 48h
Day 3: Access conversation → TTL reset to 48h
Day 5: No access for 48h  → Auto-delete
```

## 🧪 Tests

### Tests Unitarios

```bash
# Identifiers
pytest tests/memory/test_identifiers.py -v

# State
pytest tests/memory/test_state.py -v
```

### Cobertura de Tests

**test_identifiers.py**:

- ✅ Generación de user_id (SHA-256)
- ✅ Generación de thread_id (HMAC-SHA256)
- ✅ Validación de formato
- ✅ Determinismo con seeds
- ✅ Unicidad sin seeds

**test_state.py**:

- ✅ Creación de estado inicial
- ✅ Añadir tool executions
- ✅ Recuperar executions recientes
- ✅ Buscar por doc_id
- ✅ Actualización de metadata

## 🔧 Configuración

Añadir a `.env`:

```bash
# Memory System
REDIS_HOST=127.0.0.1
REDIS_PORT=6379
MEMORY_TTL=172800  # 48 horas
THREAD_SECRET=your-secret-key-here  # Generar con: openssl rand -hex 32
```

## 📋 Estado de Implementación Completo

### ✅ Fase 1: Fundamentos (COMPLETADA)
- ✅ `core/identifiers.py` - Generación criptográfica de IDs
- ✅ `core/state.py` - Definición de ConversationState
- ✅ `core/checkpointer.py` - Redis checkpointer con TTL

### ✅ Fase 2: Compresión + Tool Memory (COMPLETADA)
- ✅ `compression/pareto.py` - Compresión 80/20
- ✅ `compression/summarizer.py` - LLM summarizer (LFM2-1.2B)
- ✅ `layers/tool_memory.py` - Gestión de tool memory

### ✅ Fase 3: Context Assembly (COMPLETADA)
- ✅ `context/builder.py` - Constructor de contexto jerárquico

### ✅ Fase 4-5: ChatMemory (COMPLETADA)
- ✅ `snapshot.py` - Creación de snapshots comprimidos
- ✅ `storage/chat_memory_schema.py` - Esquema Weaviate para ChatMemory
- ✅ `storage/chat_memory_persistence.py` - Persistencia de snapshots
- ✅ `retrieval/cross_chat.py` - Cross-chat retrieval

### ✅ Fase 6: RRF + MMR (COMPLETADA)
- ✅ `retrieval/rrf_fusion.py` - Reciprocal Rank Fusion
- ✅ `retrieval/mmr.py` - Maximal Marginal Relevance (anti-eco)
- ✅ `integration.py` - ChatMemoryManager integrado

### 🔄 Pendiente: Integración con API
- [ ] Modificar `src/api/ollama/router.py` para usar ChatMemory
- [ ] Integrar snapshot creation en flujo de conversación
- [ ] Añadir cross-chat retrieval a RAG pipeline
- [ ] Configurar cleanup automático de snapshots expirados

## 🐛 Troubleshooting

### ModuleNotFoundError: No module named 'langgraph'

```bash
pip install langgraph langgraph-checkpoint-redis
```

### Redis connection refused

```bash
# Verificar que Redis esté corriendo
systemctl --user status redis
# O con podman-compose
podman-compose up -d redis
```

### Tests fallan con Redis

```bash
# Verificar conexión
redis-cli -h 127.0.0.1 -p 6379 ping
# Debería responder: PONG
```

## 📚 Referencias

- [Plan completo](../../docs/MEMORY_SYSTEM_IMPLEMENTATION_PLAN.md)
- [LangGraph Docs](https://langchain-ai.github.io/langgraph/)
- [Redis Checkpointer](https://langchain-ai.github.io/langgraph/how-tos/persistence/)

## ✅ Checklist de Fase 1

- [x] Dependencias añadidas a requirements.txt
- [x] Estructura de directorios creada
- [x] identifiers.py implementado y testeado
- [x] state.py implementado y testeado
- [x] checkpointer.py implementado
- [x] Tests unitarios creados
- [x] Script de verificación creado
- [x] Documentación completada

**Estado**: ✅ **FASE 1 COMPLETADA**

**Siguiente paso**: Instalar dependencias y comenzar Fase 2.
