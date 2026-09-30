CREATE TABLE IF NOT EXISTS app_settings (
    id INT AUTO_INCREMENT PRIMARY KEY,
    section VARCHAR(50) NOT NULL,
    `key` VARCHAR(100) NOT NULL,
    value TEXT NULL,
    UNIQUE KEY uq_section_key (section, `key`)
);

CREATE TABLE IF NOT EXISTS alert_sources (
    id INT AUTO_INCREMENT PRIMARY KEY,
    slug VARCHAR(50) NOT NULL,
    name VARCHAR(100) NOT NULL,
    token VARCHAR(64) NOT NULL,
    enabled TINYINT(1) NOT NULL DEFAULT 1,
    description VARCHAR(255) NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_alert_sources_slug (slug)
);

INSERT INTO app_settings (section, `key`, value) VALUES
('telegram', 'enabled', '0'),
('telegram', 'bot_token', ''),
('telegram', 'chat_id', ''),
('email', 'enabled', '0'),
('email', 'auth_mode', 'smtp'),
('email', 'smtp_host', ''),
('email', 'smtp_port', '587'),
('email', 'smtp_tls', '1'),
('email', 'smtp_user', ''),
('email', 'smtp_password', ''),
('email', 'graph_tenant_id', ''),
('email', 'graph_client_id', ''),
('email', 'graph_client_secret', ''),
('email', 'from_addr', ''),
('email', 'recipients', ''),
('cms', 'enabled', '1'),
('cms', 'webhook_url', 'https://core-dev.mundogo.cl/api/webhook-vod'),
('security', 'api_key', 'a1b2c3d4e5f67890123456789abcdef0')
ON DUPLICATE KEY UPDATE `key` = `key`;

INSERT INTO alert_sources (slug, name, token, enabled, description) VALUES
('tsmonitor', 'TSMonitor', '', 1, 'Endpoint dedicado /api/alertas/tsmonitor (abierto, sin token)'),
('packager', 'Packager', '', 1, 'Endpoint dedicado /api/alertas/packager (abierto, sin token)'),
('encoder', 'Encoder', '', 1, 'Alertas internas del encoder')
ON DUPLICATE KEY UPDATE slug = slug;
