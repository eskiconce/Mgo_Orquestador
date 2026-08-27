# Rotacion de Llaves DRM v2.0.0

## Fecha
15 Julio 2026

## Descripcion
Sistema de rotacion de llaves Widevine que se gatilla desde el orquestador al generar el script de packager DRM.
Permite rotar la KID+KEY de un canal especifico, varios canales, o todos los canales DRM al mismo tiempo.

## Arquitectura

```
[Browser] → checkbox "Rotar llave" + click "Generar Script (con DRM)"
    ↓
[Orquestador] POST /orchestrator/packager-drm/rotate-and-build
    ↓
[Orquestador] httpx → POST http://172.16.222.240:8000/api/keys/rotate
    ↓
[KMS API]     Genera nuevo KID+KEY
              → INSERT content_keys (NUEVA fila, la anterior se conserva)
              → SET Redis drm:key:{new_kid} (la key vieja sigue en cache)
              → SET Redis drm:active_channel:{channel_id} (apunta a la nueva)
              → LOG rotacion
    ↓
[Orquestador] builders.generate_packager_drm_with_keys(channel, node, new_kid, new_key)
    ↓
[Browser]     Script bash con KID/KEY inline (sin curl a KMS en runtime)
```

## Endpoints Nuevos

### KMS API (172.16.222.240:8000)

| Metodo | Ruta | Body | Respuesta |
|--------|------|------|-----------|
| `POST` | `/api/keys/rotate` | `{"channel_id": "canal_x"}` | `{"status":"rotated","kid":"...","key":"...","previous_kid":"..."}` |

### Orquestador (172.16.223.5:9000)

| Metodo | Ruta | Uso |
|--------|------|-----|
| `POST` | `/orchestrator/packager-drm/rotate-and-build` | Genera script rotando llave + embedandola inline |
| `POST` | `/orchestrator/rotate-key/{channel_id}` | Rotacion simple de un canal |
| `POST` | `/orchestrator/rotate-keys/batch` | Rotacion batch. Body: `{"channel_ids": [1,2,3]}` o `[]` para todos los DRM |

## Cambios en Modelo

### Channel (models.py)
```python
is_drm = Column(Boolean, default=False)
```
- Indica si el canal usa proteccion Widevine
- Se configura desde el formulario de edicion/creacion de canales (toggle DRM)
- Columna agregada via ALTER TABLE a la base de datos existente

## Cambios en Builders (services/builders.py)

### generate_packager_drm_bash() (existente)
- Sin cambios funcionales
- El script sigue llamando a KMS en runtime via curl para obtener la llave

### generate_packager_drm_with_keys(channel, node, kid, key) (nueva)
- Recibe KID+KEY ya rotadas
- Genera script con las llaves inline (sin llamada a KMS en runtime)
- Usada por el flujo de rotacion

## Cambios en UI

### Formulario Nuevo Proceso (process_form.html)
- Nuevo checkbox **"Rotar llave al generar"** junto al checkbox DRM
- Al marcarlo y hacer click en "Generar Script (con DRM)", el backend:
  1. Llama a KMS para rotar la llave
  2. Genera el script con la nueva llave embebida

### Lista de Procesos (process_list.html)
- **Botón 🔄 por fila**: aparece solo en procesos Packager con `is_drm=True`. Llama a `/orchestrator/rotate-key/{channel_id}`
- **Botón "Rotar todas DRM"**: en toolbar superior. Llama a `/orchestrator/rotate-keys/batch` con `[]` (todos los canales DRM)
- Confirmacion previa antes de ejecutar (alert nativo del browser)

### Formulario de Canales (channel_form.html)
- Nuevo toggle **DRM** en la seccion de identificacion del servicio
- Al guardar el canal, se persiste el campo `is_drm` en la DB

## Flujos de Uso

### 1. Rotacion al generar script (nuevo proceso)
1. Ir a `Crear Proceso`
2. Seleccionar canal + nodo Packager
3. Marcar checkbox **"Rotar llave al generar"**
4. Click "Generar Script (con DRM)"
5. El script generado tiene la nueva KID+KEY inline
6. Crear el proceso normalmente

### 2. Rotacion desde lista de procesos
1. Ir a `Operaciones`
2. Pestaña Packagers
3. Buscar proceso con badge `DRM`
4. Click botón 🔄 en acciones
5. Confirmar en el dialogo
6. **El orquestador automaticamente**:
   - Rota la llave en KMS (INSERT nueva fila)
   - Busca packagers activos del canal (running/starting/failover)
   - Regenera el script con la nueva key inline
   - Envia el nuevo comando al agente (`/jobs/create`)
   - Reinicia el proceso packager en el nodo remoto (`/jobs/control restart`)
   - **Downtime**: ~2-3 segundos (stop + start del packager)

### 3. Rotacion masiva
1. Ir a `Operaciones`
2. Click botón **"Rotar todas DRM"** en toolbar superior
3. Confirmar en el dialogo
4. Se rotan todos los canales con `is_drm=True` (solo rotacion en KMS, sin reiniciar packagers)

## Consideraciones

- **Rotacion desde lista (boton 🔄)**: si el packager esta activo, el orquestador regenera el script con la nueva key y reinicia el proceso automaticamente. Downtime ~2-3s
- **Rotacion desde formulario (checkbox)**: solo genera el script con la nueva key inline. No reinicia ningun proceso
- **Keys antiguas se conservan**: cada rotacion hace `INSERT` en `content_keys`. Las keys viejas siguen accesibles por KID para que el DRM license server (Java) pueda servir licencias de contenido ya cifrado
- **Retencion**: keys antiguas quedan en la DB sin limite actual. Pendiente implementar purge a 120 dias
- **`/kms/generate`** retorna la key mas reciente (`ORDER BY created_at DESC`)
- **Redis**: no se elimina la key vieja del cache (sigue siendo valida para el license server). Solo se actualiza `drm:active_channel:` para que nuevos packagers tomen la key rotada

## Version

```
v2.0.0
```
