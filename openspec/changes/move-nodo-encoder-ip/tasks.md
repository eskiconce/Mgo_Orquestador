# Tasks

## Preparación

- [ ] 1. Issue GitHub #15 + cambio OpenSpec `move-nodo-encoder-ip` (proposal, spec, tasks) + aprobación del plan por el usuario

## Implementación

- [ ] 2. M1 — `routers/processes.py::move_job`: parcheo de `job.command` con `new_node.ip_multicast` cuando `new_node.tipo == 'Encoder'` (re.sub `LOCADDRESS = "..."` y `localaddr=<IP literal>`; defensivo con `command` vacío o `ip_multicast` None)
- [ ] 3. M2 — Tests `tests/test_move_job_ip.py`: move encoder → parchea `LOCADDRESS` (Linux) y `localaddr=` inline ×3 (Mac); referencia `localaddr={LOCADDRESS}` intacta; move packager → sin cambios; defensivo sin valores → sin error; suite completa en verde (`python3 -m pytest tests/ -q`)

## Versionado y documentación

- [ ] 4. Bump **v2.22.1** (PATCH) + entrada en `CHANGELOG.md`

## Deploy y verificación

- [ ] 5. Push a GitHub (fuente principal)
- [ ] 6. Deploy solo `routers/processes.py` + `core/version.py` a `172.16.223.5` + restart `encoder-monitor` + `encoder-api` + verificar servicios activos
- [ ] 7. QA manual: mover un Encoder a otro nodo → `job.command` en BD con la IP del nodo destino (ambos patrones según tipo de script); proceso inicia correcto

## Cierre

- [ ] 8. `openspec archive move-nodo-encoder-ip` + comentario y cierre del issue #15 tras deploy exitoso

## Fuera de alcance (deferido)

- Mover Packager (`INTERFACE="..."`) → issue/revisiones separadas
- Regeneración completa del script en el move (se preservan ediciones manuales)
- Validación/parcheo en `start-job`
- UI del modal de move
