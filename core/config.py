import os

# ==========================================
# CONFIGURACIÓN GENERAL
# ==========================================
LOG_DIR = "logs"
AGENT_API_KEY = "a1b2c3d4e5f67890123456789abcdef0"
AGENT_PORT = 8000
DRM_HEALTH_PORT = 8080

# ==========================================
# INTEGRACIÓN CMS Y VOD
# ==========================================
# La URL de tu Orquestador para que los Origins le avisen
ORCHESTRATOR_WEBHOOK_URL = "http://172.16.223.5:9000/api/internal/vod-webhook"
# La URL real de tu CMS
CMS_REAL_WEBHOOK = "https://core-dev.mundogo.cl/api/webhook-vod"
VOD_API_PORT = 8005

# ==========================================
# HAPROXY
# ==========================================
# IPs de tus HAProxy (Añade o quita IPs de esta lista según necesites)
HAPROXY_NODES = ["172.16.223.240"] 
HAPROXY_AGENT_PORT = 8002

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
SECRET_KEY = "MUNDO_GO_PLUS_SECRET_KEY_VERY_SECURE_2026" 
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 # 24 Horas