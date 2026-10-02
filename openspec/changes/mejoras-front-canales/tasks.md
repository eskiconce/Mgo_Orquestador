# Tasks

## Preparación

- [x] 1. Issue GitHub #13 + cambio OpenSpec (proposal, specs, tasks) + aprobación del plan por el usuario

## Implementación

- [x] 2. M1 — Nombre sin espacios: JS en `channel_form.html` (validación al enviar + placeholder `Ej: TVN_HD`) y validación 400 en `routers/channels.py::save_channel`
- [x] 3. M2 — Eliminar switch DRM de `channel_form.html` (sección 1, bloque `chIsDrm`)
- [x] 4. M3 — Program ID derivado: quitar textbox + "Fijar Mapeo", valor readonly sincronizado con `unique_id`; JS de escaneo deja de escribir `program_id` (líneas ~379 y ~565) y se elimina `useDetectedProgram()`; `save_channel` fuerza `program_id = int(unique_id)` y valida `unique_id` numérico (400)
- [x] 5. M4 — Bitrate perfil 1 default 4500k (editable): tras escaneo asignar `4500k` a `bitrate_p1` (reemplaza lógica 7000/5000/4000k por resolución); default del form en alta `4500k`; `bitrate_high_max` emparejado a `bitrate_p1` (JS en el form + `save_channel` guarda `bitrate_high_max = bitrate_p1`); sin forzar `bitrate_p1`
- [x] 6. Tests: `tests/` — nombre con espacios → 400; `unique_id` no numérico → 400; `program_id` derivado de `unique_id`; `bitrate_p1` editable guardado como enviado + `bitrate_high_max` emparejado; suite completa en verde

## Versionado y documentación

- [x] 7. Bump **v2.21.0** (MINOR) + entrada en `CHANGELOG.md` + `README`/docs si aplica

## Deploy y verificación

- [ ] 8. Push a GitHub (fuente principal)
- [ ] 9. Deploy solo código a `172.16.223.5` + restart `encoder-monitor` + `encoder-api` + verificar servicios activos
- [ ] 10. QA manual en UI: alta de canal (espacios rechazados, program_id = unique_id, bitrate 4500k editable, sin switch DRM), escaneo (resolución auto-rellenada + bitrate 4500k + program_id intacto), edición (mismos comportamientos)

## Cierre

- [ ] 11. `openspec archive mejoras-front-canales` + cierre del issue tras deploy exitoso
