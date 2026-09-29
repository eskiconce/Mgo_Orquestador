# Diagrama de Flujo — Sistema de Reglas para Alertas Externas

## Flujo Principal

```mermaid
flowchart TB
    subgraph EXTERNAL["🔌 Plataforma Externa"]
        A[tsmonitor] 
        B[packager]
        C[encoder]
        D[Otra plataforma]
    end

    subgraph GATEWAY["🚪 Gateway de Alertas"]
        E["POST /api/alertas/{source}"]
        F["Normalizar a\nNormalizedAlert"]
    end

    subgraph ENGINE["⚙️ Motor de Reglas"]
        G["Buscar reglas aplicables"]
        H["1. Regla específica\n(source + canal + tipo)"]
        I["2. Regla global source\n(source + NULL + tipo)"]
        J["3. Regla global total\n(NULL + NULL + tipo)"]
        K["4. Comportamiento default"]
        L{"Cooldown\nactivo?"}
    end

    subgraph ACTIONS["🎯 Ejecución de Acciones"]
        M["stop_encoder"]
        N["start_encoder"]
        O["restart_encoder"]
        P["failover"]
        Q["notify_only"]
    end

    subgraph NOTIFY["📢 Notificaciones"]
        R["Telegram"]
        S["CMS webhook"]
    end

    subgraph AUDIT["📋 Auditoría"]
        T["monitor_logs\n+ rule_id"]
    end

    A --> E
    B --> E
    C --> E
    D --> E
    
    E --> F
    F --> G
    
    G --> H
    G --> I
    G --> J
    G --> K
    
    H --> L
    I --> L
    J --> L
    K --> L
    
    L -->|Sí| M
    L -->|Sí| N
    L -->|Sí| O
    L -->|Sí| P
    L -->|Sí| Q
    L -->|No| T
    
    M --> R
    N --> R
    O --> R
    P --> R
    Q --> R
    
    M --> S
    N --> S
    O --> S
    P --> S
    Q --> S
    
    R --> T
    S --> T

    style EXTERNAL fill:#e1f5fe
    style GATEWAY fill:#f3e5f5
    style ENGINE fill:#fff3e0
    style ACTIONS fill:#e8f5e9
    style NOTIFY fill:#fce4ec
    style AUDIT fill:#f5f5f5
```

## Flujo de Búsqueda de Reglas

```mermaid
flowchart TD
    A["Recibir alerta normalizada"] --> B{"Buscar regla específica:\nsource + channel_id + alert_type"}
    
    B -->|Encontrada| C["Usar regla específica"]
    B -->|No encontrada| D{"Buscar regla global source:\nsource + channel_id=NULL + alert_type"}
    
    D -->|Encontrada| E["Usar regla global source"]
    D -->|No encontrada| F{"Buscar regla global total:\nsource=NULL + channel_id=NULL + alert_type"}
    
    F -->|Encontrada| G["Usar regla global total"]
    F -->|No encontrada| H["Usar comportamiento default"]
    
    C --> I{"¿Regla habilitada?"}
    E --> I
    G --> I
    H --> I
    
    I -->|No| J["Registrar sin acción"]
    I -->|Sí| K{"¿Cooldown activo?"}
    
    K -->|Sí| L["Registrar cooldown\n(no ejecutar)"]
    K -->|No| M["Ejecutar acción"]
    
    M --> N["Actualizar timestamp\ncooldown"]
    N --> O["Notificar"]
    O --> P["Registrar auditoría"]

    style A fill:#e3f2fd
    style C fill:#c8e6c9
    style E fill:#c8e6c9
    style G fill:#c8e6c9
    style H fill:#ffcdd2
    style M fill:#a5d6a7
    style J fill:#ef9a9a
    style L fill:#ffcc80
```

## Integración de Nueva Plataforma

```mermaid
flowchart LR
    subgraph PASO1["Paso 1: Crear Endpoint"]
        A["POST /api/alertas/nueva_plataforma"]
        B["Schema de entrada"]
    end
    
    subgraph PASO2["Paso 2: Crear Normalizador"]
        C["Mapear status → tipo normalizado"]
        D["Retornar NormalizedAlert"]
    end
    
    subgraph PASO3["Paso 3: Configurar Reglas"]
        E["Crear reglas en BD\ncon source = nueva_plataforma"]
        F["Las reglas existentes\naplican automáticamente"]
    end

    A --> B
    B --> C
    C --> D
    D --> E
    E --> F

    style PASO1 fill:#e3f2fd
    style PASO2 fill:#f3e5f5
    style PASO3 fill:#e8f5e9
```

## Acciones Disponibles

| Acción | Descripción | Endpoint Agente |
|--------|-------------|-----------------|
| `stop_encoder` | Detiene el encoder del canal | `POST /jobs/control?action=stop` |
| `start_encoder` | Inicia el encoder del canal | `POST /jobs/create` |
| `restart_encoder` | Reinicia el encoder (stop + start) | `POST /jobs/control?action=restart` |
| `failover` | Activa failover a señal de respaldo | `POST /api/internal/trigger-failover/{id}` |
| `notify_only` | Solo registra log y notifica | (sin acción en encoder) |

## Prioridad de Reglas

```
1. Regla específica (source + channel_id + alert_type)
   ↓ no encontrada
2. Regla global source (source + channel_id=NULL + alert_type)
   ↓ no encontrada
3. Regla global total (source=NULL + channel_id=NULL + alert_type)
   ↓ no encontrada
4. Comportamiento por defecto (hardcodeado)
```
