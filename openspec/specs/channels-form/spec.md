# channels-form Specification

## Purpose
TBD - created by archiving change mejoras-front-canales. Update Purpose after archive.

## Requirements

### Requirement: nombre de canal sin espacios

El nombre del canal (`channel_name`) SHALL rechazar cualquier espacio en blanco, tanto en el formulario (validación en cliente) como en `POST /ui/channels/save` (validación en servidor con HTTP 400).

#### Scenario: creación con espacio en el nombre
- WHEN el usuario envía el formulario con `channel_name = "TVN HD"`
- THEN el formulario muestra un mensaje de validación y no envía; si la petición llega al servidor, `save_channel` responde 400 y no guarda

#### Scenario: nombre sin espacios
- WHEN el usuario envía `channel_name = "TVN_HD"`
- THEN el canal se guarda normalmente

#### Scenario: espacios al inicio o final
- WHEN `channel_name = " TVN_HD "`
- THEN se responde 400 (el nombre no puede contener espacios)

#### Scenario: placeholder de ayuda
- WHEN se renderiza el formulario en alta
- THEN el placeholder del nombre sugiere un valor sin espacios (ej. `Ej: TVN_HD`)

### Requirement: toggle DRM eliminado del formulario de canales

El formulario de alta/edición de canales NO SHALL renderizar el switch DRM. La funcionalidad DRM a nivel de proceso/packager permanece en `process_form.html`.

#### Scenario: alta de canal
- WHEN se renderiza `/ui/channels/new`
- THEN no existe el switch DRM en la sección de Identificación

#### Scenario: edición de canal
- WHEN se renderiza `/ui/channels/edit/{id}`
- THEN no existe el switch DRM y el guardado no requiere el campo `is_drm`

### Requirement: program_id derivado del Número Canal MGO

`program_id` SHALL ser igual al `unique_id` (Número Canal MGO) en todo guardado. El formulario NO SHALL permitir editar `program_id` manualmente ni el escaneo SHALL sobrescribirlo. `unique_id` SHALL ser numérico.

#### Scenario: creación de canal
- WHEN se guarda un canal con `unique_id = "100"`
- THEN `program_id` queda en `100` en BD, sin importar el valor del formulario

#### Scenario: edición de canal
- WHEN se edita un canal y se cambia `unique_id` de "100" a "250"
- THEN `program_id` queda en `250`

#### Scenario: unique_id no numérico
- WHEN `unique_id = "ABC"`
- THEN `save_channel` responde 400 y no guarda

#### Scenario: formulario muestra el valor derivado
- WHEN el usuario escribe o carga el Número Canal MGO
- THEN el campo Program ID (readonly) se actualiza en vivo con ese valor

#### Scenario: escaneo no sobrescribe program_id
- WHEN el escaneo detecta un programa con `program_id = 5`
- THEN el campo Program ID sigue mostrando el valor derivado del Número Canal MGO (el detectado solo aparece como informativo en el modal)

### Requirement: bitrate del perfil 1 con default 4500k

`bitrate_p1` SHALL mostrar `4500k` como valor por defecto en alta, y el escaneo SHALL asignar `4500k` (no valores derivados de la resolución). El campo es **editable** (parámetro base que puede cambiar) y `save_channel` SHALL guardar el valor enviado. `bitrate_high_max` SHALL emparejarse siempre con `bitrate_p1` (JS en el form + al guardar) para mantener coherencia entre el encode de ffmpeg y el ancho de banda declarado a Shaka.

#### Scenario: canal nuevo sin escanear
- WHEN se renderiza el formulario en alta
- THEN el bitrate del perfil 1 muestra `4500k` y es editable

#### Scenario: escaneo de señal 1080p
- WHEN el escaneo termina con video 1920x1080
- THEN la resolución del perfil 1 se auto-rellena (1920x1080) y el bitrate queda en `4500k` (no 7000k)

#### Scenario: escaneo de señal 720p
- WHEN el escaneo termina con video 1280x720
- THEN la resolución del perfil 1 se auto-rellena (1280x720) y el bitrate queda en `4500k` (no 5000k)

#### Scenario: el operador cambia el bitrate
- WHEN el usuario edita `bitrate_p1` a `6000k` y guarda
- THEN la BD queda con `bitrate_p1 = "6000k"` y `bitrate_high_max = "6000k"` (emparejado)

#### Scenario: high_max no se envía en pareja
- WHEN el formulario envía `bitrate_p1 = "5500k"` y `bitrate_high_max` con otro valor
- THEN `save_channel` guarda `bitrate_p1 = "5500k"` y `bitrate_high_max = "5500k"` (siempre igual a `bitrate_p1`)

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
