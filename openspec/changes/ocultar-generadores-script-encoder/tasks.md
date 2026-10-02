# Tasks

## Preparación

- [x] 1. Issue GitHub #16 + cambio OpenSpec `ocultar-generadores-script-encoder` (proposal, spec, tasks) + diseño aprobado por el usuario (enfoque A: `d-none`)

## Implementación (pendiente — NO ejecutar aún)

- [ ] 2. `templates/process_form.html`: agregar `d-none` a `btnAutoBuild` (línea 34), `btnAutoBuildLinux` (línea 37) y divider `vr` (línea 40)
- [ ] 3. `templates/process_list.html`: agregar `d-none` a `modalBtnEncoderMac` (línea 363), `modalBtnEncoderLinux` (línea 366) y divider `vr` (línea 369)
- [ ] 4. Smoke test `tests/test_ui_generadores_ocultos.py`: leer los 2 templates y exigir `d-none` en los 4 botones; suite completa en verde (`python3 -m pytest tests/ -q`)

## Versionado y documentación

- [ ] 5. Bump **v2.22.4** (PATCH) en `core/version.py` + entrada en `CHANGELOG.md`

## Deploy y verificación

- [ ] 6. Push a GitHub (fuente principal)
- [ ] 7. Deploy solo `templates/process_form.html` + `templates/process_list.html` + `core/version.py` a `172.16.223.5` + restart `encoder-monitor` + `encoder-api` + verificar servicios activos
- [ ] 8. QA visual: Crear Proceso y modal Editar muestran solo Analizar Señal; packager Normal/DRM visibles; Analizar funcional

## Cierre

- [ ] 9. `openspec archive ocultar-generadores-script-encoder` + comentario y cierre del issue #16 tras deploy exitoso

## Fuera de alcance (deferido)

- Botones de packager (Normal/DRM) — permanecen visibles
- Borrar/limpiar funciones JS de generación (`buildEncoderScript*`, `rebuildModalEncoder*`) — se conservan para reactivación futura
- Backend / builders / lógica de generación de scripts
