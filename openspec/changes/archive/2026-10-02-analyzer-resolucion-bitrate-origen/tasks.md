# Tasks

## Preparación

- [x] 1. Issue GitHub #17 + cambio OpenSpec `analyzer-resolucion-bitrate-origen` (proposal, spec, design, tasks) + diseño aprobado por el usuario

## Implementación

- [x] 2. `scripts/signal_analyzer.py::generate_recommendations()`: tiers defensivos — fallback `width/height ≤ 0` → 1280x720 + warning (nunca `0x0`); tier SD (`width < 1280`) → P1 nativa en pares, P2 = `min(w/2,640) x min(h/2,360)` en pares
- [x] 3. Mismo método: bitrates SD → `bitrate_p1=2500`, `bitrate_p4=700` **gobiernan sobre BD** (override con reason explícito); tiers ≥720 y GOP sin cambios; verificar que `bufsize` (533-536) usa los valores finales
- [x] 4. Tests `tests/test_signal_analyzer_recs.py` (importlib, análisis falsos): SD 640x360, 720x576, 480x270, `width=0`, regresiones HD/720 con prioridad BD, GOP BD en todos los tiers, bufsize=2x; suite completa en verde

## Versionado y documentación

- [x] 5. Bump **v2.22.3** (PATCH) en `core/version.py` + entrada en `CHANGELOG.md`

## Deploy y verificación

- [x] 6. Push a GitHub (fuente principal)
- [x] 7. Deploy orquestador: `scripts/signal_analyzer.py` + `core/version.py` → `172.16.223.5` + restart `encoder-monitor` + `encoder-api` + verificar activos
- [x] 8. Copiar `signal_analyzer.py` corregido a encoders: mac_05 `172.16.222.155`, mac_02 `172.16.223.8`, encoder_02 `172.16.222.233`, encoder_03 `172.16.222.235` (mac_01 `172.16.223.10` pendiente — auth SSH rechazada)
- [x] 9. QA: `--generate-only` con análisis SD real → script con P1 nativa, P2 escalonado, bitrates 2500/700, `scale=` correcto; QA regresión con señal HD existente

## Cierre

- [x] 10. `openspec archive analyzer-resolucion-bitrate-origen` + comentario y cierre del issue #17 tras deploy exitoso

## Fuera de alcance (deferido)

- Sincronizar copias stale de `Api_agent-mac|linux` `scripts/signal_analyzer.py` (1026 líneas, drift pre-existente vs 1083 del orquestador)
- Clasificación por `height` (1440x1080 mantiene tier actual)
- UI / BD / audio / GOP
- mac_01 (172.16.223.10): resolver auth SSH para deploy
