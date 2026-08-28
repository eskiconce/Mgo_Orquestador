import os
from dotenv import load_dotenv

load_dotenv()

# ==========================================
# CONFIGURACIÓN GENERAL
# ==========================================
LOG_DIR = os.getenv("LOG_DIR", "logs")
AGENT_API_KEY = os.getenv("AGENT_API_KEY", "a1b2c3d4e5f67890123456789abcdef0")
AGENT_PORT = int(os.getenv("AGENT_PORT", "8000"))
DRM_HEALTH_PORT = int(os.getenv("DRM_HEALTH_PORT", "8080"))
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "10"))

# ==========================================
# INTEGRACIÓN CMS Y VOD
# ==========================================
ORCHESTRATOR_WEBHOOK_URL = os.getenv("ORCHESTRATOR_WEBHOOK_URL", "http://172.16.223.5:9000/api/internal/vod-webhook")
CMS_REAL_WEBHOOK = os.getenv("CMS_REAL_WEBHOOK", "https://core-dev.mundogo.cl/api/webhook-vod")
VOD_API_PORT = int(os.getenv("VOD_API_PORT", "8005"))

# ==========================================
# HAPROXY
# ==========================================
HAPROXY_NODES = os.getenv("HAPROXY_NODES", "172.16.223.240").split(",")
HAPROXY_AGENT_PORT = int(os.getenv("HAPROXY_AGENT_PORT", "8002"))

# ==========================================
# SEÑAL OFFLINE / FAILOVER
# ==========================================
OFFLINE_IP = os.getenv("OFFLINE_IP", "226.1.2.58")
OFFLINE_PORT = int(os.getenv("OFFLINE_PORT", "2058"))
OFFLINE_PROTO = os.getenv("OFFLINE_PROTO", "udp")

# ==========================================
# KMS / DRM API
# ==========================================
KMS_API_URL = os.getenv("KMS_API_URL", "http://172.16.222.240:8000")
KMS_API_KEY = os.getenv("KMS_API_KEY", "a1b2c3d4e5f67890123456789abcdef0")

# ==========================================
# SEGURIDAD Y JWT (Auth Local)
# ==========================================
SECRET_KEY = os.getenv("SECRET_KEY", "MUNDO_GO_PLUS_SECRET_KEY_VERY_SECURE_2026")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))

# ==========================================
# TELEGRAM
# ==========================================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ==========================================
# BASE DE DATOS
# ==========================================
DATABASE_URL = os.getenv("DATABASE_URL", "mysql+pymysql://ingservice:S3rv1c3.Ingenieria@localhost:3306/encoder_orchestrator")
