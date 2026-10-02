# Escaneo de Canales: numeración de streams por tipo y subtítulo PID relativo

## Why

Issue #14 (diagnóstico completo 2026-10-02) sobre el modal de escaneo del formulario de canales:

1. **Numeración global vs. por tipo**: el modal agrupa los streams por tipo (Video / Audio / Subtítulos) pero numera con el índice global ffprobe (video=0, audio=1..6, subs=7..11):
   - Audio **muestra** global pero **envía** por tipo (`0:a:i`) → mismatch visible.
   - El radio de subtítulos envía el **índice global** a `subtitle_pid` (1er sub → 7) — inconsistente con `audio_mapping` (`0:a:0`) y con los defaults de los agents (`0:s:0` / 1er sub español).
   - El auto-fill tras escaneo (`channel_form.html:374`) también asigna el índice global.

## What Changes

- **M1 Frontend** `templates/channel_form.html` (modal de escaneo):
  - Numerar `Stream #` con el ordinal **dentro de su tipo** desde #0 (video, audio, subtítulos) — display consistente con los values enviados (PID MPEG real se conserva como informativo).
- **M2 `subtitle_pid` relativo**: radio con `value` = ordinal por tipo (desde 0), auto-fill tras escaneo con el mismo criterio, placeholder `Ej: 0`.
- **M3 Tests / verificación**: suite completa en verde (regresión, sin cambios backend); QA manual del modal.

## Non-Goals

- **`/api/analyze-source` fuera de alcance**: `routers/channels.py` NO se modifica. El envío de campos extra (`r_frame_rate`, `field_order`, perfil, etc. — bug de FPS no visible y "Progresivo" siempre) queda **deferido a un issue separado**.
- **`services/builders.py` fuera de alcance**: la interpretación de `subtitle_pid` como `0:{N}` (índice global) en `generate_linux_encoder_bash`/`generate_mac_encoder_bash` **se revisa en otra sesión**. ⚠️ Consecuencia conocida: hasta ese ajuste, un `subtitle_pid` relativo nuevo (0, 1, …) se interpretará como índice global en el script generado — el quemado con selección nueva queda pendiente de ese cambio diferido.
- **Sin migración en BD**: los 3 canales con burn activo (`MyZentv=11`, `Sony_Channel=7`, `Discovery_Theater=3`, valores globales) se revisan **manualmente en otra sesión** (re-escaneo y re-selección en el UI).
- Los agents (Api_agent-mac / Api_agent-linux) **no** passan a respetar `subtitle_pid` del payload (siguen eligiendo 1er subtítulo español / `0:s:0`) — issue separado si se requiere.
- No se modifica `signal_analyzer.py` ni ningún código de los agents.
- No se cambia `audio_mapping` (ya es por tipo).
- No se modifica el modelo `Channel` ni el esquema BD.

## Impact

- Affected specs: `channels-form` (requisitos ADDED en este change).
- Affected code: `templates/channel_form.html`, `tests/` (regresión).
- Version: **v2.22.0** (MINOR — mejoras de UI de escaneo sin cambios backend).
- Deploy: solo `channel_form.html` + `version.py` a `172.16.223.5` + restart `encoder-monitor` + `encoder-api`.
- Issue: https://github.com/eskiconce/Mgo_Orquestador/issues/14
