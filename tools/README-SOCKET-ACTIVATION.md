# Socket Activation - Guía de Uso

## ¿Qué es Socket Activation?

Socket activation es una característica de systemd que permite que los servicios se inicien **automáticamente** solo cuando se necesitan, y se detengan cuando no están en uso.

### Ventajas

✅ **Ahorro de recursos**: Los contenedores solo corren cuando se usan
✅ **Inicio rápido del sistema**: No se esperan todos los contenedores al arrancar
✅ **Gestión automática**: systemd maneja el ciclo de vida de los servicios
✅ **Transparente**: La aplicación no nota la diferencia

## Arquitectura

```
Aplicación RAG
    ↓
  Socket (puerto 9102)  ← Siempre escuchando
    ↓
  systemd detecta conexión
    ↓
  Inicia tool-office.service
    ↓
  Servicio lanza contenedor
    ↓
  systemd-socket-proxyd reenvía tráfico
    ↓
  Contenedor procesa la petición
```

## Componentes

Cada herramienta (office, archive, ocr, gpu) tiene **2 archivos**:

### 1. Socket Unit (`.socket`)

Escucha en un puerto específico y espera conexiones.

```ini
[Socket]
ListenStream=127.0.0.1:9102  # Puerto en el que escucha
NoDelay=true

[Install]
WantedBy=sockets.target  # Se habilita con los sockets del sistema
```

### 2. Service Unit (`.service`)

Define qué hacer cuando el socket recibe una conexión.

```ini
[Service]
ExecStartPre=/usr/bin/podman run -d ...  # Inicia el contenedor
ExecStart=/usr/lib/systemd/systemd-socket-proxyd 127.0.0.1:19102
ExecStop=/usr/bin/podman stop ...         # Para el contenedor

[Install]
# IMPORTANTE: NO tiene WantedBy=default.target
# El socket lo inicia automáticamente
```

## Flujo de Estados

### Estado Inicial (después de `enable-tool-sockets.sh`)

```
tool-office.socket   → ACTIVO (escuchando)
tool-office.service  → INACTIVO (esperando)
Contenedor           → NO EXISTE
```

### Después de la Primera Petición

```
curl http://127.0.0.1:9102/healthz
```

```
tool-office.socket   → ACTIVO (escuchando)
tool-office.service  → ACTIVO (corriendo)
Contenedor           → CORRIENDO
```

### Después de Inactividad (configurable)

```
tool-office.socket   → ACTIVO (escuchando)
tool-office.service  → INACTIVO (detenido automáticamente)
Contenedor           → DETENIDO
```

## Scripts Disponibles

### 1. `install-systemd.sh`

Instala los archivos `.socket` y `.service` en `~/.config/systemd/user/`.

```bash
cd tools
./install-systemd.sh
```

### 2. `enable-tool-sockets.sh`

Habilita y arranca los sockets (NO los servicios).

```bash
cd tools
./enable-tool-sockets.sh
```

**Lo que hace:**
- ✅ Habilita `tool-*.socket`
- ❌ NO habilita `tool-*.service` (importante!)
- 🔥 Hace un "warmup" opcional (primera activación)

### 3. `fix-socket-activation.sh` ⭐

Limpia cualquier configuración incorrecta y restablece todo correctamente.

```bash
cd tools
./fix-socket-activation.sh
```

**Úsalo cuando:**
- Los servicios estén corriendo permanentemente
- Después de cambios en los archivos `.service` o `.socket`
- Para verificar que todo esté configurado correctamente

### 4. `restart-tool-*.sh` (office, archive, ocr, gpu)

Reinicia una herramienta específica de forma segura.

```bash
cd tools
./restart-tool-office.sh
```

**Lo que hace:**
- Para el socket y servicio
- Recarga systemd
- Inicia el socket
- Hace healthcheck
- Verifica permisos

## Comandos Útiles

### Ver estado de sockets

```bash
systemctl --user list-sockets | grep tool-
```

### Ver estado de servicios

```bash
systemctl --user status tool-office.service
systemctl --user status tool-archive.service
```

### Ver logs en tiempo real

```bash
journalctl --user -u tool-office.service -f
journalctl --user -u tool-archive.service -f
```

### Ver contenedores corriendo

```bash
podman ps | grep rag-tool
```

### Probar activación manual

```bash
# Esto debe iniciar el contenedor automáticamente
curl http://127.0.0.1:9102/healthz

# Verifica que el servicio arrancó
systemctl --user status tool-office.service
```

### Detener todo (emergencia)

```bash
systemctl --user stop tool-*.socket
systemctl --user stop tool-*.service
podman stop $(podman ps -q --filter name=rag-tool)
```

## Solución de Problemas

### Problema: Los servicios arrancan automáticamente al inicio del sistema

**Causa:** Los archivos `.service` tienen `WantedBy=default.target` en la sección `[Install]`.

**Solución:**

```bash
cd tools
./fix-socket-activation.sh
```

Esto elimina la línea `WantedBy=default.target` de todos los servicios.

### Problema: El servicio no arranca cuando hago una petición

**Verificar:**

```bash
# 1. ¿Está el socket escuchando?
systemctl --user status tool-office.socket

# 2. ¿Hay errores en los logs?
journalctl --user -u tool-office.service -n 50

# 3. ¿Existe la imagen del contenedor?
podman images | grep rag-tool-office
```

**Solución común:**

```bash
# Reiniciar el socket
systemctl --user restart tool-office.socket

# O usar el script específico
./tools/restart-tool-office.sh
```

### Problema: El contenedor no arranca (permisos)

**Error típico:**

```
Error: /work: read-only file system
```

**Solución:**

Verificar que el directorio de caché existe y tiene permisos:

```bash
mkdir -p ~/.cache/rag-tools/{office,archive,ocr,gpu}
chmod 755 ~/.cache/rag-tools/*
```

### Problema: Timeout al iniciar

**Causa:** El contenedor tarda más de 90 segundos en arrancar.

**Solución temporal:**

Editar el archivo `.service` y aumentar `TimeoutStartSec`:

```ini
TimeoutStartSec=180  # Era 90
```

Luego:

```bash
systemctl --user daemon-reload
systemctl --user restart tool-office.socket
```

## Best Practices

### ✅ DO

- Usa `enable-tool-sockets.sh` para configurar todo
- Usa `restart-tool-*.sh` para reiniciar servicios individuales
- Verifica logs con `journalctl` cuando algo falle
- Usa `fix-socket-activation.sh` después de cambios

### ❌ DON'T

- NO ejecutes `systemctl --user enable tool-office.service` directamente
- NO agregues `WantedBy=default.target` a los archivos `.service`
- NO inicies servicios con `systemctl --user start tool-office.service` manualmente (déjalo al socket)
- NO edites archivos en `~/.config/systemd/user/` directamente (usa los scripts)

## Verificación Completa

Después de configurar todo, ejecuta:

```bash
# 1. Estado inicial
systemctl --user list-sockets | grep tool-
systemctl --user status tool-*.service

# 2. Debe mostrar:
# - Sockets: active (listening)
# - Services: inactive (dead)

# 3. Prueba activación
curl http://127.0.0.1:9102/healthz

# 4. Ahora debe mostrar:
systemctl --user status tool-office.service
# - Service: active (running)

podman ps | grep rag-tool-office
# - Contenedor corriendo
```

## Referencias

- [systemd Socket Activation](https://www.freedesktop.org/software/systemd/man/systemd.socket.html)
- [systemd-socket-proxyd](https://www.freedesktop.org/software/systemd/man/systemd-socket-proxyd.html)
- [Podman + systemd](https://docs.podman.io/en/latest/markdown/podman-systemd.unit.5.html)
