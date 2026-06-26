from sqlalchemy import Column, Integer, String, Boolean, Text, ForeignKey, DateTime, Float, DECIMAL, Enum
from sqlalchemy.orm import relationship, backref
from database import Base
from datetime import datetime
import base64
import zlib


class Channel(Base):
    __tablename__ = "channels"

    id = Column(Integer, primary_key=True, index=True)

    # --- Identificación ---
    channel_name = Column(String(100))
    ruta = Column(String(100), nullable=True)
    unique_id = Column(String(50), unique=True)

    tech_contact_name = Column(String(100))
    tech_contact_phone = Column(String(50))
    tech_contact_email = Column(String(100))
    customer = Column(String(100))

    # --- Estado ---
    created_at = Column(DateTime, default=datetime.now)
    enabled = Column(Boolean, default=True)
    redundancy_group = Column(String(50))
    notes = Column(Text)

    # =========================
    # ORIGENES (principal/respaldo)
    # =========================
    # Principal
    origin_multicast_ip = Column(String(50))
    origin_multicast_port = Column(Integer)
    input_protocol = Column(String(20), default="udp")
    program_id = Column(Integer, default=1)

    # Nuevo: cantidad de orígenes (1 o 2)
    origin_count = Column(Integer, default=1)  # 1=solo principal, 2=principal+respaldo

    # Respaldo (solo IP/puerto por ahora)
    origin2_multicast_ip = Column(String(50), nullable=True)
    origin2_multicast_port = Column(Integer, nullable=True)

    # Nuevo: origen activo (para futura etapa de failover)
    active_origin = Column(String(10), default="primary")  # primary | backup | offline

    # Parámetros avanzados (se usan para ambos orígenes por ahora)
    probesize = Column(String(10), default="5M")
    analyzeduration = Column(String(10), default="5M")
    fifo_size = Column(Integer, default=1000000)
    buffer_size = Column(Integer, default=2000000)

    # --- Encoding ---
    video_codec = Column(String(50), default="libx264")
    audio_codec = Column(String(50), default="aac")
    fps_p1 = Column(Float, default=30)
    fps_p2 = Column(Float, default=30)
    gop_p1 = Column(Integer, default=60)
    gop_p2   = Column(Integer, default=60)
    interlaced = Column(Boolean, default=False)

    burn_subtitles = Column(Boolean, default=False)
    subtitle_pid = Column(Integer, nullable=True)

    # --- Output ---
    multicast_ip_out = Column(String(15))

    port_1080p = Column(Integer)
    resolution_p1 = Column(String(20), default="1920x1080")
    bitrate_p1 = Column(String(20), default="6500k")
    bitrate_high_max = Column(String(20), default="7000k")

    port_480p = Column(Integer)
    bitrate_p2 = Column(String(20), default="2500k")
    bitrate_low_max = Column(String(20), default="3000k")

    port_audio = Column(Integer)
    audio_mapping = Column(String(60), default="")

    jobs = relationship("EncodingJob", back_populates="channel")





class Node(Base):
    __tablename__ = "nodos"

    id = Column(Integer, primary_key=True, index=True)
    hostname = Column(String(200))
    
    # --- NUEVO CAMPO PARA ENRUTAMIENTO HAPROXY ---
    node_name = Column(String(50), nullable=True) 
    # ---------------------------------------------
    
    ip_address = Column(String(50))
    ip_multicast = Column(String(16), nullable=True)
    # Tipo de Nodo
    tipo = Column(String(20), default='Encoder') 
    # Métricas
    cpu_usage = Column(Float, default=0)
    mem_usage = Column(Float, default=0)
    gpu_usage = Column(Float, default=0)
    status = Column(String(50), default="offline")
    last_heartbeat = Column(DateTime, nullable=True)
    enabled = Column(Boolean, default=True)
    # Campos SSH 
    ssh_user = Column(String(64), nullable=True)
    ssh_password = Column(String(128), nullable=True)
    ssh_port = Column(Integer, default=22)

    # --- NUEVOS CAMPOS PARA ALTA DISPONIBILIDAD (HA) ---
    backup_node_id = Column(Integer, ForeignKey("nodos.id"), nullable=True)
    backup_node = relationship("Node", remote_side="Node.id")
    # ---------------------------------------------------

    jobs = relationship("EncodingJob", back_populates="node")



class EncodingJob(Base):
    __tablename__ = "encoding_jobs"
    id = Column(Integer, primary_key=True, index=True)
    channel_id = Column(Integer, ForeignKey("channels.id"))
    node_id = Column(Integer, ForeignKey("nodos.id")) 
    status = Column(String(50), default="stopped") 
    started_at = Column(DateTime, nullable=True) 
    command = Column(Text)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    parent_job_id = Column(Integer, ForeignKey("encoding_jobs.id"), nullable=True) 
    auto_started = Column(Boolean, default=False) 
    
    # --- NUEVO CAMPO: ESTADO DRM ---
    is_drm = Column(Boolean, default=False)
    # -------------------------------

    children = relationship("EncodingJob", backref=backref('parent', remote_side=[id]))
    node = relationship("Node", back_populates="jobs")
    channel = relationship("Channel", back_populates="jobs")

    source_url = Column(Text) 
    last_visual_hash = Column(String(255), nullable=True)
    source_status = Column(String(20), default='unknown')
    output_status = Column(String(20), default='unknown') 
    last_output_hash = Column(String(255), nullable=True)

    @property
    def command_compress(self):
        """
        Comprime el texto con Zlib y luego lo pasa a Base64.
        """
        if not self.command:
            return ""
        try:
            cmd_bytes = self.command.encode('utf-8')
            compressed = zlib.compress(cmd_bytes)
            return base64.b64encode(compressed).decode('utf-8')
        except Exception as e:
            print(f"Error comprimiendo: {e}")
            return ""

class EncoderHealth(Base):
    __tablename__ = "encoder_health"
    id = Column(Integer, primary_key=True, index=True)
    encoder_id = Column(Integer, ForeignKey("nodos.id")) 
    timestamp = Column(DateTime, default=datetime.now)
    reachable = Column(Boolean)
    cpu_usage = Column(Float)
    p_cpu_usage = Column(Float, default=0.0)  # <-- NUEVA COLUMNA 22jun26
    ram_usage = Column(Float)
    gpu_usage = Column(Float) 
    ffmpeg_running = Column(Boolean)

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True) 
    email = Column(String(100), unique=True, index=True)
    full_name = Column(String(100))
    hashed_password = Column(String(255))
    disabled = Column(Boolean, default=False)

class Recording(Base):
    __tablename__ = "recordings"

    id = Column(Integer, primary_key=True, index=True)
    process_id = Column(String(100), unique=True, index=True) # El ID que envía el CMS
    canal = Column(String(100))
    node_id = Column(Integer, ForeignKey("nodos.id")) # Para saber en qué Origin quedó
    output_dir = Column(String(255), nullable=True)
    # --- NUEVOS CAMPOS PARA BLOQUEO DE BORRADO ---
    in_use = Column(Boolean, default=False)
    in_use_since = Column(DateTime, nullable=True)
    # ---------------------------------------------
    status = Column(String(50), default="pending")    # pending, success, error
    created_at = Column(DateTime, default=datetime.now)
    finished_at = Column(DateTime, nullable=True)
    # Relación con el nodo para sacar su nombre fácilmente
    node = relationship("Node")
    deleted_at = Column(DateTime, nullable=True, default=None) # 24jun26 nuevo campo

class SystemLog(Base):
    __tablename__ = "system_logs"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.now, index=True)
    level = Column(String(20), index=True)  # INFO, WARNING, ERROR, CRITICAL
    message = Column(Text)

class MonitorLog(Base):
    __tablename__ = "monitor_logs"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.now, index=True)
    node_id = Column(Integer, ForeignKey("nodos.id"), nullable=True) # Puede ser nulo si es un evento global
    event_type = Column(String(50), index=True) # Ej: 'NODE_DOWN', 'NODE_UP', 'FAILOVER', 'HIGH_CPU'
    message = Column(Text)

    # Relación para poder traer el nombre del nodo fácilmente en el Front-End
    node = relationship("Node")


class PackagerLog(Base):
    __tablename__ = "packager_logs"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, index=True)
    canal = Column(String(100), index=True)
    node_id = Column(Integer, ForeignKey("nodos.id"), nullable=True) # Relación automática
    hostname = Column(String(200))
    estado = Column(String(50))
    mensaje = Column(Text)
    created_at = Column(DateTime, default=datetime.now)

    # Relación para extraer propiedades del servidor fácilmente si es necesario
    node = relationship("Node")

