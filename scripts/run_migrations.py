#!/usr/bin/env python3
"""
Sistema de migraciones de esquema para Mgo_Orquestador.

Uso:
    python scripts/run_migrations.py          # Ejecuta migraciones pendientes
    python scripts/run_migrations.py --status # Muestra estado de migraciones
"""
import os
import sys
import glob
import hashlib
import pymysql
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core.config import DATABASE_URL


def parse_db_url(url: str) -> dict:
    """Extrae host, user, password, database desde DATABASE_URL."""
    # mysql+pymysql://user:pass@host:port/db
    parts = url.split("://", 1)[1]
    auth_host = parts.split("@", 1)
    user_pass = auth_host[0].split(":", 1)
    host_db = auth_host[1].split("/", 1)
    host_port = host_db[0].split(":", 1)
    return {
        "host": host_port[0],
        "port": int(host_port[1]) if len(host_port) > 1 else 3306,
        "user": user_pass[0],
        "password": user_pass[1],
        "database": host_db[1],
    }


def ensure_migrations_table(conn):
    """Crea la tabla schema_migrations si no existe."""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                id INT AUTO_INCREMENT PRIMARY KEY,
                version VARCHAR(20) NOT NULL UNIQUE,
                name VARCHAR(200) NOT NULL,
                applied_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                checksum VARCHAR(64)
            )
        """)
    conn.commit()


def get_applied(conn) -> set:
    """Retorna las versiones ya aplicadas."""
    with conn.cursor() as cur:
        cur.execute("SELECT version FROM schema_migrations ORDER BY version")
        return {row[0] for row in cur.fetchall()}


def get_pending(migrations_dir: str, applied: set) -> list:
    """Retorna migraciones pendientes ordenadas por versión."""
    pattern = os.path.join(migrations_dir, "*.sql")
    files = sorted(glob.glob(pattern))
    pending = []
    for f in files:
        basename = os.path.basename(f)
        version = basename.split("_")[0]
        if version not in applied:
            pending.append((version, basename, f))
    return pending


def apply_migration(conn, version: str, name: str, filepath: str):
    """Ejecuta una migración SQL y la registra."""
    with open(filepath, "r") as f:
        sql = f.read()

    checksum = hashlib.sha256(sql.encode()).hexdigest()[:16]

    with conn.cursor() as cur:
        for statement in sql.split(";"):
            stmt = statement.strip()
            if stmt:
                cur.execute(stmt)

        cur.execute(
            "INSERT INTO schema_migrations (version, name, checksum) VALUES (%s, %s, %s)",
            (version, name, checksum)
        )
    conn.commit()
    print(f"  ✓ Applied: {name}")


def main():
    db_config = parse_db_url(DATABASE_URL)
    conn = pymysql.connect(**db_config)

    try:
        ensure_migrations_table(conn)
        applied = get_applied(conn)
        migrations_dir = os.path.join(os.path.dirname(__file__), "migrations")
        pending = get_pending(migrations_dir, applied)

        if "--status" in sys.argv:
            print(f"Applied: {len(applied)} | Pending: {len(pending)}")
            for v, name, _ in pending:
                print(f"  → {name}")
            return

        if not pending:
            print("No pending migrations.")
            return

        print(f"Running {len(pending)} migration(s)...")
        for version, name, filepath in pending:
            apply_migration(conn, version, name, filepath)

        print("All migrations applied successfully.")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
