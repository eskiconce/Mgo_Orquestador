# Design — analyzer-resolucion-bitrate-origen

**Aprobado por usuario:** 2026-10-02

## Ubicación única

`scripts/signal_analyzer.py` → `generate_recommendations(analysis, gop_p1, audio_mapping, bitrate_p4, bitrate_p1, fps_target)` — tramo de resolución (líneas 491-511) y tramo de bitrates (517-536).

## 1. Clasificación de tiers (defensiva)

```python
width = int(video.get("width") or 0)
height = int(video.get("height") or 0)

if width <= 0 or height <= 0:
    # fallback: tier 720p + warning, nunca "0x0"
    resolution_p1, resolution_p4 = "1280x720", "852x480"
    rec warning "Resolución de origen no detectada - fallback 1280x720"
elif width >= 1920:
    resolution_p1, resolution_p4 = "1920x1080", "852x480"      # sin cambio
elif width >= 1280:
    resolution_p1, resolution_p4 = "1280x720", "852x480"       # sin cambio
else:  # SD — cualquier señal bajo 720
    p1_w, p1_h = even(width), even(height)                     # nativa, pares
    resolution_p1 = f"{p1_w}x{p1_h}"
    resolution_p4 = f"{min(p1_w // 2, 640)}x{min(p1_h // 2, 360)}"   # 50%, tope 640x360
```

`even(x)` = `x - (x % 2)` → nunca dimensiones impares (rompen yuv420p).
P2 ≤ P1 siempre → sin upscale. Ejemplos: 720x576→360x288, 640x360→320x180, 480x270→240x134.

## 2. Bitrates por tier

| Tier | suggested_p1 | suggested_p4 | Prioridad |
|---|---|---|---|
| 1920+ | 4500 | 1200 | BD primero (sin cambio) |
| 1280+ | 4000 | 1200 | BD primero (sin cambio) |
| **SD** | **2500** | **700** | **Detección primero: override de BD en ambos perfiles** |

- SD: si `bitrate_p1` (BD) viene, se **ignora** y se usa 2500k; `bitrate_p4` BD (2500k) se **ignora** y se usa 700k. Reason explícito en la rec: `Bitrate SD ajustado a origen detectado {w}x{h} (BD: {bd}k ignorado)`
- `bufsize = 2x bitrate` (líneas 533-536) se recalcula automáticamente sobre los valores finales
- **GOP**: sin cambios — `gop_p1` de BD se registra igual en todos los tiers (línea 489)

## 3. Sin cambios (confirmado)

- Tiers ≥720 (prioridad BD, fallback sugerido) — comportamiento actual
- `generate_encoder_script` ya consume las recs (`resolution_p1/p4`, `bitrate_p1/p4`, `bufsize_*`) → wiring existente, cero cambios ahí
- Clasificación sigue por `width` (1440x1080 mantiene tier 720 actual) — fuera de alcance
- Audio, fps, deinterlacing, subtítulos

## 4. Tests

`tests/test_signal_analyzer_recs.py` — importar módulo vía `importlib.util.spec_from_file_location` (scripts/ no es package), función pura:

- SD 640x360 → P1 `640x360`, P2 `320x180`, bitrate_p1=2500 aunque BD=6500, bitrate_p4=700 aunque BD=2500, gop=BD
- SD 720x576 → P2 `360x288` (pares)
- SD 480x270 → P1 `480x270`, P2 `240x134` (par, sin upscale)
- `width=0` / `height=0` → fallback `1280x720`/`852x480`, rec de warning, nunca `0x0`
- 1920x1080 → P1 `1920x1080`, P2 `852x480`, bitrate_p1=BD (prioridad BD intacta)
- 1280x720 → P1 `1280x720`, bitrate_p1=BD
- GOP siempre = `gop_p1` pasado en todos los tiers
- bufsize = 2x bitrate final
- Suite completa en verde

## 5. Versionado y deploy (ver tasks)

v2.22.3 (PATCH) + CHANGELOG → push → deploy orquestador (`scripts/signal_analyzer.py` + `core/version.py`) + copiar archivo a encoders → QA `--generate-only` SD → archive → cierre issue #17.
