# Signal Analyzer / Resolución y bitrate según origen

## ADDED Requirements

### Requirement: Los perfiles P1/P2 y sus bitrates se ajustan a la resolución detectada cuando el origen está por debajo de 720

`generate_recommendations()` SHALL clasificar el origen detectado en tiers y, para orígenes SD (bajo 720), generar perfiles ajustados a la resolución real con bitrates propios del tier, manteniendo el GOP de BD.

#### Scenario: origen SD 640x360
- WHEN el análisis detecta `width=640, height=360` y la BD trae `bitrate_p1=6500` y `bitrate_p4=2500`
- THEN `resolution_p1 = "640x360"` y `resolution_p4 = "320x180"` (50% en pares, ≤640x360)
- AND `bitrate_p1 = 2500` y `bitrate_p4 = 700` (los valores detectados gobiernan sobre BD, con reason explícito)
- AND `gop` = valor de BD (sin cambios)

#### Scenario: origen SD 720x576 (PAL)
- WHEN el análisis detecta `width=720, height=576`
- THEN `resolution_p1 = "720x576"` y `resolution_p4 = "360x288"` (ambas en pares)

#### Scenario: origen SD sin upscale en P2
- WHEN el análisis detecta `width=480, height=270`
- THEN `resolution_p1 = "480x270"` y `resolution_p4 = "240x134"` (par redondeado, nunca mayor que P1)

#### Scenario: resolución no detectada (defensa)
- WHEN el análisis trae `width=0` o `height=0` ausentes/invalidos
- THEN las recs usan fallback `1280x720` / `852x480` con un warning, y NUNCA se produce `resolution_p1 = "0x0"`

#### Scenario: origen HD intacto (regresión)
- WHEN el análisis detecta `width=1920, height=1080` con `bitrate_p1=5000` de BD
- THEN `resolution_p1 = "1920x1080"`, `resolution_p4 = "852x480"` y `bitrate_p1 = 5000` (prioridad BD conservada)

#### Scenario: origen 720 intacto (regresión)
- WHEN el análisis detecta `width=1280, height=720` con `bitrate_p1=4000` de BD
- THEN `resolution_p1 = "1280x720"` y `bitrate_p1 = 4000` (prioridad BD conservada)

#### Scenario: GOP siempre de BD
- WHEN se genera cualquier tier (SD, 720, 1080)
- THEN el rec `gop` = `gop_p1` recibido de BD (nunca derivado de la resolución)

#### Scenario: bufsize deriva del bitrate final
- WHEN el bitrate final de un perfil cambia (por override SD o por BD)
- THEN `bufsize` de ese perfil = 2 × bitrate final

#### Scenario: suite completa
- WHEN se ejecuta `python3 -m pytest tests/ -q`
- THEN los tests del módulo pasan y no se rompen los tests existentes
