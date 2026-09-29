-- Migración 002: Crear tabla alert_rules para sistema de reglas configurable
-- Fecha: 2026-09-29
-- Issue: #7 — Sistema de reglas configurable para alertas de plataformas externas

CREATE TABLE IF NOT EXISTS alert_rules (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    
    -- Filtros de aplicabilidad
    source VARCHAR(50) NOT NULL,                    -- tsmonitor, packager, encoder, any
    channel_id INT DEFAULT NULL,                    -- NULL = todos los canales
    alert_type VARCHAR(50) NOT NULL,                -- freeze, dead, down, restore, ok, up, etc.
    
    -- Acción a ejecutar
    action VARCHAR(50) NOT NULL,                    -- stop_encoder, start_encoder, restart_encoder, notify_only, failover
    
    -- Configuración
    enabled BOOLEAN DEFAULT TRUE,
    priority INT DEFAULT 0,                         -- Mayor = más prioridad
    cooldown_seconds INT DEFAULT 60,
    
    -- Notificaciones
    notify_telegram BOOLEAN DEFAULT TRUE,
    notify_cms BOOLEAN DEFAULT TRUE,
    custom_message TEXT DEFAULT NULL,
    
    -- Auditoría
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
    last_executed_at DATETIME DEFAULT NULL,
    
    -- foreign key
    FOREIGN KEY (channel_id) REFERENCES channels(id) ON DELETE CASCADE,
    
    -- Índices
    INDEX idx_source (source),
    INDEX idx_channel_id (channel_id),
    INDEX idx_alert_type (alert_type),
    INDEX idx_enabled (enabled),
    INDEX idx_source_channel_type (source, channel_id, alert_type)
);

-- Insertar reglas por defecto (comportamiento actual)
-- tsmonitor: freeze/dead/down → stop_encoder
INSERT INTO alert_rules (name, source, alert_type, action, enabled, priority, cooldown_seconds, notify_telegram, notify_cms) VALUES
('TSMonitor: Freeze → Stop Encoder', 'tsmonitor', 'freeze', 'stop_encoder', TRUE, 100, 60, TRUE, TRUE),
('TSMonitor: Dead → Stop Encoder', 'tsmonitor', 'dead', 'stop_encoder', TRUE, 100, 60, TRUE, TRUE),
('TSMonitor: Down → Stop Encoder', 'tsmonitor', 'down', 'stop_encoder', TRUE, 100, 60, TRUE, TRUE);

-- tsmonitor: restore/ok/up/restored/live → start_encoder
INSERT INTO alert_rules (name, source, alert_type, action, enabled, priority, cooldown_seconds, notify_telegram, notify_cms) VALUES
('TSMonitor: Restore → Start Encoder', 'tsmonitor', 'restore', 'start_encoder', TRUE, 100, 60, TRUE, TRUE),
('TSMonitor: OK → Start Encoder', 'tsmonitor', 'ok', 'start_encoder', TRUE, 100, 60, TRUE, TRUE),
('TSMonitor: Up → Start Encoder', 'tsmonitor', 'up', 'start_encoder', TRUE, 100, 60, TRUE, TRUE),
('TSMonitor: Restored → Start Encoder', 'tsmonitor', 'restored', 'start_encoder', TRUE, 100, 60, TRUE, TRUE),
('TSMonitor: Live → Start Encoder', 'tsmonitor', 'live', 'start_encoder', TRUE, 100, 60, TRUE, TRUE);

-- tsmonitor: black → notify_only
INSERT INTO alert_rules (name, source, alert_type, action, enabled, priority, cooldown_seconds, notify_telegram, notify_cms) VALUES
('TSMonitor: Black → Notify Only', 'tsmonitor', 'black', 'notify_only', TRUE, 100, 60, TRUE, TRUE);

-- packager: caido/activo → notify_only
INSERT INTO alert_rules (name, source, alert_type, action, enabled, priority, cooldown_seconds, notify_telegram, notify_cms) VALUES
('Packager: Caído → Notify Only', 'packager', 'caido', 'notify_only', TRUE, 100, 60, TRUE, TRUE),
('Packager: Activo → Notify Only', 'packager', 'activo', 'notify_only', TRUE, 100, 60, TRUE, TRUE);
