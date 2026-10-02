# Processes Form / Generadores Encoder (ocultos)

## ADDED Requirements

### Requirement: La UI de Procesos no muestra los botones de generar/regenerar scripts de encoder

La pantalla de Crear Proceso (`/ui/processes/new`, `templates/process_form.html`) y el modal de Editar Script (`editCommandModal`, `templates/process_list.html`) SHALL ocultar los botones de generar/regenerar scripts de encoder Mac/GPU y Linux/CPU con la clase `d-none`, dejando visible únicamente el flujo de **Analizar Señal** en esa sección.

#### Scenario: Crear Proceso sin generadores de encoder
- WHEN el operador abre `/ui/processes/new` y selecciona canal + nodo encoder (sección `autoBuildSection` visible)
- THEN los botones "Generar Script (Mac/GPU)" y "Generar Script (Linux/CPU)" NO están visibles
- AND el botón "Analizar Señal", su selector de duración y la barra de progreso SÍ están visibles y funcionales

#### Scenario: Editar proceso encoder sin regeneradores
- WHEN el operador abre el modal "Editar Script de Ejecución" para un job Encoder
- THEN los botones "Regenerar Script (Mac/GPU)" y "Regenerar Script (Linux/CPU)" NO están visibles
- AND el botón "Analizar Señal" SÍ está visible y funcional

#### Scenario: Dividers de separación ocultos
- WHEN los botones de generador están ocultos
- THEN los dividers verticales `vr` que los separaban de "Analizar Señal" también están ocultos (sin líneas separadoras huérfanas)

#### Scenario: Packager sin cambios
- WHEN el operador abre Crear Proceso en modo packager o el modal de edición de un job Packager
- THEN los botones "Generar Script (Normal)" y "Generar Script (DRM)" permanecen visibles (fuera de alcance de este cambio)

#### Scenario: Reversible
- WHEN se requiere reactivar los generadores en el futuro
- THEN basta con quitar la clase `d-none` de los 4 botones (sin reintroducir HTML ni JS)

#### Scenario: Smoke test anti-regresión
- WHEN se ejecuta `python3 -m pytest tests/ -q`
- THEN un test verifica que los 4 botones en los 2 templates contienen la clase `d-none`
