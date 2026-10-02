# Mejoras al Front de Canales

## Why

Solicitud de operaciones (2026-10-01) sobre el formulario de alta/edición de canales (`templates/channel_form.html`):

1. El nombre del canal no puede llevar espacios (hoy sin validación en cliente ni servidor; placeholder incluso sugiere "TVN HD" con espacio).
2. El toggle DRM del formulario no debe existir: DRM solo aplica a los packagers. Hoy es UI muerta — `save_channel` nunca recibe `is_drm` y `Channel.is_drm` no se lee en ningún código; el DRM real vive en el formulario de procesos (`isDrmCheck` + scripts con DRM).
3. El Program ID debe ser igual al Número Canal MGO registrado en la creación. Hoy es un textbox manual en "Parámetros Avanzados de Buffer" con botón "Fijar Mapeo", y el escaneo lo sobrescribe con el programa detectado.
4. Al terminar el escaneo de una señal, los parámetros del perfil 1 quedan escritos en sus textboxes (comportamiento actual se conserva), pero el bitrate del perfil 1 debe quedar **estático en 4500k** — hoy se asigna 7000k/5000k/4000k según la resolución detectada.

## What Changes

- **M1** Validación de `channel_name` sin espacios: patrón `\S+` + mensaje en el formulario (placeholder pasa a `Ej: TVN_HD`); `save_channel` responde 400 si `channel_name` contiene espacios.
- **M2** Eliminar el switch DRM de `channel_form.html` (sección 1). No hay cambio en modelo ni backend (el campo ya no se enviaba); el DRM sigue disponible a nivel de proceso/packager en `process_form.html`.
- **M3** `program_id` derivado del Número Canal MGO (`unique_id`): se elimina el textbox de Program ID y el botón "Fijar Mapeo" (se muestra valor readonly sincronizado con `unique_id`); el escaneo deja de sobrescribir `program_id` (solo se muestra como informativo en el modal); `save_channel` fuerza `program_id = int(unique_id)` y valida que `unique_id` sea numérico (400 si no).
- **M4** Bitrate del perfil 1 con default `4500k`: tras el escaneo se asigna `4500k` (sustituye a la lógica por resolución 7000/5000/4000k); el textbox muestra `4500k` en alta (campo **editable** — es un parámetro base que puede cambiar); el hidden `bitrate_high_max` se empareja siempre a `bitrate_p1` (JS en el form + `bitrate_high_max = bitrate_p1` en `save_channel`) para mantener coherencia entre el bitrate que encodea ffmpeg y el ancho de banda que declara Shaka (`services/builders.py`). **No se fuerza** `bitrate_p1` en el servidor.

## Non-Goals

- No se modifica `channel_list.html` ni `channel_form` de jobs (`job_form.html`).
- No se migra en BD el `bitrate_p1` de canales existentes: se actualizará en el próximo guardado de cada canal.
- No se toca el DRM a nivel de proceso/packager (correcto actualmente).
- No se elimina la columna `channels.is_drm` (queda inerte por compatibilidad).

## Impact

- Affected specs: `channels-form` (nuevo en este change).
- Affected code: `templates/channel_form.html`, `routers/channels.py`, `tests/` (nuevas validaciones).
- Version: **v2.21.0** (MINOR — mejoras de UI/validación, sin breaking changes operativos; BD verificada: 0 canales con espacios, 0 `unique_id` no numéricos).
- Deploy: solo código a `172.16.223.5` + restart `encoder-monitor` + `encoder-api`.
- Issue: https://github.com/eskiconce/Mgo_Orquestador/issues/13
