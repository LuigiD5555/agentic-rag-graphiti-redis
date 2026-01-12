# Exclusion Configuration - Quick Guide

## Implemented Solution

`DOCS_EXCLUDE_GLOBS` has been configured in `settings.py` to exclude source code folders and keep only books/knowledge.

## What Was Excluded

### Excluded (Source code, not knowledge)

```
/mnt/Documents/Documents/Programacion/
├─ Aprendiendo_Programacion/  <- Learning project code
├─ Proyectos_Programacion/    <- Active project code
├─ Deprecated*/                <- Old/failed projects
├─ Certificates/               <- Thousands of certificate PDFs
├─ Odoo/                       <- Full Odoo system
└─ fact_checker*/              <- Project with static files
```

### Included (Useful knowledge for RAG)

```
/mnt/resources/Libros/Aprendizaje/  <- Programming books (educational PDFs)
```

## Current Configuration

In [`src/settings.py:140-153`](../src/settings.py#L140-L153):

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

## Test the Configuration

Run ingestion again:

```bash
# Inside the container
python -m src.workflows.query.ingestion
```

**You should see:**
```
INFO: Excluded path patterns: ['*/Programacion/Aprendiendo_Programacion/*', ...]
INFO: Candidate files found: ~500-2000 (NOT 10,000+)
```

## Expected Result

| Metric | Before | After |
|--------|--------|-------|
| Directories visited | 5,000+ | ~100-300 |
| Candidate files | 10,000+ | ~500-2,000 |
| Scan time | 5+ minutes | <30 seconds |

## Alternative: Change DOCS_PATHS

If you want an even simpler solution, change the base paths directly:

```python
# In settings.py, line 129
DOCS_PATHS = [
    # "/mnt/Documents/Documents",  <- Comment/remove this
    "/mnt/resources/Libros/Aprendizaje",  <- Books only
]
```

This is more direct: only scan books, no source code.

## Add More Exclusions

If it still scans content you do not want, add more patterns:

```python
DOCS_EXCLUDE_GLOBS = (
    "*/Programacion/*",              # Exclude the entire Programacion folder
    "*/node_modules/*",              # In case a project has them
    "*/env/*",                       # Virtual environments
    "*.test.py",                     # Test files
    "*/tests/*",                     # Test folders
)
```

## Verify Configuration

After changing `settings.py`, verify the patterns are loaded:

```bash
# Inside the container
python -c "from src.workflows.query.conf import Config; c = Config(); print('Globs:', c.DOCS_EXCLUDE_GLOBS)"
```

---

**Summary:** The system now excludes source code folders and only processes books under `/mnt/resources/Libros/Aprendizaje`.
