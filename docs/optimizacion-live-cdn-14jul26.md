# Optimización Live Streaming: Origin → HAProxy → CDN — 14 Julio 2026

## Problema

Cuando el packager se detiene y se activa el failover/backup, al retomar el packager original el player reproduce segmentos de video "pegados" en el cache del CDN (sesión anterior), provocando errores visuales en la reproducción en vivo.

**Causas raíz:**
1. Segmentos cacheados por 6h (`proxy_cache_valid 200 6h`) — al volver el packager original, la CDN sirve segmentos viejos
2. Cache key no discrimina origen ni instancia — segmentos de packager A y B comparten misma key
3. HAProxy con `roundrobin` — un mismo player puede recibir manifiesto de un origin y segmentos de otro
4. Manifiesto se cachea 2s, segmentos 6h — el player pide nuevo manifiesto, ve segmentos nuevos, pero la CDN le sirve los viejos
5. **Segmentos de 2s en CHV vs 4s+ en otros canales**: la duración del segmento multiplica la carga en el CDN (ver análisis abajo)

---

## Diseño de la solución

### Principio: freshness ≠ availability

El origin controla el TTL de cada segmento via `X-Accel-Expires`. El CDN respeta este header y cachea según el tipo de contenido (30s live, 21600s catchup).

| Tipo de contenido | TTL freshness | stale-while-revalidate | Cache zone | Almacenamiento físico |
|---|---|---|---|---|---|
| Manifiestos (mpd/m3u8) | 2s | 10s | `cache_mundogoplus` | RAM disk |
| Init segments (_init.mp4) | 30s | 604800s (7d) | `cache_mundogoplus` | RAM disk |
| Segmentos LIVE (m4s/mp4/ts) | Según `X-Accel-Expires` (30s) | 604800s (7d) | `cache_mundogoplus` | RAM disk |
| Segmentos CATCHUP (m4s/mp4/ts) | Según `X-Accel-Expires` (21600s) | 604800s (7d) | `cache_mundogoplus` | Disco físico |

### Flujo de decisión de cache en CDN

```
CDN recibe petición de segmento
  → proxy_pass a HAProxy
  → HAProxy balancea por URI hash → mismo segmento siempre al mismo origin
  → Origin responde con:
      - X-Accel-Expires: 30 (live RAM) o 21600 (catchup disco)
      - X-Segment-Type: "live" o "catchup" (debug)
  → CDN respeta X-Accel-Expires (no se ignora)
  → TTL efectivo: 30s live, 6h catchup
  → Si el segmento expiró, el CDN va al origin por contenido fresco
```

---

## Cambios en Origin NGINX (4 servidores)

| Archivo | Servidores |
|---------|------------|
| `/etc/nginx/sites-available/origin.mundogo.cl` | Origin_1 (10.85.105.66), Origin_2 (10.85.105.70), Origin_3 (10.85.105.74), Origin_4 (10.85.105.78) |

### 1. Headers de control de cache por tipo de segmento

**Antes**: sin distinción entre segmentos live y catchup. Ambos se servían con `expires 180m` y sin header `X-Accel-Expires`.

**Ahora**:
- Segmentos en RAM (live): `X-Accel-Expires 30` + `X-Segment-Type "live"`
- Segmentos en disco (catchup): `X-Accel-Expires 21600` + `X-Segment-Type "catchup"`

*(Nota: diseño inicial contemplaba cache zones separadas via `map $upstream_http_x_segment_type`. Se simplificó a zona única `cache_mundogoplus` — el origin controla el TTL via `X-Accel-Expires` directamente, sin necesidad de rutear a distintas zonas. `X-Segment-Type` se mantiene como header de debugging.)*

### 2. Separación de location live vs catchup con error_page

**Antes**: `try_files $uri @catchup_disk` — los headers del location `\.(m4s|mp4|ts)$` se perdían al caer en `@catchup_disk` porque `try_files` no hereda headers del location original.

**Ahora**:
- Location `\.(m4s|mp4|ts)$` sirve de RAM y setea headers LIVE. Si el archivo no está en RAM → `error_page 404 = @catchup_disk` (internamente, preservando headers de respuesta del subrequest)
- Location `@catchup_disk` sirve de disco y setea headers CATCHUP

### 3. Healthcheck stub_status

- Sin cambios funcionales, se mantiene acceso restringido por IP

---

## Cambios en HAProxy (1 par o 2 servidores)

| Archivo | Servidores |
|---------|------------|
| `/etc/haproxy/haproxy.cfg` | haproxy-1, haproxy-2 |

### 1. Balanceo por URI consistente

**Antes**: `balance roundrobin` — cada request podía caer en cualquier origin, incluso si eran del mismo segmento.

**Ahora**: `balance uri whole` — el mismo segmento siempre cae en el mismo origin. Esto garantiza consistencia: si el packager A genera un segmento, todos los clientes que pidan ese mismo segmento van al origin A.

### 2. Healthcheck más agresivo

- **Antes**: `inter 3s rise 2 fall 3` (hasta 9s para declarar falla)
- **Ahora**: `inter 2s rise 2 fall 3` (hasta 6s para declarar falla)

### 3. Headers de identificación de pool

- **Nuevo**: `http-response set-header X-Origin-Pool "origin_X"` — permite identificar en el CDN qué pool sirvió el contenido

### 4. Timeouts optimizados para live streaming

- `timeout client 120000` (antes 50000ms) — sesiones de video largas
- `timeout server 120000` (antes 50000ms) — segmentos lentos en catchup

### 5. maxconn por servidor

- **Antes**: `maxconn 50000`
- **Ahora**: `maxconn 60000` — para soportar 50k+ clientes distribuidos en 4 origins

> **Note**: Se eliminaron opciones avanzadas (`maxconn global`, `ulimit-n`, `tune.*`, `splice-auto`, `tcp-smart-*`, `show-legends`) que causaban error al levantar HAProxy por falta de soporte en la versión/límites del sistema.

---

## Cambios en CDN NGINX (servidores edge)

| Archivo | Servidores |
|---------|------------|
| `/etc/nginx/nginx.conf` | CDN edges |

### 1. Cache zone única — el origin controla el TTL

**Antes**: `cache_mundogoplus:200m inactive=240h max_size=2000g` — una sola zona. Los segmentos se cacheaban por 6h fijos (`proxy_cache_valid 200 6h`), sin importar si eran live o catchup.

**Ahora**: Se mantiene `cache_mundogoplus` como zona única. El control de TTL se delega al origin mediante `X-Accel-Expires`. El CDN **deja de ignorar** `X-Accel-Expires`:

```
Antes:  proxy_ignore_headers ... X-Accel-Expires  → TTL fijo de 6h
Ahora:  X-Accel-Expires NO se ignora              → origin decide: 30s live, 21600s catchup
```

`proxy_cache_valid 200 30s` actúa como **fallback** si el origin no envía `X-Accel-Expires`.

No se requieren zonas separadas. El `inactive=240h` de `cache_mundogoplus` permite mantener catchup en cache por días, mientras que los segmentos live expiran naturalmente por TTL (30s) y son reemplazados por LRU si no se acceden.

### 2. Cache: simplificado (similar a cdn-live.mundogo.cl)

Por testing en producción, se determinó que `proxy_cache_background_update on` + `stale-while-revalidate` causaban problemas cuando un canal vuelve tras estar fuera del aire: los segmentos viejos quedaban "stale" por 7 días y el CDN los servía al player aunque el origin ya tuviera contenido nuevo (ver análisis de duración de segmentos).

Se revirtió a una config similar a `cdn-live.mundogo.cl` (que funciona correctamente). La única mejora activa es **upstream keepalive** para resolver el upstream response time lento.

| Parámetro | Valor | Efecto |
|-----------|-------|--------|
| `proxy_cache_revalidate on` | — | Usa If-Modified-Since — catchup válida con 304 (sin payload) |
| `proxy_cache_lock on` | — | Evita "dogpile": 50k clientes piden el mismo segmento, solo 1 va al origin |
| `proxy_cache_lock_age 15s` | 15s | Timeout para el lock (valor estándar) |
| `proxy_cache_lock_timeout 30s` | 30s | Máximo tiempo de espera en lock (valor estándar) |
| `proxy_cache_use_stale` | error timeout http_500... | Sirve stale solo si el origin falla (sin `updating`) |
| `proxy_cache_background_update off` | off | No se revalida en background — contenido siempre fresco del origin |
| `stale-while-revalidate` | no utilizado | Eliminado — causaba segmentos viejos en failover |

### 3. Manifiestos: TTL 2s (controlado por origin)

**Antes**: `proxy_cache_valid 200 2s` sin `updating` en stale.

**Ahora**: `proxy_cache_valid 200 2s` — mismo TTL, pero sin stale-while-revalidate:

- El MPD expira cada 2s en cache del CDN
- Cada 2s, el CDN va al origin por el manifiesto fresco
- El origin controla `X-Accel-Expires` y `Cache-Control`
- No se usa `stale-while-revalidate` para evitar que el player use un MPD viejo cuando el packager reinicia

### 4. CORS: ocultar headers del origin para evitar duplicidad

**Antes**: No se ocultaban los headers CORS del origin. El origin setea `Access-Control-Allow-Origin`, `Access-Control-Expose-Headers`, etc., y el CDN también los agrega con `add_header ... always` → resultaban duplicados.

**Ahora**: Todos los locations de segmentos e init segments incluyen:

```nginx
proxy_hide_header Access-Control-Allow-Origin;
proxy_hide_header Access-Control-Expose-Headers;
proxy_hide_header Access-Control-Allow-Credentials;
```

Esto asegura que los únicos headers CORS que llegan al cliente son los que el CDN genera explícitamente, evitando conflictos de CORS por valores duplicados o diferentes entre origin y CDN.

**Nota**: En manifiestos el origin no setea CORS, por lo que no es necesario ocultarlos allí. El CDN los agrega directamente.

### 5. Init segments: TTL 30s (controlado por origin)

**Antes**: `proxy_cache_valid 200 3s` (demasiado corto), sin `updating`.

**Ahora**: `proxy_cache_valid 200 30s`. Los init segments se regeneran con cada sesión del packager, 30s es suficiente para que el CDN obtenga el init actualizado del origin.

### 6. Segmentos: TTL controlado por X-Accel-Expires del origin

**Antes**: `proxy_cache_valid 200 6h` fijo + `proxy_ignore_headers ... X-Accel-Expires` → ignoraba al origin.

**Ahora**: 

- `proxy_cache_valid 200 30s` como **fallback** mínimo
- `X-Accel-Expires` **ya no se ignora** — el origin decide el TTL por segmento
  - Live (RAM): `X-Accel-Expires: 30` → CDN cachea 30s
  - Catchup (disco): `X-Accel-Expires: 21600` → CDN cachea 6h
- `proxy_cache_use_stale` solo para errores (sin `updating`): si el origin falla, sirve cache
- Sin `stale-while-revalidate`: contenido siempre fresco del origin

### 7. Server `cdn-live.mundogo.cl` preservado sin cambios

El server block de la plataforma actual (`cdn-live.mundogo.cl`) se mantiene **exactamente igual**, sin ninguna modificación. Corre en el mismo nginx, comparte las optimizaciones globales pero conserva su propia lógica de cache.

| Aspecto | `cdn-live.mundogo.cl` | `live.mundogo.cl` |
|---------|----------------------|-------------------|
| Cache zone | `cache_mundogo` | `cache_mundogoplus` |
| Upstream | `haproxy.mundogo.cl` | `ha-origin.mundogo.cl` (directo) |
| Backend origins | 172.31.203.41-43 (roundrobin) | 10.85.105.66-78 (URI hash vía HAProxy) |
| Cache TTL | Sin `proxy_cache_valid 200` (solo origen) | `X-Accel-Expires` del origen |
| Background update | off | **on** |

### 8. Ajustes en settings generales del server `live.mundogo.cl`

| Parámetro | cdn-live.mundogo.cl | live.mundogo.cl |
|-----------|---------------------|-----------------|
| `proxy_cache_background_update` | off | **off** (igual) |
| `proxy_cache_lock_timeout` | 30s | **30s** (igual) |
| `proxy_cache_lock_age` | 15s | **15s** (igual) |
| `proxy_cache_valid 200` | no definido (usa origin) | **30s** (fallback) |
| `X-Accel-Expires` | ignorado | **respetado** |
| `upstream keepalive` | no | **1024** |

---

## Flujo completo de failover

### Escenario: Packager A falla, entra Packager B (backup), luego A vuelve

```
t=0s    Packager A deja de generar segmentos
        HAProxy detecta falla (inter 2s → ~6s para marcar down)
        → tráfico redirigido a Packager B (backup en origin_3/origin_4)

t=6s    CDN tiene segmentos de A cacheados en zone "live" con TTL de 30s
        Los nuevos requests de esos segmentos van a Packager B
        → CDN va al origin (via HAProxy) por contenido fresco
        → CDN cachea segmentos de B por 30s

t=10s   Players piden nuevo manifiesto (TTL 2s)
        Manifiesto se actualiza con los segmentos de B
        Players ven transición limpia

t=+Xmin Packager A vuelve a estar online
        HAProxy detecta recuperación (inter 2s → rise 2 → ~4s)
        → tráfico redirigido a Packager A

t=+Xmin+4s  CDN revalida segmentos contra A
            Segmentos nuevos de A reemplazan a los de B en cache
            TTL de 30s asegura convergencia en ≤30s
```

### Qué evita el video pegado

| Mecanismo | Efecto |
|-----------|--------|
| TTL 30s en segmentos live | Segmentos viejos expiran en 30s máximo |
| `proxy_cache_background_update off` | Cada request va al origin — contenido siempre fresco |
| `proxy_cache_revalidate on` | Catchup se revalida con 304 (sin payload) |
| `balance uri whole` en HAProxy | No hay mezcla de segmentos entre origins |
| `upstream keepalive 1024` | Elimina TCP overhead entre CDN y HAProxy |
| `X-Accel-Expires` respetado | Origin controla TTL por tipo de segmento |

---

## Impacto de la duración de segmentos en la carga del CDN

### Observación

El canal CHV usa segmentos de **2 segundos** y presenta upstream response time de 9-12s en la CDN para segmentos `v4_` (alta calidad). Canales con segmentos de **4 segundos o más** no presentan este problema.

### Análisis cuantitativo

| Métrica | 2s segments (CHV) | 4s segments | Factor |
|---------|-------------------|-------------|--------|
| URLs/segmento por minuto por viewer | 30 | 15 | 2x |
| Requests por 50k viewers por minuto | 1,500,000 | 750,000 | 2x |
| Requests catch-up (30s freeze) por viewer | 15 | 7.5 | 2x |
| Conexiones TCP CDN→HAProxy sin keepalive | 1 por request | 1 por request | misma tasa, 2x volumen |

### Cadena de causalidad

```
Segmentos de 2s → 2x más URLs/minuto → más cache keys únicas
  → menor hit ratio (más cardinalidad) → más MISS por segundo
  → más conexiones TCP CDN→HAProxy por segundo
  → sin keepalive: cada MISS = 3-way handshake + request + response + close
  → workers del CDN saturados con connection setup + disk I/O (escribir cache)
  → $upstream_response_time refleja cola de conexión, no tiempo real del origin
```

Los 9-12s en logs del CDN **no son el packager lento**. HAProxy reporta <50ms contra el origin. El tiempo perdido está en la **cola de conexiones TCP** del CDN hacia HAProxy.

### Solución aplicada

Se agregó **upstream keepalive 1024** entre CDN y HAProxy:

```nginx
upstream ha-origin_backend {
    server ha-origin.mundogo.cl:80 max_conns=200000;
    keepalive 1024;
}
```

Esto reutiliza conexiones TCP en lugar de abrir una nueva por cada MISS. Con 1024 conexiones persistentes, el overhead de connection setup se elimina.

### Recomendación adicional

Si la CDN continúa mostrando upstream response time elevado post-keepalive, considerar:

1. **Proxy cache tuning**: Aumentar `proxy_cache_lock_timeout` a 15s para segmentos v4_ de alta calidad (son más grandes → tardan más en escribirse a cache disk)
2. **Separar storage**: Segmentos v4_ (alta calidad) en SSD dedicado dentro de `cache_mundogoplus`
3. **Evaluar segment duration en el packager**: Si el packager de CHV puede cambiar a 4s sin afectar la experiencia, reduce la carga a la mitad

---

## Capacidad estimada para 50k+ clientes

| Recurso | CDN (por edge) | HAProxy | Origin (por servidor) |
|---------|---------------|---------|----------------------|
| Conexiones simultáneas | 65535 * workers | 300000 total | 60000 por servidor |
| Throughput estimado | ~40 Gbps | ~80 Gbps | ~20 Gbps |
| Cache SSD | ~5000GB | — | — |
| RAM para cache de archivos | 500k entries | — | RAM disk para live edge |
| Segmentos en cache | ~500k archivos | — | — |

### Factores que permiten escalar a 50k+

1. **open_file_cache 500k**: Los segmentos más populares se sirven desde RAM de nginx sin tocar disco
2. **Cache lock**: 50k clientes piden el mismo segmento → solo 1 request llega al origin
3. **Background update**: Nunca se bloquean clientes esperando al origin
4. **Upstream keepalive 1024** (implementado): Sin overhead de TCP por request entre CDN y HAProxy — cada MISS reutiliza conexión persistente. Crítico para canales con segmentos de 2s (CHV), que generan 2x requests vs canales de 4s
5. **balance uri whole**: El mismo segmento siempre al mismo origin → mejor uso de cache local del origin (page cache del kernel)
6. **`proxy_cache_revalidate on`**: Catchup se revalida con 304 sin descargar payload

---

## Servidores actualizados

| Servidor | IP | Archivos modificados | Servicio reiniciado |
|----------|-----|----------------------|---------------------|
| Origin_1 | 10.85.105.66 | origin.mundogo.cl | nginx |
| Origin_2 | 10.85.105.70 | origin.mundogo.cl | nginx |
| Origin_3 | 10.85.105.74 | origin.mundogo.cl | nginx |
| Origin_4 | 10.85.105.78 | origin.mundogo.cl | nginx |
| HAproxy-1 | — | haproxy.cfg | haproxy |
| HAproxy-2 | — | haproxy.cfg | haproxy |
| CDN-1 | 10.80.8.6 | nginx.conf | nginx |
| CDN-2 | — | nginx.conf | nginx |
| CDN-3 | — | nginx.conf | nginx |
| CDN-4 | — | nginx.conf | nginx |

---

## Monitoreo y verificación

### Headers de debugging agregados

| Header | Origen | Propósito |
|--------|--------|-----------|
| `X-Segment-Type` | Origin | "live" o "catchup" |
| `X-Origin-Pool` | HAProxy | pool de origen que sirvió |
| `X-Upstream-Origin` | HAProxy | IP del origin específico |
| `X-Cache-Status` | CDN | HIT/MISS/STALE/UPDATING/REVALIDATED |
| `X-Cache-Zone` | CDN | "live" o "catchup" (cache zone usada) |

### Logs

```nginx
log_format custom_log_format '"$remote_addr";"$upstream_cache_status [$time_local]";"$http_referer";'
                           '"$request";"$status";"$body_bytes_sent";'
                           '"$upstream_response_time";'
                           '"$http_user_agent"';
```

### Comandos de verificación post-despliegue

```bash
# Verificar que el origin setea headers correctos
curl -sI http://origin.mundogo.cl/canal1/segment-123.m4s | grep -E "X-Segment-Type|X-Accel-Expires|Cache-Control"

# Verificar que el CDN cachea correctamente
curl -sI http://live.mundogo.cl/canal1/segment-123.m4s | grep -E "X-Cache-Status|X-Cache-Zone|Cache-Control"

# Verificar consistencia de hash en HAProxy
for i in {1..10}; do
    curl -sI http://haproxy.mundogo.cl/canal1/segment-100.m4s | grep -i "x-upstream-origin"
done
# Todas deben mostrar el mismo origin

# Simular failover: detener nginx en origin_1 y verificar transición
# Luego restaurar y verificar que los segmentos se actualizan en ≤30s
```

---

## Roadmap de próximas mejoras

| Prioridad | Mejora | Descripción |
|-----------|--------|-------------|
| Alta | Purga automática en failover | Script que monitorea healthchecks de HAProxy y purga cache zone `live` cuando detecta cambio de estado |
| Media | Cache warming para catchup | Precargar segmentos catchup más populares en la zona `live` para reducir miss rate |
| Media | HSTS + HTTP/2 en CDN | Mejorar performance de conexiones HTTPS con HTTP/2 |
| Baja | Compresión Brotli para manifiestos | Brotli comprime mejor que gzip para XML/M3U8 |
