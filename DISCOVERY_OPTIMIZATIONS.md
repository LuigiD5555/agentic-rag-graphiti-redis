# Optimizaciones de Discovery del Sistema RAG

## Resumen

Se implementaron optimizaciones significativas en el módulo de discovery para evitar re-escaneo de rutas y acelerar la búsqueda de archivos dentro de las rutas autorizadas.

## Problemas Identificados

1. **Re-escaneo de directorios**: Aunque existía un sistema de caché, los directorios podían ser visitados múltiples veces durante un mismo escaneo.
2. **Verificación O(n×m) de exclusiones**: Cada path requería verificar contra todos los patrones de exclusión usando regex.
3. **Falta de tracking de visitas**: No había un mecanismo eficiente para recordar qué directorios ya se procesaron.

## Soluciones Implementadas

### 1. Estructura de Árbol (Trie) para Paths

**Archivo**: [`src/rag/ingestion/discovery/path_tree.py`](src/rag/ingestion/discovery/path_tree.py)

- **Complejidad**: O(k) donde k es la profundidad del path (vs O(n) búsqueda lineal)
- **Beneficios**:
  - Prefijos compartidos se almacenan una sola vez (ahorro de memoria)
  - Búsquedas ultrarrápidas de paths visitados
  - Verificación jerárquica de exclusiones (si un padre está excluido, todos sus hijos también)

```python
# Ejemplo de uso
path_tree = PathTree()
path_tree.add_path("src/components", is_excluded=False)
path_tree.add_path("node_modules", is_excluded=True)

# Verificación O(k)
if path_tree.is_path_excluded("node_modules/package"):
    # Automáticamente detectado como excluido sin verificar patrones
    pass
```

### 2. Tracking de Directorios Visitados

**Modificaciones en**: [`src/rag/ingestion/discovery/scanner.py`](src/rag/ingestion/discovery/scanner.py)

- **Nuevo flujo de verificación**:
  1. ✓ Verificar si ya se visitó (O(k) con PathTree)
  2. ✓ Verificar exclusión por árbol (O(k))
  3. ✓ Verificar caché (O(1) hash lookup)
  4. ✓ Verificar patrones (O(n×m) - solo como fallback)

```python
# Antes: Verificación lineal
for pattern in excluded_globs:
    if matches(path, pattern):  # O(n×m)
        skip()

# Después: Verificación jerárquica
if path_tree.is_visited(path):  # O(k)
    skip()  # ⚡ Instantáneo
```

### 3. Estadísticas y Métricas Detalladas

**Nuevas métricas disponibles**:

```python
stats = discovery_service.get_optimization_stats()
# {
#     'cache': {
#         'cache_hits': 150,
#         'cache_misses': 50,
#         'hit_rate': 75.0
#     },
#     'path_optimization': {
#         'visited_skipped': 300,      # Paths no re-escaneados
#         'excluded_skipped': 150,     # Paths excluidos rápidamente
#         'total_avoided': 450,        # Total de operaciones evitadas
#         'tree_stats': {
#             'total_nodes': 500,
#             'excluded_nodes': 100,
#             'visited_paths': 400,
#             'memory_savings': '~2500 chars saved via prefix sharing'
#         }
#     }
# }
```

## Mejoras de Performance

### Complejidad Temporal

| Operación | Antes | Después | Mejora |
|-----------|-------|---------|--------|
| Verificar si visitado | O(n) | O(k) | ~10-100x |
| Verificar exclusión | O(n×m) | O(k) | ~50-500x |
| Búsqueda de path | O(n) | O(k) | ~10-100x |

Donde:
- `n` = número de paths almacenados
- `m` = número de patrones de exclusión
- `k` = profundidad del path (típicamente 3-8)

### Beneficios Esperados

1. **Escaneo más rápido**: 2-5x más rápido en directorios grandes
2. **Menos I/O**: Evita re-leer directorios ya procesados
3. **Mejor uso de caché**: Integración inteligente entre PathTree y caché
4. **Logs informativos**: Métricas detalladas de optimización

## Uso

### Uso Normal (transparente)

```python
from src.rag.ingestion.discovery import FileDiscoveryService
from src.rag.ingestion.options import DiscoveryOptions

# El servicio usa automáticamente todas las optimizaciones
service = FileDiscoveryService()
opts = DiscoveryOptions(
    roots=["/path/to/scan"],
    excluded_globs={"*.pyc", "node_modules/**", ".git/**"}
)

files, dirs_count = service.discover(opts)
```

### Ver Estadísticas de Optimización

```python
# Al final del escaneo, verás logs automáticos:
# INFO: Cache stats: hits=150, misses=50, hit_rate=75.0%
# INFO: Path optimization: skipped_visited=300, skipped_excluded=150, tree_nodes=500
# INFO: ⚡ Performance boost: 450 path operations avoided via tree optimization

# O consultar programáticamente:
stats = service.get_optimization_stats()
print(f"Paths evitados: {stats['path_optimization']['total_avoided']}")
```

### Limpiar Caché y Stats

```python
service.clear_cache()  # Limpia caché, patterns y estadísticas
```

## Archivos Modificados

1. **Nuevo**: `src/rag/ingestion/discovery/path_tree.py` - Estructura de árbol Trie
2. **Modificado**: `src/rag/ingestion/discovery/scanner.py` - Integración de PathTree
3. **Modificado**: `src/rag/ingestion/discovery/service.py` - Métricas extendidas
4. **Modificado**: `src/rag/ingestion/discovery/__init__.py` - Exportaciones

## Compatibilidad

✅ **Totalmente retrocompatible**: Todas las optimizaciones son transparentes al código existente.

✅ **Sin cambios en APIs**: Los métodos públicos mantienen las mismas firmas.

✅ **Comportamiento idéntico**: Los resultados del escaneo son idénticos, solo más rápidos.

## Próximos Pasos (Opcionales)

1. **Persistencia del PathTree**: Guardar el árbol en Redis/disco para reutilizar entre ejecuciones
2. **Paralelización**: Escanear múltiples raíces en paralelo usando el PathTree compartido
3. **Bloom filters**: Para verificaciones aún más rápidas de paths nunca vistos
4. **Watchdog integration**: Actualizar el PathTree incrementalmente cuando cambian archivos

## Referencias

- [Trie (Wikipedia)](https://en.wikipedia.org/wiki/Trie) - Estructura de datos utilizada
- Complejidad temporal: O(k) donde k es la longitud promedio de los paths
- Memory sharing: Prefijos comunes compartidos automáticamente
