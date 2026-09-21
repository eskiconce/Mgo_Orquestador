#!/usr/bin/env python3
"""Add uptime tracking columns to nodos table."""
import pymysql

DB_CONFIG = {
    'host': 'localhost',
    'user': 'ingservice',
    'password': 'S3rv1c3.Ingenieria',
    'database': 'encoder_orchestrator'
}

def migrate():
    conn = pymysql.connect(**DB_CONFIG)
    cursor = conn.cursor()
    
    # Check if columns exist
    cursor.execute("SHOW COLUMNS FROM nodos LIKE 'previous_uptime_seconds'")
    if cursor.fetchone():
        print("Columns already exist, skipping migration")
        return
    
    # Add columns
    cursor.execute("""
        ALTER TABLE nodos 
        ADD COLUMN previous_uptime_seconds INT DEFAULT NULL,
        ADD COLUMN last_restart_detected_at DATETIME DEFAULT NULL
    """)
    
    conn.commit()
    cursor.close()
    conn.close()
    print("Migration completed: added previous_uptime_seconds, last_restart_detected_at")

if __name__ == "__main__":
    migrate()
