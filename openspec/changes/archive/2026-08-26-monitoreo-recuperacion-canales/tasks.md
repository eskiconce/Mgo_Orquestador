# Tasks — Recuperación automática de canales

## 1. Fix recuperación tsmonitor

- [x] 1.1 Corregir `services/vod_service.py:456` — cambiar `payload.numero_canal` por `payload.num_canal`. Verif: `grep numero_canal` no devuelve resultados; `python3 -c "import ast; ast.parse(open('services/vod_service.py').read())"` pasa.
- [x] 1.2 Mejorar lookup del canal en `services/vod_service.py:451-453` — intentar con `unique_id == str(num_canal)` y fallback con `Channel.id == num_canal`. Verif: probar alerta tsmonitor con `id` numérico y con `unique_id`; ambos localizan el canal.
- [x] 1.3 Validar que la rama de recuperación (`restore`/`ok`/`up`/`restored`/`live`) en `vod_service.py:525-549` envía `POST /jobs/create` con `autostart: true` y actualiza estado a `starting`. Verif: revisar que el flujo de recuperación está activo y sin campos inexistentes.

## 2. Recuperación tras reinicio del nodo (NODE_UP)

- [x] 2.1 En `monitor.py` NODE_UP handler, ampliar la consulta de jobs a relanzar: incluir estado `error` **y** `stopped` (actualmente solo `error`). Verif: `grep "status == \"error\""` actualizado; revisar que la query incluya ambos estados.
- [x] 2.2 Asegurar que al relanzar jobs en NODE_UP no se repongan canales detenidos intencionalmente: usar `auto_started` y un cooldown mínimo. Verif: canal `stopped` manualmente no se relanza; canal `stopped` por reinicio del nodo sí.

## 3. Reintento periódico en sync loop

- [x] 3.1 Agregar rama de reintento en el sync loop (`monitor.py` handler STOPPED/ERROR) para jobs en `error`/`stopped` cuyo nodo esté online, reintentando `start` cada N segundos. Verif: job en `error`/`stopped` con nodo online se reintenta; los intentos se registran en monitor log.

## 4. QA y despliegue

- [x] 4.1 Verificar sintaxis de `monitor.py` y `vod_service.py` con `ast.parse` local y en servidor. Verif: ambos comandos imprimen `OK`.
- [x] 4.2 Crear backup de `monitor.py` y `vod_service.py` en el servidor y en el repo local. Verif: archivos `.bak` con timestamp existen.
- [x] 4.3 Desplegar archivos modificados al servidor y reiniciar `encoder-monitor.service` + `encoder-api.service`. Verif: servicios activos (`systemctl status`).
- [x] 4.4 Bump versión en `core/version.py` y actualizar `CHANGELOG.md` (solo local, no servidor). Verif: versión nueva visible en frontend.

## 5. Archive

- [x] 5.1 Ejecutar `openspec archive monitoreo-recuperacion-canales` tras deploy exitoso. Verif: change movido a `openspec/changes/archive/`.
