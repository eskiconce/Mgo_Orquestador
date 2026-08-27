#!/bin/bash
# ==========================================
# Deploy automático del Orquestador
# Uso:
#   bash deploy.sh                 # Deploy de todos los archivos modificados (git)
#   bash deploy.sh archivo.py      # Deploy de un archivo específico
#   bash deploy.sh --dry-run       # Solo prueba conexión
#   bash deploy.sh --test          # Solo prueba conexión
# ==========================================
set -e

SSH_USER="oymservice"
SSH_HOST="172.16.223.5"
SSH_OPTS="-o PreferredAuthentications=password -o StrictHostKeyChecking=no"
REMOTE_DIR="/opt/encoder-orchestrator"
BACKUP_DIR="${REMOTE_DIR}/backups"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")

DRY_RUN=false

if [ "$1" == "--dry-run" ] || [ "$1" == "--test" ]; then
    DRY_RUN=true
fi

if $DRY_RUN; then
    echo "🧪 MODO PRUEBA — Solo verificando conexión..."
    if [ -z "${SUDO_PASS+x}" ]; then
        read -s -p "🔑 Contraseña sudo de ${SSH_USER}: " SUDO_PASS
        echo ""
    fi

ssh ${SSH_OPTS} -t "${SSH_USER}@${SSH_HOST}" "
        echo '✅ Conexión SSH exitosa'
        echo ''
        echo '📋 Versión actual en servidor:'
        echo ${SUDO_PASS} | sudo -S grep -E '^VERSION_' ${REMOTE_DIR}/core/version.py 2>/dev/null || echo ${SUDO_PASS} | sudo -S grep -E '^VERSION_' ${REMOTE_DIR}/main.py
        echo ''
        echo '📂 Respaldos existentes:'
        echo ${SUDO_PASS} | sudo -S ls -lh ${BACKUP_DIR}/ 2>/dev/null || echo '   (sin respaldos aún)'
        echo ''
        echo '📊 Estado del servicio:'
        echo ${SUDO_PASS} | sudo -S systemctl status encoder-api.service --no-pager 2>&1 | head -5
        echo ''
        echo '🎯 Modo prueba — No se realizaron cambios'
    "
    echo ""
    echo "🧪 Prueba completada. Sin cambios en el servidor."
    exit 0
fi

# Determinar archivos a desplegar
if [ -n "$1" ]; then
    FILES=("$1")
else
    # Usar git diff para obtener archivos modificados (solo .py)
    if git rev-parse --git-dir > /dev/null 2>&1; then
        FILES=()
        while IFS= read -r line; do FILES+=("$line"); done < <(git diff --name-only --diff-filter=M HEAD -- '*.py' '*.html')
        if [ ${#FILES[@]} -eq 0 ]; then
            echo "⚠️ No hay archivos .py ni .html modificados según git."
            exit 1
        fi
    else
        echo "⚠️ No es un repositorio git. Usa: bash deploy.sh <archivo.py>"
        exit 1
    fi
fi

echo "🚀 Deploy de ${#FILES[@]} archivo(s) a ${SSH_USER}@${SSH_HOST}..."
for f in "${FILES[@]}"; do echo "   - $f"; done

# Pedir contraseña sudo si no viene del entorno
if [ -z "${SUDO_PASS+x}" ]; then
    read -s -p "🔑 Contraseña sudo de ${SSH_USER}: " SUDO_PASS
    echo ""
fi

# 1. Subir archivos a /tmp/ preservando estructura
echo "📤 Subiendo archivos..."
for FILE in "${FILES[@]}"; do
    REMOTE_PATH="/tmp/${FILE}"
    echo "   → ${FILE}"
    ssh "${SSH_USER}@${SSH_HOST}" "mkdir -p $(dirname ${REMOTE_PATH})"
    scp "${FILE}" "${SSH_USER}@${SSH_HOST}:${REMOTE_PATH}"
done

# 2. Una sola SSH con todas las operaciones sudo
echo "📦 Instalando en servidor..."
INSTALL_CMDS=""
for FILE in "${FILES[@]}"; do
    REMOTE_TMP="/tmp/${FILE}"
    REMOTE_DST="${REMOTE_DIR}/${FILE}"
    INSTALL_CMDS+="
  # Respaldar ${FILE}
  echo ${SUDO_PASS} | sudo -S mkdir -p $(dirname ${BACKUP_DIR}/${FILE}.${TIMESTAMP}.bak)
  echo ${SUDO_PASS} | sudo -S cp ${REMOTE_DST} ${BACKUP_DIR}/${FILE}.${TIMESTAMP}.bak
  echo '✅ Respaldo: ${FILE}.${TIMESTAMP}.bak'
  
  # Mover archivo nuevo
  echo ${SUDO_PASS} | sudo -S mv ${REMOTE_TMP} ${REMOTE_DST}"
done

ssh -t "${SSH_USER}@${SSH_HOST}" "
  # Crear carpeta de backups
  echo ${SUDO_PASS} | sudo -S mkdir -p ${BACKUP_DIR}${INSTALL_CMDS}
  
  # Verificar sintaxis de archivos Python
  for f in ${FILES[@]}; do
    case \$f in
      *.py)
        echo ${SUDO_PASS} | sudo -S python3 -m py_compile ${REMOTE_DIR}/\$f && echo \"✅ Python OK: \$f\"
        ;;
      *)
        echo \"📄 Copiado: \$f\"
        ;;
    esac
  done
  
  # Reiniciar servicio
  echo ${SUDO_PASS} | sudo -S systemctl restart encoder-api.service
  echo '✅ Servicio reiniciado'
"

# 3. Verificar estado
sleep 2
echo "📋 Estado del servicio:"
ssh -t "${SSH_USER}@${SSH_HOST}" "echo ${SUDO_PASS} | sudo -S systemctl status encoder-api.service --no-pager | head -8"

echo ""
echo "🎉 Deploy completado!"
echo "   Archivos: ${FILES[*]}"
echo "   Respaldo: ${BACKUP_DIR}/"
