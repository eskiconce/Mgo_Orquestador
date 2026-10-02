# Change: ocultar-generadores-script-encoder

**Issue:** https://github.com/eskiconce/Mgo_Orquestador/issues/16
**Fecha:** 2026-10-02
**Versión objetivo:** v2.22.2 (PATCH)
**Estado:** plan aprobado — pendiente de implementación

## Why

En el menú Procesos, al crear o editar procesos se muestran los botones de generar/regenerar scripts de encoder (Mac/GPU y Linux/CPU). Por decisión operativa, **por ahora no deben mostrarse**: el flujo solo debe partir desde **Analizar Señal**. Los scripts de encoder se gestionan por otros medios y la generación directa desde la UI queda suspendida de forma reversible.

## What Changes

- **Crear Proceso** (`templates/process_form.html`): ocultar `btnAutoBuild` (Generar Script Mac/GPU, línea 34), `btnAutoBuildLinux` (Generar Script Linux/CPU, línea 37) y el divider `vr` (línea 40)
- **Editar — modal `editCommandModal`** (`templates/process_list.html`): ocultar `modalBtnEncoderMac` (Regenerar Script Mac/GPU, línea 363), `modalBtnEncoderLinux` (Regenerar Script Linux/CPU, línea 366) y el divider `vr` (línea 369)
- Mecanismo: clase `d-none` en cada elemento (enfoque A aprobado: reversible, cero cambios JS, diff mínimo)
- Smoke test pytest que exija `d-none` en los 4 botones (guard anti-regresión)

## Impact

- Afectados: UI de Procesos (2 templates), tests
- **Sin cambios:** botones de packager (Generar Normal/DRM), funciones JS `buildEncoderScript*` / `rebuildModalEncoder*` (se mantienen intactas por si se reactivan), backend, builders
- Sin cambio de comportamiento en Analizar Señal (botón, duración, barra de progreso, polling)
- Sin cambio de BD
