# Change: analyzer-resolucion-bitrate-origen

**Issue:** https://github.com/eskiconce/Mgo_Orquestador/issues/17
**Fecha:** 2026-10-02
**Versión objetivo:** v2.22.3 (PATCH)
**Estado:** plan aprobado — pendiente de implementación

## Why

Cuando el origen detectado por `signal_analyzer.py` está por debajo de los perfiles 1080/720, los perfiles generados no quedan ajustados a la resolución real:

- **P2 secundario fijo en 640x360** para cualquier SD: igual al P1 si el origen es 640x360, o en **upscale** si el origen es 480x270/320x240
- **Bitrates no ajustados en SD**: BD (6500k/2500k pensados para HD) prevalecen sobre los sugeridos por resolución (2500/700)
- **Bug defensivo**: si ffprobe no reporta resolución → `resolution_p1 = "0x0"` → script con `scale=0:0` inválido

Regla de negocio aprobada: cualquier señal **bajo 720** → P1 nativa (par), P2 = 50% de P1 con tope 640x360, bitrates de ambos perfiles según lo detectado (SD: 2500k/700k), GOP siempre de BD, tiers ≥720 intactos.

## What Changes

- `scripts/signal_analyzer.py` → `generate_recommendations()` (líneas 491-511, lógica de tiers) y tramo de bitrates (517-536):
  - **Tier SD** (`width < 1280`): P1 = nativa redondeada a pares; P2 = `min(w/2, 640) x min(h/2, 360)` en pares (nunca upscale); bitrates **2500k/700k gobiernan sobre BD** con reason explícito
  - **Defensa**: `width/height` ≤ 0 → fallback tier 1280x720 + rec de warning (nunca `0x0`)
  - Tiers `width ≥ 1920` y `≥ 1280`: sin cambio (prioridad BD, fallback sugerido)
  - GOP: sin cambios en todos los tiers
- Tests unitarios nuevos `tests/test_signal_analyzer_recs.py` (función pura, análisis falsos)

## Impact

- Afectados: `scripts/signal_analyzer.py` (orquestador), tests
- Sin cambios: UI, BD, builders, `generate_encoder_script` (ya consume recs vía `resolution_p1/p4` y `bitrate_p1/p4`), audio, GOP
- **Copia fuente:** orquestador `scripts/` (1083 líneas = la desplegada en los encoders); copias en `Api_agent-mac|linux` (1026, stale) quedan fuera de alcance
- Deploy posterior: orquestador + copia del archivo a encoders (mac_05, mac_02, encoder_02, encoder_03; mac_01 con auth SSH pendiente)
