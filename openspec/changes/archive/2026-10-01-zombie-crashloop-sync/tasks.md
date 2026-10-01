# Tasks

## Fase A — Orquestador/Monitor (hoy)

- [x] 1. Issue GitHub #12 + cambio OpenSpec (proposal, specs, tasks)
- [x] 2. A0 — 5 units systemd en encoder_03: `stop` + `disable` verificados (inactivas)
- [x] 3. A1 — `stop_job` honesto: sin `except: pass`, HTTP != 200 o error de red → 502, job NO marcado `stopped`
- [x]] 4. A2 — anti-zombie efímero: uptime < 30s → `ZOMBIE_UNSTABLE` + `error` (sin adoptar), guard en `PROCESS_SYNCED`, adopción solo con 30s continuos
- [x]] 5. A3 — rate-limit CMS 10 min por (canal, evento) con `cms.rate_limit_sec` en app_settings
- [x]] 6. A4 — dedupe `ZOMBIE_DETECTED` 5 min por job (consola + BD)
- [x]] 7. A5 — `log_monitor_event` sin commit propio + commits explícitos en paths que perderían eventos
- [x]] 8. A6 — eventos `CMS_{STATUS}` hacia `monitor_logs` cuando el webhook se envía
- [x]] 9. A7 — timestamp consola/BD idéntico (truncar µs; CMS usa el mismo instante)
- [x]] 10. A8 — dropdown `/ui/monitor-logs` con todos los tipos de evento + badges
- [x]] 11. A9 — tests (stop_job 502, rate-limit CMS, log sin commit propio, zombie inestable) + v2.20.0 + CHANGELOG + docs/monitor-zombie-crashloop.md
- [x]] 12. A10 — push GitHub + deploy solo de código + restart `encoder-monitor` + `encoder-api` + verificación

## Fase B — Api_agent-linux (mañana)

- [x] 13. B1 — `StartLimitIntervalSec=60` + `StartLimitBurst=3` en `/jobs/create`
- [x] 14. B2 — stop verificado en `/jobs/control`
- [x] 15. B3 — mapeo `failed→FATAL`, `activating(auto-restart)→BACKOFF` en `/jobs/status`
- [x] 16. B4 — docs + CHANGELOG Api_agent-linux
- [x] 17. B5 — deploy agente + verificación

## Cierre

- [x] 18. QA — verificar completitud de specs
- [x] 19. `openspec archive zombie-crashloop-sync` + cierre issue #12 (tras Fase B)
