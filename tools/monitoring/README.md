# RAG Monitoring Container

Contenedor dedicado para monitoreo, diagnóstico y análisis de logs del sistema RAG.

## 📋 Descripción

Este contenedor separa todas las funcionalidades de monitoreo, análisis de logs y diagnóstico del contenedor principal de la aplicación, siguiendo el principio de separación de responsabilidades.

## 🎯 Componentes Incluidos

### 1. **Análisis de Logs** (`src/tools/analyze_logs.py`)
- Analiza logs de systemd journal
- Detección de patrones de error
- Identificación de anomalías
- Generación de reportes JSON y texto

### 2. **Verificador de Setup** (`src/tools/setup_verifier.py`)
- Verifica configuración del sistema
- Comprueba archivos necesarios
- Valida puertos y servicios
- Verifica dependencias

### 3. **Diagnóstico de Configuración** (`scripts/diagnose_config.py`)
- Verifica conectividad de servicios
- Comprueba Redis, Weaviate, Neo4j
- Valida configuración de embeddings
- Test de conectividad LM Studio

### 4. **Verificación de Datos** (`scripts/verify_data.py`)
- Verifica datos en Weaviate
- Cuenta documentos
- Muestra ejemplos
- Ejecuta queries de prueba

### 5. **Verificación de Streaming** (`scripts/verify_streaming.py`)
- Verifica ingesta streaming
- Queries concurrentes durante ingesta
- Monitoreo de progreso

### 6. **Monitoreo de Volúmenes** (`src/utils/volume_monitor.py`, `src/utils/volume_watcher.py`)
- Detecta disponibilidad de volúmenes externos
- Monitorea reconexiones
- Gestiona fallbacks

### 7. **Daemon de Monitoreo** (`src/monitor_daemon.py`)
- Servicio continuo de monitoreo
- Health checks periódicos
- Análisis automático de logs
- Generación de reportes

## 🚀 Uso

### Inicio del Contenedor

```bash
# Iniciar con el resto del stack
podman-compose up -d monitoring

# Ver logs del contenedor
podman-compose logs -f monitoring
```

### Modos de Operación

El contenedor soporta múltiples modos de operación:

#### 1. **Modo Daemon** (por defecto)
Ejecuta monitoreo continuo en segundo plano:

```bash
podman-compose exec monitoring /entrypoint.sh daemon
```

#### 2. **Análisis de Logs**
Analizar logs manualmente:

```bash
# Analizar últimas 24 horas
podman-compose exec monitoring /entrypoint.sh logs

# Analizar última semana
podman-compose exec monitoring /entrypoint.sh logs --since "1 week ago"

# Analizar herramienta específica
podman-compose exec monitoring /entrypoint.sh logs --tool office

# Exportar a JSON
podman-compose exec monitoring /entrypoint.sh logs --format json --output /app/reports/analysis.json
```

#### 3. **Verificación de Setup**
Verificar configuración del sistema:

```bash
# Verificación completa
podman-compose exec monitoring /entrypoint.sh verify

# Salida JSON
podman-compose exec monitoring /entrypoint.sh verify --json

# Modo silencioso (solo exit code)
podman-compose exec monitoring /entrypoint.sh verify --quiet
```

#### 4. **Diagnóstico de Configuración**
Diagnosticar conexiones y configuración:

```bash
podman-compose exec monitoring /entrypoint.sh diagnose
```

#### 5. **Verificación de Datos**
Verificar datos en Weaviate:

```bash
podman-compose exec monitoring /entrypoint.sh verify-data
```

#### 6. **Monitoreo de Volúmenes**
Monitorear disponibilidad de volúmenes:

```bash
podman-compose exec monitoring /entrypoint.sh volumes
```

#### 7. **Shell Interactivo**
Acceder al contenedor:

```bash
podman-compose exec monitoring /entrypoint.sh shell
```

## ⚙️ Configuración

### Variables de Entorno

Configurables en `.env`:

```bash
# Intervalo de monitoreo (segundos)
MONITORING_INTERVAL=300

# Habilitar análisis de logs
ENABLE_LOG_ANALYSIS=true

# Habilitar monitoreo de volúmenes
ENABLE_VOLUME_MONITORING=true

# Habilitar health checks
ENABLE_HEALTH_CHECKS=true

# Nivel de log
MONITORING_LOG_LEVEL=INFO

# Puerto del dashboard (opcional)
MONITORING_DASHBOARD_PORT=8888

# Recursos del contenedor
MONITORING_CPUS=0.5
MONITORING_MEMORY=512m
```

### Endpoints de Servicios

El contenedor utiliza `host` network mode para acceder a servicios:

- **Redis**: `127.0.0.1:6379`
- **Weaviate**: `http://127.0.0.1:8080`
- **Neo4j**: `bolt://127.0.0.1:7687`
- **LM Studio**: `http://127.0.0.1:1234`

## 📊 Reportes

Los reportes se guardan en volúmenes persistentes:

```
/app/logs/          # Logs del daemon de monitoreo
/app/reports/       # Reportes JSON de análisis
/app/data/          # Datos persistentes
```

Acceder desde el host:

```bash
# Ver reportes generados
ls -la ./monitoring_reports/

# Ver último reporte de salud
cat ./monitoring_reports/health_*.json | jq .

# Ver último reporte de logs
cat ./monitoring_reports/logs_*.json | jq .
```

## 🔍 Health Checks

El daemon ejecuta health checks periódicos:

### Redis
- Conectividad
- Memoria usada
- Clientes conectados
- Total de keys

### Weaviate
- Conectividad
- Versión
- Número de colecciones

### Neo4j
- Conectividad
- Conteo de nodos

## 📁 Estructura del Proyecto

```
tools/monitoring/
├── Dockerfile              # Imagen del contenedor
├── requirements.txt        # Dependencias Python
├── entrypoint.sh          # Script de entrada
├── README.md              # Esta documentación
├── config/                # Configuraciones
├── src/
│   ├── __init__.py
│   ├── monitor_daemon.py  # Daemon principal
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── analyze_logs.py      # Análisis de logs
│   │   └── setup_verifier.py    # Verificador de setup
│   └── utils/
│       ├── __init__.py
│       ├── volume_monitor.py    # Monitor de volúmenes
│       └── volume_watcher.py    # Watcher de volúmenes
└── scripts/
    ├── __init__.py
    ├── diagnose_config.py       # Diagnóstico
    ├── verify_data.py           # Verificación de datos
    └── verify_streaming.py      # Verificación streaming
```

## 🔧 Desarrollo

### Build del Contenedor

```bash
# Build manual
podman build -t rag-monitoring -f tools/monitoring/Dockerfile .

# Build con compose
podman-compose build monitoring
```

### Agregar Nuevas Herramientas

1. Crear script en `tools/monitoring/src/tools/` o `tools/monitoring/scripts/`
2. Agregar modo en `entrypoint.sh`
3. Documentar en este README

### Extender el Daemon

Editar `tools/monitoring/src/monitor_daemon.py` para agregar:
- Nuevos health checks
- Nuevas métricas
- Alertas personalizadas

## 📝 Logs y Debugging

```bash
# Ver logs en tiempo real
podman-compose logs -f monitoring

# Ver logs históricos
podman logs rag-graphiti-agentic_monitoring_1

# Inspeccionar contenedor
podman inspect rag-graphiti-agentic_monitoring_1

# Acceder al shell
podman-compose exec monitoring bash
```

## 🎨 Dashboard Web (Opcional)

Para habilitar el dashboard web:

1. Descomentar la sección de puertos en `podman-compose.yml`
2. Implementar `src/dashboard.py` (actualmente no incluido)
3. Acceder a `http://127.0.0.1:8888`

## 🚨 Troubleshooting

### El contenedor no inicia

```bash
# Verificar dependencias
podman-compose ps

# Ver logs de error
podman-compose logs monitoring
```

### No puede acceder a servicios

Verificar que el contenedor use `network_mode: "host"` y que los servicios estén corriendo:

```bash
# Verificar servicios
podman-compose ps

# Test de conectividad desde el contenedor
podman-compose exec monitoring curl http://127.0.0.1:8080/v1/meta
```

### Permisos de journal logs

El contenedor necesita acceso a `/var/log/journal` y `/run/log/journal`:

```bash
# Verificar montaje
podman inspect rag-graphiti-agentic_monitoring_1 | grep -A 5 Mounts
```

## 📖 Referencias

- [Systemd Journal](https://www.freedesktop.org/software/systemd/man/journalctl.html)
- [Weaviate API](https://weaviate.io/developers/weaviate/api)
- [Redis Commands](https://redis.io/commands)
- [Neo4j Driver](https://neo4j.com/docs/python-manual/current/)

## 🤝 Contribuciones

Para contribuir:

1. Crear feature branch
2. Agregar herramienta en `tools/monitoring/`
3. Actualizar `entrypoint.sh`
4. Documentar en README
5. Crear pull request

## 📄 Licencia

Mismo que el proyecto principal.
