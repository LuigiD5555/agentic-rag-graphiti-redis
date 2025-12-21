# 📝 Configuración de Exclusiones - Guía Rápida

## ✅ Solución Implementada

He configurado `DOCS_EXCLUDE_GLOBS` en `settings.py` para excluir carpetas con código fuente y mantener solo libros/conocimiento.

## 🎯 Qué se Excluyó

### ❌ Excluido (Código fuente, no conocimiento)

```
/mnt/Documents/Documents/Programacion/
├─ Aprendiendo_Programacion/  ← Código de proyectos de aprendizaje
├─ Proyectos_Programacion/    ← Código de proyectos activos
├─ Deprecated*/                ← Proyectos viejos/fallidos
├─ Certificates/               ← Miles de PDFs de certificados
├─ Odoo/                       ← Sistema Odoo completo
└─ fact_checker*/              ← Proyecto con archivos estáticos
```

### ✅ Incluido (Conocimiento útil para RAG)

```
/mnt/resources/Libros/Aprendizaje/  ← Libros de programación (PDFs educativos)
```

## 🔧 Configuración Actual

En [`src/settings.py:140-153`](../src/settings.py#L140-L153):

```python
DOCS_EXCLUDE_GLOBS = (
    # Exclude all programming projects and code
    "*/Programacion/Aprendiendo_Programacion/*",
    "*/Programacion/Proyectos_Programacion/*",
    "*/Programacion/Deprecated*",

    # Exclude specific heavy folders
    "*/Certificates/*",
    "*/Odoo/*",
    "*/fact_checker*",
)
```

## 🚀 Probar la Configuración

Ejecuta la ingesta nuevamente:

```bash
# Dentro del contenedor
python -m src.rag.ingestion
```

**Deberías ver:**
```
INFO: Excluded path patterns: ['*/Programacion/Aprendiendo_Programacion/*', ...]
INFO: Candidate files found: ~500-2000 (NO 10,000+)
```

## 📊 Resultado Esperado

| Métrica | Antes | Después |
|---------|-------|---------|
| Directorios visitados | 5,000+ | ~100-300 |
| Archivos candidatos | 10,000+ | ~500-2,000 |
| Tiempo de escaneo | 5+ minutos | <30 segundos |

## 🔄 Alternativa: Cambiar DOCS_PATHS

Si quieres una solución AÚN MÁS SIMPLE, cambia directamente las rutas base:

```python
# En settings.py, línea 129
DOCS_PATHS = [
    # "/mnt/Documents/Documents",  ← Comentar/eliminar esto
    "/mnt/resources/Libros/Aprendizaje",  ← Solo libros
]
```

Esto es más directo: solo escanea libros, nada de código fuente.

## 💡 Añadir Más Exclusiones

Si ves que sigue escaneando cosas que no quieres, añade más patrones:

```python
DOCS_EXCLUDE_GLOBS = (
    "*/Programacion/*",              # Excluir TODA la carpeta Programacion
    "*/node_modules/*",              # Por si algún proyecto los tiene
    "*/env/*",                       # Ambientes virtuales
    "*.test.py",                     # Archivos de test
    "*/tests/*",                     # Carpetas de tests
)
```

## ✅ Verificar Configuración

Después de cambiar `settings.py`, verifica que los patrones estén cargados:

```bash
# Dentro del contenedor
python -c "from src.rag.conf import Config; c = Config(); print('Globs:', c.DOCS_EXCLUDE_GLOBS)"
```

---

**Resumen:** Ahora el sistema excluirá carpetas de código fuente y solo procesará libros en `/mnt/resources/Libros/Aprendizaje`.
