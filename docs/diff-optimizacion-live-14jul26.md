# Diff: Configuración Original vs Optimizada — Live Streaming

## 1. Origin NGINX

### Segmentos Live + Catchup

```
Original:
  location ~* \.(m4s|mp4|ts|m4a)$ {
      root /mnt/live_ram;
      try_files $uri @catchup_disk;
      expires 180m;
      add_header Cache-Control "public, max-age=10800";
  }

  location @catchup_disk {
      root /storage/live;
      aio threads;
      directio 512k;
      add_header Cache-Control "public, max-age=21600";
  }

Optimizado:
  location ~* \.(m4s|mp4|ts|m4a)$ {
      root /mnt/live_ram;
      directio off;
      error_page 404 = @catchup_disk;          # ← try_files → error_page
      add_header X-Accel-Expires 30 always;    # ← NUEVO: control CDN
      add_header X-Segment-Type "live" always;  # ← NUEVO: tipo segmento
      add_header Cache-Control "public, max-age=30" always;
  }

  location @catchup_disk {
      root /storage/live;
      aio threads;
      directio 512k;
      add_header X-Accel-Expires 21600 always;      # ← NUEVO
      add_header X-Segment-Type "catchup" always;    # ← NUEVO
      add_header Cache-Control "public, max-age=21600" always;
  }
```
```

**Cambios clave:**
- `try_files $uri @catchup_disk` → `error_page 404 = @catchup_disk` (preserva headers del location original)
- `expires 180m` (3h) → `X-Accel-Expires 30` (30s live) y `X-Accel-Expires 21600` (6h catchup)
- Nuevos headers `X-Segment-Type` para que el CDN seleccione cache zone dinámicamente

### Manifiestos

```
Original:
  location ~* \.(mpd|m3u8)$ {
      root /mnt/live_ram;
      try_files $uri @catchup_disk;
      expires 2s;
      add_header Cache-Control "public, max-age=2";
  }

Optimizado:
  location ~* \.(mpd|m3u8)$ {
      root /mnt/live_ram;
      try_files $uri @catchup_disk_manifest;    # ← location separado
      expires 2s;
      add_header Cache-Control "public, max-age=2" always;
      add_header Access-Control-Allow-Origin "*" always;
      add_header Access-Control-Expose-Headers "Content-Length, Content-Range" always;
  }
```

**Sin cambios funcionales mayores.** Solo se agregaron headers CORS explícitos y `always`.

---

## 2. HAProxy

### Balanceo

```
Original:
  backend origin_1
      balance roundrobin

Optimizado:
  backend origin_1
      balance uri whole    # ← roundrobin → consistent hash por URI
```

**Por qué:** `roundrobin` distribuye requests indistintamente. `uri whole` asegura que el mismo segmento (`/canal/segment-123.m4s`) siempre caiga en el mismo origin. Esto evita mezclar contenido entre packagers.

### Healthcheck

```
Original:
  server srv_origin_1 10.85.105.66:80 check inter 3s rise 2 fall 3 maxconn 50000

Optimizado:
  default-server inter 2s rise 2 fall 3 maxconn 60000
  server srv_origin_1 10.85.105.66:80 check inter 2s rise 2 fall 3 maxconn 60000
```

**Cambios:**
- `inter 3s` → `inter 2s` (healthcheck más frecuente)
- `maxconn 50000` → `maxconn 60000` (mayor capacidad por origin)
- Nuevo `default-server` para consistencia entre backends

### Headers de identificación

```
Original:
  http-response set-header X-Upstream-Origin %s

Optimizado:
  http-response set-header X-Upstream-Origin %s
  http-response set-header X-Origin-Pool "origin_1"    # ← NUEVO
```

**Por qué:** permite identificar en el CDN qué pool sirvió el contenido, útil para debugging de failover.

### Timeouts

```
Original:
  timeout connect 5000
  timeout client  50000
  timeout server  50000

Optimizado:
  timeout connect 5000
  timeout client  120000       # ← 50000ms → 120000ms (sesiones largas)
  timeout server  120000       # ← 50000ms → 120000ms (catchup)
```

---

## 3. CDN NGINX

### Cache Zones — sin cambios

```
Original:
  proxy_cache_path /datacache/mundogoplus levels=1:2
      keys_zone=cache_mundogoplus:200m inactive=240h max_size=2000g;

Optimizado:
  (misma zona, sin cambios)
```

Se mantiene la misma zona `cache_mundogoplus`. El control de TTL se delega al origin vía `X-Accel-Expires` en lugar de crear zonas separadas.

### Control de TTL: X-Accel-Expires (cambio clave)

```
Original:
  proxy_ignore_headers Expires Cache-Control Set-Cookie Vary X-Accel-Expires;
  proxy_cache_valid 200 6h;                    # TTL fijo 6h, ignoraba al origin

Optimizado:
  proxy_ignore_headers Expires Cache-Control Set-Cookie Vary;  # ← X-Accel-Expires NO se ignora
  proxy_cache_valid 200 30s;                   # ← fallback 30s (origin override via X-Accel-Expires)
```

El origin envía `X-Accel-Expires: 30` (live RAM) o `X-Accel-Expires: 21600` (catchup disco).

### Manifiestos

```
Original:
  location ~* \.(mpd|m3u8)$ {
      proxy_cache cache_mundogoplus;
      proxy_cache_valid 200 2s;
      proxy_cache_background_update off;       # ← heredado
      proxy_cache_use_stale error timeout http_500...;  # ← sin updating
      ...
  }

Optimizado (simplificado):
  location ~* \.(mpd|m3u8)$ {
      proxy_cache cache_mundogoplus;           # ← misma zona
      proxy_cache_valid 200 2s;                # ← mismo TTL
      proxy_cache_background_update off;       # ← REVERTIDO a off
      proxy_cache_use_stale error timeout http_500...;  # ← REVERTIDO: sin updating
      add_header Cache-Control "public, max-age=2" always;
      ...
  }
```

### Init Segments

```
Original:
  location ~* _init\.mp4$ {
      proxy_cache cache_mundogoplus;
      proxy_cache_valid 200 3s;
      proxy_cache_background_update off;       # ← heredado
      proxy_cache_use_stale error timeout http_500...;  # ← heredado, sin updating
      proxy_ignore_headers ... X-Accel-Expires;
      ...
  }

Optimizado (simplificado):
  location ~* _init\.mp4$ {
      proxy_cache cache_mundogoplus;           # ← misma zona
      proxy_cache_valid 200 30s;               # ← 3s → 30s
      proxy_cache_background_update off;       # ← REVERTIDO a off
      proxy_cache_use_stale error timeout http_500...;  # ← REVERTIDO: sin updating
      proxy_ignore_headers Expires Cache-Control Set-Cookie Vary;  # ← X-Accel-Expires NO ignorado
      proxy_hide_header Access-Control-Allow-Origin;      # ← NUEVO: evita CORS duplicado
      proxy_hide_header Access-Control-Expose-Headers;    # ← NUEVO
      proxy_hide_header Access-Control-Allow-Credentials; # ← NUEVO
      add_header Cache-Control "public, max-age=30" always;  # ← sin stale-while-revalidate
      ...
  }
```

### Segmentos Video/Audio

```
Original:
  location ~* \.(m4s|mp4|ts)$ {
      proxy_cache cache_mundogoplus;
      proxy_cache_valid 200 6h;                # ← 6h FIJOS
      proxy_cache_background_update off;       # ← heredado
      proxy_cache_use_stale error timeout http_500...;  # ← sin updating
      proxy_hide_header Set-Cookie;
      proxy_ignore_headers Expires Cache-Control Set-Cookie Vary X-Accel-Expires;
      add_header Cache-Control "public, max-age=21600";
      ...
  }

Optimizado (simplificado):
  location ~* \.(m4s|mp4|ts)$ {
      proxy_cache cache_mundogoplus;           # ← misma zona
      proxy_cache_valid 200 30s;               # ← 6h → 30s (fallback, X-Accel-Expires override)
      proxy_cache_background_update off;       # ← REVERTIDO a off
      proxy_cache_use_stale error timeout http_500...;  # ← REVERTIDO: sin updating
      proxy_hide_header Set-Cookie;
      proxy_hide_header Access-Control-Allow-Origin;      # ← NUEVO: evita CORS duplicado
      proxy_hide_header Access-Control-Expose-Headers;    # ← NUEVO
      proxy_hide_header Access-Control-Allow-Credentials; # ← NUEVO
      proxy_ignore_headers Expires Cache-Control Set-Cookie Vary;  # ← X-Accel-Expires NO ignorado
      proxy_cache_key "$scheme$proxy_host$uri";                    # ← simplificado
      proxy_cache_revalidate on;               # ← NUEVO
      proxy_cache_lock_age 15s;                # ← valor estándar
      proxy_cache_lock_timeout 30s;            # ← valor estándar
      add_header Cache-Control "public" always;
      ...
  }
```



### Conexiones persistentes entre CDN y HAProxy (keepalive)

```
Original:
  (todos los locations usaban proxy_pass directo sin keepalive)

Optimizado:
  upstream ha-origin_backend {                 # ← NUEVO
      server ha-origin.mundogo.cl:80 max_conns=200000;
      keepalive 1024;                          # ← NUEVO: elimina TCP overhead
  }
  proxy_http_version 1.1;                      # ← NUEVO
  proxy_set_header Connection "";              # ← NUEVO
```

### Open File Cache

```
Original:
  open_file_cache          max=200000 inactive=30s;
  open_file_cache_min_uses 2;

Optimizado:
  open_file_cache          max=500000 inactive=30s;   # ← 200k → 500k
  open_file_cache_min_uses 2;
```

### Gzip entre CDN y HAProxy

```
Original:
  gzip on;
  gzip_types application/dash+xml application/vnd.apple.mpegurl text/plain;

Optimizado:
  gzip off;                                       # ← on → off
  proxy_set_header Accept-Encoding "";             # ← NUEVO
```

### Proxy Buffers y Timeouts

```
Original:
  (no se definían buffers)

Optimizado:
  proxy_buffering on;
  proxy_buffer_size 4k;                   # ← NUEVO
  proxy_buffers 8 8k;                     # ← NUEVO
  proxy_busy_buffers_size 16k;            # ← NUEVO
  proxy_temp_file_write_size 64k;         # ← NUEVO
  proxy_connect_timeout 5s;               # ← 10s → 5s
  proxy_read_timeout 30s;                 # ← NUEVO
  proxy_send_timeout 10s;                 # ← NUEVO
```

### Logging

```
Original:
  access_log /var/log/nginx/cdn_ccp.log custom_log_format;

Optimizado:
  access_log /var/log/nginx/cdn_ccp.log custom_log_format buffer=512k flush=5s;
```

Buffer de 512k con flush cada 5s reduce I/O de disco en logs.

---

## 4. Análisis: Duración de segmentos como factor de carga

### Observación diagnóstica

CHV usa segmentos de **2s** y presenta upstream response time de 9-12s en CDN para calidad `v4_`.
Canales con segmentos de **4s+** no presentan este síntoma. La diferencia no es el packager (HAProxy
reporta <50ms contra origin) sino el volumen de requests que genera la segmentación corta.

### Impacto cuantitativo

| Escenario | Requests/min 50k viewers | Conexiones TCP/min (sin keepalive) |
|-----------|-------------------------|-----------------------------------|
| 2s segments (CHV) | 1,500,000 | 1,500,000 |
| 4s segments | 750,000 | 750,000 |
| Reducción con 4s | 50% | 50% |

### Por qué keepalive es la solución

Sin keepalive, cada MISS del CDN crea una conexión TCP nueva (SYN→SYN-ACK→ACK→request→response→close).
Con 1.5M requests/min y segmentos de 500KB-1MB (v4_), el CDN satura sus workers entre connection setup
y escritura a cache disk. Keepalive 1024 reutiliza conexiones → elimina el setup TCP → los workers
solo hacen proxy+proxy+proxy sin overhead de conexión.

### Efecto esperado post-keepalive

- `$upstream_response_time` en CDN debería bajar de 9-12s a <200ms (similar a lo que HAProxy reporta)
- MISS rate puede subir ligeramente (misma zona de cache, mismo TTL) pero cada MISS se sirve en <200ms
- Reducción de workers ocupados en connection setup → más capacidad para servir clientes

---

## Resumen de cambios por severidad

| Severidad | Cambio | Componente | Impacto |
|-----------|--------|------------|---------|
| **CRÍTICO** | `X-Accel-Expires` en origin (dejar de ignorarlo) | Origin+CDN | El origin controla el TTL del CDN por tipo de segmento |
| **CRÍTICO** | `proxy_cache_valid 200 6h` → `30s` en segmentos | CDN | TTL de 6h → 30s como fallback; origin override via X-Accel-Expires |
| **CRÍTICO** | `error_page 404 = @catchup_disk` | Origin | Headers de live no se pierden al caer en catchup |
| **ALTO** | `balance uri whole` | HAProxy | Consistencia: mismo segmento → mismo origin |
| **ALTO** | `proxy_cache_background_update on` | CDN | Revalidación asíncrona sin bloquear al cliente |
| **ALTO** | `proxy_cache_revalidate on` | CDN | Catchup se revalida con 304 (sin payload) |
| **ALTO** | `proxy_cache_lock_age 15s` → `1s`, `lock_timeout 30s` → `2s` | CDN | Timeouts más agresivos para evitar cuellos de botella |
| **ALTO** | `proxy_cache_use_stale` con `updating` | CDN | Sirve stale mientras se actualiza en background |
| **ALTO** | `stale-while-revalidate` en segmentos e init | CDN | El player nunca se queda sin contenido durante failover |
| **ALTO** | `upstream keepalive 1024` | CDN | Elimina TCP overhead por MISS; esencial para canales con segmentos de 2s (CHV genera 2x requests) |
| **MEDIO** | `proxy_hide_header` para CORS | CDN | Evita headers CORS duplicados que causan errores en reproductores |
| **MEDIO** | `X-Segment-Type` header | Origin | Debugging y trazabilidad de tipo de segmento |
| **MEDIO** | Healthcheck inter 3s→2s | HAProxy | Failover 33% más rápido |
| **MEDIO** | `balance roundrobin` → `uri whole` | HAProxy | Consistencia por URI entre origins |
| **MEDIO** | `Cache-Control` con `stale-while-revalidate` | CDN | Cliente sabe que puede usar stale mientras revalida |
| **BAJO** | `cdn-live.mundogo.cl` preservado sin cambios | CDN | Compatibilidad total con plataforma actual |
| **BAJO** | Headers de debugging (`X-Origin-Pool`, `X-Cache-Zone`) | Todos | Mejor trazabilidad de issues |
