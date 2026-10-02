# Tasks

## Preparación

- [x] 1. Issue GitHub #14 + cambio OpenSpec `mejoras-escaneo-streams` (proposal, spec, tasks) + aprobación del plan por el usuario

## Implementación

- [x] 2. M1 — Modal `channel_form.html`: numeración `Stream #` por tipo desde #0 (video, audio, subtítulos), conservando el PID MPEG real informativo
- [x] 3. M2 — `subtitle_pid` relativo: radio `value` = ordinal por tipo, auto-fill tras escaneo ordinal (no global), placeholder `Ej: 0`
- [x] 4. M3 — Verificación: suite completa en verde (`python3 -m pytest tests/ -q`) — regresión, sin cambios backend

## Versionado y documentación

- [x] 5. Bump **v2.22.0** (MINOR) + entrada en `CHANGELOG.md` + docs si aplica

## Deploy y verificación

- [x] 6. Push a GitHub (fuente principal)
- [x] 7. Deploy solo `channel_form.html` + `version.py` a `172.16.223.5` + restart `encoder-monitor` + `encoder-api` + verificar servicios activos
- [x] 8. QA manual del modal: numeración por tipo desde #0 (video/audio/subs), selección de subtítulo → `subtitle_pid` relativo (1er sub = 0), auto-fill tras escaneo = ordinal, placeholder `Ej: 0`

## Cierre

- [x] 9. `openspec archive mejoras-escaneo-streams` + comentario y cierre del issue #14 tras deploy exitoso

## Fuera de alcance (deferido a otra sesión)

- `/api/analyze-source` (`routers/channels.py`) — envío de `r_frame_rate`, `field_order` y campos extra (FPS no visible / "Progresivo" siempre) → issue separado
- `services/builders.py` — interpretación de `subtitle_pid` como `0:{N}` (global) → `0:s:{N}` (relativo) en `generate_linux_encoder_bash`/`generate_mac_encoder_bash` → revisión en otra sesión. ⚠️ Hasta entonces, valores relativos nuevos se interpretarán como índice global en el script generado
- Migración BD de los 3 canales con burn activo (`MyZentv=11`, `Sony_Channel=7`, `Discovery_Theater=3`) → revisión manual en otra sesión
- Agents respetando `subtitle_pid` del payload → issue separado
