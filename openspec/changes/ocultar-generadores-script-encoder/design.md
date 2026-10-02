# Design — ocultar-generadores-script-encoder

**Aprobado por usuario:** 2026-10-02 (enfoque A)

## Enfoque elegido

Ocultar con clase **`d-none`** (Bootstrap) los botones de generar/regenerar scripts de encoder, en lugar de comentar o borrar el HTML.

**Por qué:** coherente con "por ahora" (reversible quitando la clase), cero cambios JS (los elementos siguen en el DOM, los `getElementById` no rompen), diff mínimo.

**Descartado:**
- Comentar HTML (`<!-- -->`) → diff más ruido, revertir más frágil
- Borrar botones + limpiar JS → no reversible fácilmente, siendo temporal

## Cambios concretos

### `templates/process_form.html` (Crear Proceso)

Línea 33-40, sección `autoBuildSection`:

```html
<button id="btnAutoBuild" ... class="btn btn-outline-dark fw-bold d-none">   <!-- + d-none -->
<button id="btnAutoBuildLinux" ... class="btn btn-outline-primary fw-bold d-none">  <!-- + d-none -->
<div class="vr mx-2 d-none"></div>   <!-- + d-none (divider) -->
```

### `templates/process_list.html` (modal editCommandModal)

Línea 361-369, sección `modalEncoderGenerators`:

```html
<button id="modalBtnEncoderMac" ... class="btn btn-sm btn-outline-dark fw-bold d-none">   <!-- + d-none -->
<button id="modalBtnEncoderLinux" ... class="btn btn-sm btn-outline-primary fw-bold d-none">  <!-- + d-none -->
<div class="vr mx-2 d-none"></div>   <!-- + d-none (divider) -->
```

## Queda visible

- `Analizar Señal` + selector de duración (1/2/5/10 min) + barra de progreso + polling (intactos)
- Botones packager: Generar Script (Normal) y (DRM)

## Sin cambios

- Funciones JS `buildEncoderScriptMac/Linux`, `rebuildModalEncoderMac/Linux` — intactas (reutilizables al reactivar)
- Backend (`/orchestrator/encoder/analyze`, builders, packager/build)
- BD

## Verificación

- Smoke test pytest: lee los 2 templates, exige `d-none` en los 4 botones (guard anti-regresión)
- QA visual tras deploy: Crear Proceso y modal Editar muestran solo Analizar Señal; packager sin cambios
