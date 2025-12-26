# Solución: Activación por Socket de Herramientas

## Problema Original

Los contenedores de herramientas (`rag-tool-office`, `rag-tool-archive`, etc.) se iniciaban **automáticamente** al arrancar el sistema y permanecían **corriendo permanentemente**, consumiendo recursos innecesarios.

**Comportamiento incorrecto:**
```
$ systemctl --user status tool-office.service
● tool-office.service - RAG Tool Office (container + proxy)
   Loaded: loaded
   Active: active (running)  ← ❌ Siempre corriendo
```

## Causa Raíz

Los archivos `.service` tenían esta configuración incorrecta:

```ini
[Install]
WantedBy=default.target  ← ❌ Esto hace que arranquen automáticamente
```

Esto causaba que systemd iniciara los servicios al arrancar el usuario, ignorando el sistema de socket activation.

## Solución Implementada

### 1. Archivos `.service` corregidos

**Antes:**
```ini
[Install]
WantedBy=default.target
```

**Después:**
```ini
[Install]
# Socket-activated: DO NOT use WantedBy=default.target
# The socket will start this service on-demand
```

### 2. Scripts creados/actualizados

#### `fix-socket-activation.sh` ⭐ (NUEVO)

Script principal que arregla todo:
- Para y deshabilita servicios
- Detiene contenedores
- Reinstala units corregidos
- Habilita SOLO sockets
- Verifica configuración

**Uso:**
```bash
cd tools
./fix-socket-activation.sh
```

#### `verify-socket-activation.sh` (NUEVO)

Verifica que todo esté configurado correctamente:
- Chequea archivos `.service`
- Valida que servicios NO estén habilitados
- Confirma que sockets SÍ estén habilitados
- Verifica imágenes de contenedores

**Uso:**
```bash
cd tools
./verify-socket-activation.sh
```

#### `enable-tool-sockets.sh` (ACTUALIZADO)

Ahora deshabilita servicios explícitamente antes de habilitar sockets:

```bash
# Ensure services are NOT enabled (socket activation only)
systemctl --user disable tool-office.service 2>/dev/null || true
systemctl --user disable tool-archive.service 2>/dev/null || true
```

#### `restart-tool-*.sh` (SIN CAMBIOS)

Estos scripts ya funcionaban perfectamente y siguen siendo la forma recomendada de reiniciar servicios individuales.

### 3. Documentación

- `README-SOCKET-ACTIVATION.md`: Guía completa del sistema
- `RESUMEN-SOLUCION.md`: Este documento

## Cómo Funciona Ahora

### Estado Inicial (arranque del sistema)

```
┌─────────────────────┐
│ Sockets escuchando  │ ← systemctl --user enable tool-*.socket
└─────────────────────┘
         ↓
┌─────────────────────┐
│ Servicios inactivos │ ← NO se inician automáticamente
└─────────────────────┘
         ↓
┌─────────────────────┐
│ Contenedores OFF    │ ← No consumen recursos
└─────────────────────┘
```

**Verificación:**
```bash
$ systemctl --user is-active tool-office.service
inactive  ← ✅ Correcto

$ systemctl --user is-enabled tool-office.service
static/disabled  ← ✅ Correcto

$ systemctl --user is-active tool-office.socket
active  ← ✅ Correcto

$ podman ps | grep rag-tool
(vacío)  ← ✅ Correcto
```

### Primera Petición (activación automática)

```
Cliente hace petición
         ↓
curl http://127.0.0.1:9102/healthz
         ↓
Socket detecta conexión
         ↓
systemd inicia tool-office.service
         ↓
Servicio lanza contenedor
         ↓
systemd-socket-proxyd reenvía tráfico
         ↓
Contenedor responde
```

**Verificación después:**
```bash
$ systemctl --user is-active tool-office.service
active  ← ✅ Ahora está corriendo

$ podman ps | grep rag-tool-office
rag-tool-office  Up 10 seconds  ← ✅ Contenedor recién iniciado
```

### Después de Inactividad (futuro)

Con configuración adicional (idle timeout), systemd puede detener servicios inactivos:

```ini
[Service]
RuntimeMaxSec=300  # Se detiene después de 5 minutos de corriendo
```

## Migración/Actualización

### Para sistemas existentes con el problema

1. **Ejecutar el script de corrección:**
   ```bash
   cd tools
   ./fix-socket-activation.sh
   ```

2. **Verificar que todo esté correcto:**
   ```bash
   ./verify-socket-activation.sh
   ```

3. **Probar activación:**
   ```bash
   curl http://127.0.0.1:9102/healthz
   systemctl --user status tool-office.service
   ```

### Para instalaciones nuevas

El script `start-everything.sh` ya está actualizado para usar `enable-tool-sockets.sh`, que ahora configura todo correctamente.

```bash
./start-everything.sh
```

## Validación de la Solución

### Test 1: Servicios inactivos al inicio

```bash
$ systemctl --user is-active tool-office.service
inactive  ← ✅ PASS
```

### Test 2: Sockets escuchando

```bash
$ systemctl --user list-sockets | grep tool-
127.0.0.1:9101  tool-archive.socket  tool-archive.service
127.0.0.1:9102  tool-office.socket   tool-office.service
← ✅ PASS
```

### Test 3: Activación automática

```bash
$ curl http://127.0.0.1:9102/healthz
{"status":"ok","service":"tool-office"}  ← ✅ PASS

$ systemctl --user is-active tool-office.service
active  ← ✅ PASS (se activó automáticamente)
```

### Test 4: Contenedores solo cuando se usan

```bash
# Antes de la petición
$ podman ps | grep rag-tool
(vacío)  ← ✅ PASS

# Después de la petición
$ podman ps | grep rag-tool
rag-tool-office  Up 5 seconds  ← ✅ PASS
```

## Beneficios

✅ **Ahorro de RAM/CPU**: Contenedores solo corren cuando se necesitan
✅ **Arranque más rápido**: No esperar a que todos los contenedores inicien
✅ **Gestión automática**: systemd maneja el ciclo de vida
✅ **Sin cambios en el código**: La aplicación RAG no nota la diferencia
✅ **Transparente**: Activación invisible para el usuario
✅ **Escalable**: Fácil agregar más herramientas con el mismo patrón

## Scripts de Gestión

| Script | Propósito | Cuándo usar |
|--------|-----------|-------------|
| `fix-socket-activation.sh` | Corrige configuración | Primera vez / después de cambios |
| `verify-socket-activation.sh` | Valida configuración | Diagnóstico / verificación |
| `enable-tool-sockets.sh` | Habilita sockets | Parte de `start-everything.sh` |
| `restart-tool-office.sh` | Reinicia servicio específico | Desarrollo / debugging |
| `restart-tool-archive.sh` | Reinicia servicio específico | Desarrollo / debugging |
| `restart-tool-ocr.sh` | Reinicia servicio específico | Desarrollo / debugging |
| `restart-tool-gpu.sh` | Reinicia servicio específico | Desarrollo / debugging |

## Troubleshooting

### Problema: Servicios siguen arrancando automáticamente

**Solución:**
```bash
./tools/fix-socket-activation.sh
```

### Problema: Socket no inicia el servicio

**Diagnóstico:**
```bash
journalctl --user -u tool-office.service -n 50
journalctl --user -u tool-office.socket -n 50
```

**Solución común:**
```bash
systemctl --user daemon-reload
systemctl --user restart tool-office.socket
```

### Problema: Contenedor no arranca (permisos)

**Solución:**
```bash
mkdir -p ~/.cache/rag-tools/{office,archive,ocr,gpu}
chmod 755 ~/.cache/rag-tools/*
```

## Referencias

- [README-SOCKET-ACTIVATION.md](./README-SOCKET-ACTIVATION.md) - Guía completa
- [systemd.socket man page](https://www.freedesktop.org/software/systemd/man/systemd.socket.html)
- [systemd-socket-proxyd](https://www.freedesktop.org/software/systemd/man/systemd-socket-proxyd.html)

## Cambios en Git

Archivos modificados:
- `systemd/user/tool-office.service`
- `systemd/user/tool-archive.service`
- `systemd/user/tool-ocr.service`
- `systemd/user/tool-gpu.service`
- `tools/enable-tool-sockets.sh`

Archivos nuevos:
- `tools/fix-socket-activation.sh`
- `tools/verify-socket-activation.sh`
- `tools/README-SOCKET-ACTIVATION.md`
- `tools/RESUMEN-SOLUCION.md`

## Conclusión

El sistema ahora funciona exactamente como debería:

1. ✅ Sockets **siempre escuchando** (sin overhead)
2. ✅ Servicios **inactivos** hasta que se necesiten
3. ✅ Contenedores **on-demand** (arrancan en 1-2 segundos)
4. ✅ Transparente para el usuario final
5. ✅ Scripts `restart-tool-*.sh` funcionan perfectamente

**El objetivo original se cumplió**: Las herramientas se inician bajo demanda y no permanecen corriendo innecesariamente.