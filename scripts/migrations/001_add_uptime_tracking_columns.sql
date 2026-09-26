-- Migración 001: Agregar columnas de uptime tracking a tabla nodos
-- Fecha: 2026-09-21
-- Issue: #4 — Encoder restart detection via uptime tracking

ALTER TABLE nodos
    ADD COLUMN previous_uptime_seconds INT DEFAULT NULL,
    ADD COLUMN last_restart_detected_at DATETIME DEFAULT NULL;
