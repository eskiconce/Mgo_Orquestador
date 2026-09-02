#!/bin/bash
# ==========================================
# Deploy del Orquestador MundoGo
# Usa SSH key (~/.ssh/id_opencode) — sin passwords
#
# Uso:
#   bash deploy.sh                  # Deploy de archivos modificados (git)
#   bash deploy.sh archivo.py      # Deploy de un archivo específico
#   bash deploy.sh --test           # Solo verificar conexión + versión
#   bash deploy.sh --health        # Solo verificar health endpoint
# ==========================================
set -e

SSH_KEY="$HOME/.ssh/id_opencode"
SSH_USER="oymservice"
SSH_HOST="172.16.223.5"
SSH_OPTS="-i ${SSH_KEY} -o StrictHostKeyChecking=no"
REMOTE_DIR="/opt/encoder-orchestrator"
SUDO_PASS="S3rv1c3.operaciones"

# --- Funciones ---
ssh_cmd() {
    ssh ${SSH_OPTS} "${SSH_USER}@${SSH_HOST}" "$@"
}

sudo_cmd() {
    ssh_cmd "echo '${SUDO_PASS}' | sudo -S $*"
}

check_health() {
    echo "🏥 Verificando health endpoint..."
    HEALTH=$(curl -s --max-time 5 http://${SSH_HOST}:9000/api/health 2>/dev/null || echo '{"status":"unreachable"}')
    STATUS=$(echo "$HEALTH" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','unknown'))" 2>/dev/null || echo "unknown")
    VERSION=$(echo "$HEALTH" | python3 -c "import sys,json; print(json.load(sys.stdin).get('version','unknown'))" 2>/dev/null || echo "unknown")

    if [ "$STATUS" = "healthy" ]; then
        echo "   ✅ Status: ${STATUS} | Versión: ${VERSION}"
        return 0
    else
        echo "   ❌ Status: ${STATUS} | Versión: ${VERSION}"
        return 1
    fi
}

# --- Modo test ---
if [ "$1" == "--test" ]; then
    echo "🧪 MODO PRUEBA — Verificando conexión..."
    echo ""
    echo "📋 Versión actual:"
    sudo_cmd "grep -E '^VERSION_' ${REMOTE_DIR}/core/version.py"
    echo ""
    echo "📊 Estado del servicio:"
    sudo_cmd "systemctl is-active encoder-api.service encoder-monitor.service"
    echo ""
    check_health
    echo ""
    echo "🧪 Prueba completada. Sin cambios."
    exit 0
fi

# --- Modo health ---
if [ "$1" == "--health" ]; then
    check_health
    exit $?
fi

# --- Determinar archivos a desplegar ---
if [ -n "$1" ] && [ "$1" != "--all" ]; then
    FILES=("$1")
else
    if git rev-parse --git-dir > /dev/null 2>&1; then
        FILES=()
        while IFS= read -r line; do FILES+=("$line"); done < <(git diff --name-only --diff-filter=AM HEAD -- '*.py' '*.html')
        if [ ${#FILES[@]} -eq 0 ]; then
            echo "⚠️ No hay archivos modificados según git."
            exit 1
        fi
    else
        echo "⚠️ No es un repositorio git. Usa: bash deploy.sh <archivo.py>"
        exit 1
    fi
fi

echo "🚀 Deploy de ${#FILES[@]} archivo(s) a ${SSH_HOST}..."
for f in "${FILES[@]}"; do echo "   - $f"; done
echo ""

# --- Verificar salud pre-deploy ---
check_health || echo "⚠️ Servicio no está saludable pre-deploy"
echo ""

# --- 1. Backup + copiar archivos ---
echo "📤 Subiendo archivos..."
for FILE in "${FILES[@]}"; do
    REMOTE_TMP="/tmp/${FILE}"
    mkdir -p "$(dirname /tmp/${FILE})"
    scp ${SSH_OPTS} "${FILE}" "${SSH_USER}@${SSH_HOST}:${REMOTE_TMP}" 2>/dev/null
    echo "   ✅ ${FILE}"
done

# --- 2. Instalar en servidor ---
echo ""
echo "📦 Instalando..."
INSTALL_CMDS=""
for FILE in "${FILES[@]}"; do
    REMOTE_TMP="/tmp/${FILE}"
    REMOTE_DST="${REMOTE_DIR}/${FILE}"
    BACKUP_DST="${REMOTE_DIR}/backups/${FILE}.$(date +%Y%m%d_%H%M%S).bak"
    INSTALL_CMDS+="
mkdir -p $(dirname ${BACKUP_DST}) 2>/dev/null
cp ${REMOTE_DST} ${BACKUP_DST} 2>/dev/null || true
cp ${REMOTE_TMP} ${REMOTE_DST}
"
done

sudo_cmd "mkdir -p ${REMOTE_DIR}/backups && ${INSTALL_CMDS}"

# --- 3. Limpiar pycache ---
sudo_cmd "rm -rf ${REMOTE_DIR}/__pycache__ ${REMOTE_DIR}/core/__pycache__ ${REMOTE_DIR}/routers/__pycache__ ${REMOTE_DIR}/services/__pycache__"

# --- 4. Verificar sintaxis ---
echo "🔍 Verificando sintaxis..."
for FILE in "${FILES[@]}"; do
    case "$FILE" in
        *.py)
            sudo_cmd "python3 -m py_compile ${REMOTE_DIR}/${FILE}" 2>/dev/null && echo "   ✅ ${FILE}" || echo "   ❌ ERROR: ${FILE}"
            ;;
        *)
            echo "   📄 ${FILE} (copiado)"
            ;;
    esac
done

# --- 5. Reiniciar servicios ---
echo ""
echo "🔄 Reiniciando servicios..."
sudo_cmd "systemctl restart encoder-api.service encoder-monitor.service"
sleep 3

# --- 6. Verificar health post-deploy ---
echo ""
check_health

# --- 7. Estado final ---
echo ""
echo "📊 Estado final:"
sudo_cmd "systemctl is-active encoder-api.service encoder-monitor.service"

echo ""
echo "🎉 Deploy completado!"
echo "   Archivos: ${FILES[*]}"
echo "   Respaldo: ${REMOTE_DIR}/backups/"
