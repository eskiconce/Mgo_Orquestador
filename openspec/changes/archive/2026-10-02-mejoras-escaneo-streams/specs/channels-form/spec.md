# Channels Form

## ADDED Requirements

### Requirement: numeración de streams por tipo desde cero

El modal de escaneo SHALL numerar `Stream #` con el ordinal del stream **dentro de su tipo** (video, audio, subtítulos), empezando en 0 en cada grupo, consistente con los values que se envían. El PID MPEG real (`s.id`) SHALL mostrarse informativo junto al número.

#### Scenario: entrada con 1 video, 3 audio, 2 subtítulos (índices globales 0-5)
- WHEN se abre el modal con esos streams
- THEN video muestra "Stream #0"; audio muestra "Stream #0", "#1", "#2"; subtítulos muestran "Stream #0" y "Stream #1"

#### Scenario: display y value de audio coinciden
- WHEN se selecciona el segundo stream de audio
- THEN la etiqueta muestra "Stream #1" y el checkbox envía `0:a:1`

#### Scenario: PID real se conserva
- WHEN se muestra un stream
- THEN junto al número por tipo se muestra el PID MPEG real (`s.id`) informativo

### Requirement: `subtitle_pid` como ordinal de subtítulo

El campo `subtitle_pid` SHALL recibir el ordinal (desde 0) del stream de subtítulo seleccionado **dentro del listado de subtítulos**, no el índice global ffprobe. El auto-fill posterior al escaneo SHALL usar el mismo criterio.

#### Scenario: primer subtítulo seleccionado
- WHEN el subtítulo con índice global ffprobe 7 (el primero del tipo) está seleccionado
- THEN `subtitle_pid = 0`

#### Scenario: segundo subtítulo seleccionado
- WHEN se selecciona el segundo subtítulo del listado
- THEN `subtitle_pid = 1`

#### Scenario: auto-fill tras escaneo
- WHEN el escaneo detecta subtítulos y auto-rellena el campo
- THEN se asigna el ordinal del primer subtítulo (0), no su índice global

#### Scenario: placeholder del campo
- WHEN se renderiza el formulario
- THEN el placeholder de `subtitle_pid` sugiere un ordinal por tipo (ej. `Ej: 0`)
