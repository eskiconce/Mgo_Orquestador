from core.logging_service import logger
from core.config import OFFLINE_IP, OFFLINE_PORT

def parse_shaka_bw(bw_str, default="5000000"):
    """Convierte formatos como '7000k' o '5M' a bits por segundo crudos para Shaka Packager"""
    if not bw_str: return default
    bw_str = str(bw_str).strip().lower()
    try:
        if bw_str.endswith('k'): return str(int(float(bw_str.replace('k', '')) * 1000))
        if bw_str.endswith('m'): return str(int(float(bw_str.replace('m', '')) * 1000000))
        return str(int(bw_str))
    except Exception:
        return default

# --------- #
def generate_packager_bash(channel, node, failover=False):
    """Genera el script de Packager Normal (Sin DRM)"""
    canal = channel.ruta or "canal"
    canal = str(canal).strip()
    interface = node.ip_multicast
    #output_dir = f"/storage/live/{canal}"
    output_dir = f"/mnt/live_ram/{canal}"

    bw_p1 = parse_shaka_bw(channel.bitrate_high_max, "4000000")
    bw_p2 = parse_shaka_bw(channel.bitrate_low_max, "2500000")

    if failover:
        logger.warning(f"⚠️ GENERANDO SCRIPT FAILOVER para {canal} usando {OFFLINE_IP}:{OFFLINE_PORT}")
        segment_duration = 6
        return f"""#!/bin/bash

# ---- #
ORIGEN="{OFFLINE_IP}"
PORT="{OFFLINE_PORT}"
OUTPUT_DIR="{output_dir}"
INTERFACE="{interface}"
CANAL="{canal}"
# ---- #
mkdir -p "$OUTPUT_DIR"
# Tag único por ejecución (timestamp en segundos)
TAG=$(date +%s)
# ---- #
exec packager \\
  "in=udp://$ORIGEN:$PORT?interface=$INTERFACE&reuse=1,stream=video,init_segment=$OUTPUT_DIR/fov1_"${{TAG}}"_init.mp4,segment_template=$OUTPUT_DIR/fov1_\\$Time\\$.m4s,bw=2500000" \
  "in=udp://$ORIGEN:$PORT?interface=$INTERFACE&reuse=1,stream=audio,init_segment=$OUTPUT_DIR/foa0_"${{TAG}}"_init.mp4,segment_template=$OUTPUT_DIR/foa0_\\$Time\\$.m4s,language=spa,hls_group_id=audio,hls_name=Español,bw=128000" \
  --default_language=es \\
  --time_shift_buffer_depth 21600 \\
  --segment_duration {segment_duration} \\
  --fragment_duration {segment_duration} \\
  --minimum_update_period {segment_duration} \\
  --suggested_presentation_delay 18 \\
  --preserved_segments_outside_live_window 30 \\
  --utc_timings="urn:mpeg:dash:utc:http-iso:2014=https://time.akamai.com/?iso" \\
  --generate_static_mpd=false \\
  --mpd_output "$OUTPUT_DIR/$CANAL.mpd" \\
  --io_block_size 512000
# ---- #

"""
    else:
        fps = float(channel.fps_p1) if channel.fps_p1 else 30
        gop = int(channel.gop_p1) if channel.gop_p1 else 60
        segment_duration = int(gop / fps) if gop % fps == 0 else round(gop / fps, 3)
        suggested = ( segment_duration * 3 ) + 2

        return f"""#!/bin/bash

# ---- #
ORIGEN="{channel.multicast_ip_out}"
CANAL="{canal}"
OUTPUT_DIR="{output_dir}"
INTERFACE="{interface}"
PORT1="{channel.port_1080p}"
PORT4="{channel.port_480p}"
PORTA="{channel.port_1080p}"
# Tag único por ejecución (timestamp en segundos)
TAG=$(date +%s)
# ---- #
mkdir -p "$OUTPUT_DIR"
# ---- #
exec packager \\
  "in=udp://$ORIGEN:$PORT1?interface=$INTERFACE&reuse=1&buffer_size=33554432,stream=video,init_segment=$OUTPUT_DIR/v1_"${{TAG}}"_init.mp4,segment_template=$OUTPUT_DIR/v1_\\$Time\\$.m4s,bw={bw_p1}" \\
  "in=udp://$ORIGEN:$PORT4?interface=$INTERFACE&reuse=1&buffer_size=33554432,stream=video,init_segment=$OUTPUT_DIR/v4_"${{TAG}}"_init.mp4,segment_template=$OUTPUT_DIR/v4_\\$Time\\$.m4s,bw={bw_p2}" \\
  "in=udp://$ORIGEN:$PORTA?interface=$INTERFACE&reuse=1&buffer_size=33554432,stream=audio,init_segment=$OUTPUT_DIR/a0_"${{TAG}}"_init.mp4,segment_template=$OUTPUT_DIR/a0_\\$Time\\$.m4s,language=spa,hls_group_id=audio,hls_name=Español,bw=128000" \\
  --default_language=spa \\
  --time_shift_buffer_depth 21600 \\
  --segment_duration {segment_duration} \\
  --fragment_duration {segment_duration} \\
  --minimum_update_period {segment_duration} \\
  --suggested_presentation_delay {suggested} \\
  --preserved_segments_outside_live_window 30 \\
  --utc_timings="urn:mpeg:dash:utc:http-iso:2014=https://time.akamai.com/?iso" \\
  --generate_static_mpd=false \\
  --mpd_output "$OUTPUT_DIR/$CANAL.mpd" \\
  --io_block_size 512000
# ---- #

"""

# --------- #
def generate_packager_drm_bash(channel, node):
    """Genera el script de Packager con DRM y llamadas a KMS (runtime key fetch)"""
    canal = channel.ruta or "canal"
    canal = str(canal).strip()
    interface = node.ip_multicast
    #output_dir = f"/storage/live/{canal}"
    output_dir = f"/mnt/live_ram/{canal}"

    bw_p1 = parse_shaka_bw(channel.bitrate_high_max, "4000000")
    bw_p2 = parse_shaka_bw(channel.bitrate_low_max,  "2500000")

    fps = float(channel.fps_p1) if channel.fps_p1 else 30.0
    gop = int(channel.gop_p1) if channel.gop_p1 else 60
    segment_duration = int(gop / fps) if gop % fps == 0 else round(gop / fps, 3)
    suggested = ( segment_duration * 3 ) + 2 

    return f"""#!/bin/bash

# ---- #
ORIGEN="{channel.multicast_ip_out}"
CANAL="{canal}"
OUTPUT_DIR="{output_dir}"
INTERFACE="{interface}"
PORT1="{channel.port_1080p}"
PORT4="{channel.port_480p}"
PORTA="{channel.port_1080p}"
# ---- #
mkdir -p "$OUTPUT_DIR"
# Tag único por ejecución (timestamp en segundos)
TAG=$(date +%s)
# ---- #
KMS_URL="https://kms.mundogo.cl/kms/generate"
echo "[INFO] Solicitando llave al KMS para el canal: $CANAL..."
RESPONSE=$(curl -s -X POST "$KMS_URL" -H "Content-Type: application/json" -d "{{\\"channel_id\\": \\"$CANAL\\"}}")
KID=$(echo "$RESPONSE" | jq -r .kid)
KEY=$(echo "$RESPONSE" | jq -r .key)
# ---- #
if [ -z "$KID" ] || [ "$KID" == "null" ]; then
    echo "[ERROR] El KMS no respondió correctamente. Abortando."
    echo "Respuesta cruda: $RESPONSE"
    exit 1
fi
echo "[INFO] Llave obtenida exitosamente -> KID: $KID"
# ---- #
exec packager \\
  "in=udp://$ORIGEN:$PORT1?interface=$INTERFACE&reuse=1&buffer_size=33554432,stream=video,init_segment=$OUTPUT_DIR/v1_"${{TAG}}"_init.mp4,segment_template=$OUTPUT_DIR/v1_\\$Time\\$.m4s,bw={bw_p1},drm_label=HD" \\
  "in=udp://$ORIGEN:$PORT4?interface=$INTERFACE&reuse=1&buffer_size=33554432,stream=video,init_segment=$OUTPUT_DIR/v4_"${{TAG}}"_init.mp4,segment_template=$OUTPUT_DIR/v4_\\$Time\\$.m4s,bw={bw_p2},drm_label=SD" \\
  "in=udp://$ORIGEN:$PORTA?interface=$INTERFACE&reuse=1&buffer_size=33554432,stream=audio,init_segment=$OUTPUT_DIR/a0_"${{TAG}}"_init.mp4,segment_template=$OUTPUT_DIR/a0_\\$Time\\$.m4s,language=spa,hls_group_id=audio,hls_name=Español,bw=128000,drm_label=AUDIO" \\
  --enable_raw_key_encryption \\
  --keys label=AUDIO:key_id=$KID:key=$KEY,label=SD:key_id=$KID:key=$KEY,label=HD:key_id=$KID:key=$KEY \\
  --protection_systems Widevine \\
  --default_language=spa \\
  --time_shift_buffer_depth 21600 \\
  --segment_duration {segment_duration} \\
  --fragment_duration {segment_duration} \\
  --minimum_update_period {segment_duration} \\
  --suggested_presentation_delay {suggested} \\
  --preserved_segments_outside_live_window 30 \\
  --utc_timings="urn:mpeg:dash:utc:http-iso:2014=https://time.akamai.com/?iso" \\
  --generate_static_mpd=false \\
  --mpd_output "$OUTPUT_DIR/$CANAL.mpd" \\
  --io_block_size 512000

  # ---- #
"""

# --------- #
# def generate_linux_encoder_bash(channel, node, include_subtitles=None, use_backup=False):
#     """Genera el script estático para un Encoder Linux usando libx264 por CPU"""

#     if use_backup and channel.origin_count > 1 and channel.origin2_multicast_ip and channel.origin2_multicast_port:
#         origen_ip = channel.origin2_multicast_ip
#         origen_port = channel.origin2_multicast_port
#     else:
#         origen_ip = channel.origin_multicast_ip
#         origen_port = channel.origin_multicast_port
#     fps_p1, gop_p1 = float(channel.fps_p1 or 30), int(channel.gop_p1 or 60)
#     fps_p2, gop_p2 = float(channel.fps_p2 or 30), int(channel.gop_p2 or 60)

#     locaddress = node.ip_multicast
#     dest_ip = channel.multicast_ip_out
#     dest_p1 = channel.port_1080p
#     dest_p4 = channel.port_480p
#     dest_pa = channel.port_audio

#     bitrate_p1 = channel.bitrate_p1.strip() if channel.bitrate_p1 else "4000k"
#     bitrate_p4 = channel.bitrate_p2.strip() if channel.bitrate_p2 else "2500k"
#     bitrate_m1 = channel.bitrate_high_max.strip() if channel.bitrate_high_max else "4000k"
#     bitrate_m4 = channel.bitrate_low_max.strip() if channel.bitrate_low_max else "2500k"
#     key_min_p1 = gop_p1 / 2
#     key_min_p4 = gop_p2 / 2

#     resolucion_bd = channel.resolution_p1 if channel.resolution_p1 else "1920x1080"
#     if resolucion_bd == "1280x720": scale_p1, threads_p1, bufsize_p1 = "1280:720", 4, "10M"
#     else: scale_p1, threads_p1, bufsize_p1 = "1920:1080", 6, "12M"

#     audio_map = channel.audio_mapping.strip() if channel.audio_mapping else "-map 0:a:0"

#     burn_subs = include_subtitles if include_subtitles is not None else channel.burn_subtitles
#     subtitle_var, filter_complex = "", ""
#     if burn_subs and channel.subtitle_pid is not None:
#         subtitle_var = f'SUBTITLE="{channel.subtitle_pid}"\n'
#         filter_complex = f"""[0:v]yadif=mode=0:parity=-1:deint=0,fps=$FPS_P1[v_deint]; \\
# [v_deint][0:s:$SUBTITLE]overlay=eof_action=pass:repeatlast=0[v_subbed]; \\
# [v_subbed]split=2[v_b1][v_b4]; \\
# [v_b1]scale={scale_p1}:flags=fast_bilinear,setsar=1,format=yuv420p[vout1]; \\
# [v_b4]fps=$FPS_P2,scale=852:480:flags=fast_bilinear,setsar=1,format=yuv420p[vout2]"""
#     else:
#         filter_complex = f"""[0:v]yadif=mode=0:parity=-1:deint=0,split=2[v_b1][v_b4]; \\
# [v_b1]fps=$FPS_P1,scale={scale_p1}:flags=fast_bilinear,setsar=1,format=yuv420p[vout1]; \\
# [v_b4]fps=$FPS_P2,scale=852:480:flags=fast_bilinear,setsar=1,format=yuv420p[vout2]"""

#     return f"""#!/bin/bash

# # ---- #
# ORIGEN_IP="{origen_ip}"
# ORIGEN_PORT="{origen_port}"
# FPS_P1="{fps_p1}"
# GOP_P1="{gop_p1}"
# FPS_P2="{fps_p2}"
# GOP_P2="{gop_p2}"
# LOCADDRESS="{locaddress}"
# DEST_IP="{dest_ip}"
# DEST_P1="{dest_p1}"
# DEST_P4="{dest_p4}"
# DEST_PA="{dest_pa}"
# AUDIO_MAP="{audio_map}"
# {subtitle_var}
# # ---- #
# ORIGEN_URL="udp://$ORIGEN_IP:$ORIGEN_PORT?localaddr=$LOCADDRESS&fifo_size=2000000&overrun_nonfatal=1&buffer_size=26214400&reorder_queue_size=2500" 
# DEST_P1="udp://$DEST_IP:$DEST_P1?localaddr=$LOCADDRESS&fifo_size=1000000&buffer_size=8388608&reuse=1&pkt_size=1316&ttl=32" 
# DEST_P4="udp://$DEST_IP:$DEST_P4?localaddr=$LOCADDRESS&fifo_size=1000000&buffer_size=8388608&reuse=1&pkt_size=1316&ttl=32"
# # ---- #
# # ---- ASIGNAR CPU A UTILIZAR ---- #
# exec numactl --cpunodebind=0 --membind=0 \\
# /usr/bin/ffmpeg -hide_banner -loglevel info -y \\
#  -fflags +genpts+discardcorrupt+igndts -err_detect ignore_err -thread_queue_size 8192 -filter_threads 6 \\
#  -probesize 2M -analyzeduration 2M -ignore_unknown -async 1\\
#  -i "$ORIGEN_URL" \\
#  -filter_complex " \\
#  {filter_complex}" \\
# \\
# -map "[vout1]" -c:v:0 libx264 -threads {threads_p1} -preset fast -profile:v:0 high \\
# -b:v:0 {bitrate_p1} -maxrate:v:0 {bitrate_m1} -minrate:v:0 {bitrate_p1} -bufsize:v:0 {bitrate_m1} \\
# -g:v:0 {gop_p1} -keyint_min:v:0 {gop_p1} -sc_threshold:v:0 0 -bf:v:0 3 \\
# -x264-params:v:0 "nal-hrd=cbr:aud=1:force-cfr=1:open-gop=0:ref=2:rc-lookahead=10" \\
# $AUDIO_MAP -c:a aac -profile:a aac_low -b:a 128k -ar 48000 -ac 2 -af "aresample=async=1:min_hard_comp=0.100000" \\
# -muxdelay 0.7 -muxpreload 0.7 -muxrate 6M \\
# -f mpegts -mpegts_flags +resend_headers+pat_pmt_at_frames -pcr_period 20 \\
# "$DEST_P1" \\
# \\
# -map "[vout2]" -c:v:0 libx264 -threads 4 -preset fast -profile:v:0 high \\
# -b:v:0 {bitrate_p4} -maxrate:v:0 {bitrate_m4} -minrate:v:0 {bitrate_p4} -bufsize:v:0 {bitrate_m4} \\
# -g:v:0 {gop_p2} -keyint_min:v:0 {gop_p2} -sc_threshold:v:0 0 -bf:v:0 3 \\
# -x264-params:v:0 "nal-hrd=cbr:aud=1:force-cfr=1:open-gop=0:ref=2:rc-lookahead=10" \\
# -muxdelay 0.7 -muxpreload 0.7 -muxrate 5M \\
# -f mpegts -mpegts_flags +resend_headers+pat_pmt_at_frames -pcr_period 20 \\
# "$DEST_P4"

# # ---- #
# """
# --------- #
def generate_linux_encoder_bash(channel, node, include_subtitles=None, use_backup=False):
    """Genera el script estático para un Encoder Linux usando libx264 por CPU"""

    if use_backup and channel.origin_count > 1 and channel.origin2_multicast_ip and channel.origin2_multicast_port:
        origen_ip = channel.origin2_multicast_ip
        origen_port = channel.origin2_multicast_port
    else:
        origen_ip = channel.origin_multicast_ip
        origen_port = channel.origin_multicast_port

    fps_p1, gop_p1 = float(channel.fps_p1 or 30), int(channel.gop_p1 or 60)
    fps_p2, gop_p2 = float(channel.fps_p2 or 30), int(channel.gop_p2 or 60)

    locaddress = node.ip_multicast
    dest_ip = channel.multicast_ip_out
    dest_p1 = channel.port_1080p
    dest_p4 = channel.port_480p
    dest_pa = channel.port_audio

    bitrate_p1 = channel.bitrate_p1.strip() if channel.bitrate_p1 else "4000k"
    bitrate_p4 = channel.bitrate_p2.strip() if channel.bitrate_p2 else "2500k"

    resolucion_bd = channel.resolution_p1 if channel.resolution_p1 else "1920x1080"
    if resolucion_bd == "1280x720":
        scale_p1, threads_p1, bufsize_p1 = "1280:720", 4, "10M"
    else:
        scale_p1, threads_p1, bufsize_p1 = "1920:1080", 6, "12M"

    audio_map = channel.audio_mapping.strip() if channel.audio_mapping else "0:a:0"

    burn_subs = include_subtitles if include_subtitles is not None else channel.burn_subtitles

    # ---- CONSTRUCCIÓN LIMPIA DEL FILTER_COMPLEX ----
    if burn_subs and channel.subtitle_pid is not None:
        sub_map = f"0:{channel.subtitle_pid}" if ":" not in str(channel.subtitle_pid) else channel.subtitle_pid
        filter_complex = (
            f"[0:v]bwdif=mode=0:parity=-1:deint=0,fps={fps_p1}[v_base];"
            f"[v_base][{sub_map}]overlay=eof_action=pass:repeatlast=0[v_subbed];"
            f"[v_subbed]split=2[v_b1][v_b4];"
            f"[v_b1]scale={scale_p1}:flags=fast_bilinear,setsar=1,format=nv12[vout1];"
            f"[v_b4]scale=852:480:flags=fast_bilinear,setsar=1,format=nv12[vout2]"
        )
    else:
        filter_complex = (
            f"[0:v]bwdif=mode=0:parity=-1:deint=0,split=2[v_b1][v_b4];"
            f"[v_b1]fps={fps_p1},scale={scale_p1}:flags=fast_bilinear,setsar=1,format=nv12[vout1];"
            f"[v_b4]fps={fps_p2},scale=852:480:flags=fast_bilinear,setsar=1,format=nv12[vout2]"
        )

    # ---- RETORNO DEL CÓDIGO GENERADO USANDO f""" ----
    return f"""#!/usr/bin/env python3
import subprocess
import sys
import re
import time
import signal

def iniciar_canal():
    # ==========================================
    # 1. PARÁMETROS ESTÁTICOS Y RED
    # ==========================================
    ORIGEN_IP = "{origen_ip}"
    ORIGEN_PORT = "{origen_port}"
    LOCADDRESS = "{locaddress}"
    DEST_IP = "{dest_ip}"
    DEST_P1 = "{dest_p1}"
    DEST_P4 = "{dest_p4}"
    AUDIO_MAP = "{audio_map}"

    # ==========================================
    # 2. URLs (Con interpolación interna)
    # ==========================================
    origen_url = f"udp://{{ORIGEN_IP}}:{{ORIGEN_PORT}}?localaddr={{LOCADDRESS}}&fifo_size=2000000&overrun_nonfatal=1&buffer_size=26214400&reorder_queue_size=2500" 
    dest_p1_url = f"udp://{{DEST_IP}}:{{DEST_P1}}?localaddr={{LOCADDRESS}}&fifo_size=1000000&buffer_size=8388608&reuse=1&pkt_size=1316&ttl=32" 
    dest_p4_url = f"udp://{{DEST_IP}}:{{DEST_P4}}?localaddr={{LOCADDRESS}}&fifo_size=1000000&buffer_size=8388608&reuse=1&pkt_size=1316&ttl=32"

    # ==========================================
    # 3. COMANDO FFMPEG
    # ==========================================
    comando = [
        "numactl", "--cpunodebind=0", "--membind=0",
        "/usr/bin/ffmpeg", "-hide_banner", "-loglevel", "info", "-y",
        "-fflags", "+genpts+discardcorrupt+igndts",
        "-err_detect", "ignore_err",
        "-thread_queue_size", "8192",
        "-filter_threads", "6",
        "-probesize", "4M",
        "-analyzeduration", "4M",
        "-ignore_unknown",
        "-async", "1",
        "-i", origen_url,

        "-filter_complex",
        "{filter_complex}",

        # PERFIL 1
        "-map", "[vout1]",
        "-c:v:0", "libx264", "-threads", "{threads_p1}", "-preset", "veryfast", "-profile:v:0", "high",
        "-b:v:0", "{bitrate_p1}", "-maxrate:v:0", "{bitrate_p1}", "-minrate:v:0", "{bitrate_p1}", "-bufsize:v:0", "6000k",
        "-g:v:0", "{gop_p1}", "-keyint_min:v:0", "{gop_p1}", "-sc_threshold:v:0", "0", "-bf:v:0", "3",
        "-x264-params:v:0", "nal-hrd=cbr:aud=1:force-cfr=1:open-gop=0:ref=2:rc-lookahead=10",
        "-map", "{audio_map}",
        "-c:a", "aac", "-profile:a", "aac_low", "-b:a", "128k", "-ar", "48000", "-ac", "2",
        "-af", "aresample=async=1:min_hard_comp=0.100000",
        "-max_muxing_queue_size", "9999", "-muxdelay", "0.7", "-muxpreload", "0.7", "-muxrate", "6M",
        "-f", "mpegts", "-mpegts_flags", "+resend_headers+pat_pmt_at_frames", "-pcr_period", "20",
        dest_p1_url,

        # PERFIL 2
        "-map", "[vout2]",
        "-c:v:0", "libx264", "-threads", "4", "-preset", "veryfast", "-profile:v:0", "high",
        "-b:v:0", "{bitrate_p4}", "-maxrate:v:0", "{bitrate_p4}", "-minrate:v:0", "{bitrate_p4}", "-bufsize:v:0", "3000k",
        "-g:v:0", "{gop_p2}", "-keyint_min:v:0", "{gop_p2}", "-sc_threshold:v:0", "0", "-bf:v:0", "3",
        "-x264-params:v:0", "nal-hrd=cbr:aud=1:force-cfr=1:open-gop=0:ref=2:rc-lookahead=10",
        "-max_muxing_queue_size", "9999", "-muxdelay", "0.7", "-muxpreload", "0.7", "-muxrate", "5M",
        "-f", "mpegts", "-mpegts_flags", "+resend_headers+pat_pmt_at_frames", "-pcr_period", "20",
        dest_p4_url
    ]

    # ==========================================
    # 4. ORQUESTADOR Y WATCHDOG
    # ==========================================
    while True:
        try:
            print(f"\\n[*] INICIANDO CANAL: {{origen_ip}}:{{origen_port}} -> {{dest_ip}}")
            proceso = subprocess.Popen(comando, stderr=subprocess.PIPE, universal_newlines=True)

            errores_velocidad = 0
            alertas_salto = 0

            for linea in proceso.stderr:
                sys.stdout.write(linea)
                sys.stdout.flush()

                if "speed=" in linea:
                    match = re.search(r"speed=\\s*([0-9.]+)x", linea)
                    if match:
                        velocidad = float(match.group(1))
                        if velocidad < 0.95:
                            errores_velocidad += 1
                        else:
                            errores_velocidad = 0

                        if errores_velocidad > 10:
                            print("\\n[!!!] ALARMA CRÍTICA: Velocidad sostenida por debajo de 0.95x.")
                            print("[!!!] Reiniciando FFmpeg para liberar buffer y CPU...")
                            proceso.terminate()
                            break

                if "timestamp discontinuity" in linea:
                    alertas_salto += 1
                    if alertas_salto > 20:
                        print("\\n[!!!] ALARMA CRÍTICA: Tormenta de discontinuidad de tiempo (origen corrupto).")
                        print("[!!!] Reiniciando FFmpeg para forzar resincronización...")
                        proceso.terminate()
                        break
                else:
                    alertas_salto = max(0, alertas_salto - 1)

            proceso.wait()

        except KeyboardInterrupt:
            print("\\n[*] Detención manual detectada (Control+C). Apagando canal...")
            if 'proceso' in locals():
                proceso.terminate()
            break

        except Exception as e:
            print(f"\\n[!] Error inesperado en Python: {{e}}")
            if 'proceso' in locals():
                proceso.terminate()

        print("[*] Esperando 3 segundos antes del reinicio automático...\\n")
        time.sleep(3)

if __name__ == "__main__":
    iniciar_canal()

# ---- fin del script ---- #

"""

# --------- #
# def generate_mac_encoder_bash(channel, node, include_subtitles=None, use_backup=False):
#     """Genera el script estático para un Encoder Linux usando libx264 por CPU"""

#     if use_backup and channel.origin_count > 1 and channel.origin2_multicast_ip and channel.origin2_multicast_port:
#         origen_ip = channel.origin2_multicast_ip
#         origen_port = channel.origin2_multicast_port
#     else:
#         origen_ip = channel.origin_multicast_ip
#         origen_port = channel.origin_multicast_port
#     fps_p1, gop_p1 = float(channel.fps_p1 or 30), int(channel.gop_p1 or 60)
#     fps_p2, gop_p2 = float(channel.fps_p2 or 30), int(channel.gop_p2 or 60)

#     locaddress = node.ip_multicast
#     dest_ip = channel.multicast_ip_out
#     dest_p1 = channel.port_1080p
#     dest_p4 = channel.port_480p
#     dest_pa = channel.port_audio

#     bitrate_p1 = channel.bitrate_p1.strip() if channel.bitrate_p1 else "5000k"
#     bitrate_p4 = channel.bitrate_p2.strip() if channel.bitrate_p2 else "2500k"
#     bitrate_m1 = channel.bitrate_high_max.strip() if channel.bitrate_high_max else "5000k"
#     bitrate_m4 = channel.bitrate_low_max.strip() if channel.bitrate_low_max else "2500k"
#     key_min_p1 = gop_p1 / 2
#     key_min_p4 = gop_p2 / 2

#     resolucion_bd = channel.resolution_p1 if channel.resolution_p1 else "1920x1080"
#     if resolucion_bd == "1280x720": scale_p1, threads_p1, bufsize_p1 = "1280:720", 4, "10M"
#     else: scale_p1, threads_p1, bufsize_p1 = "1920:1080", 6, "12M"

#     audio_map = channel.audio_mapping.strip() if channel.audio_mapping else "-map 0:a:0"

#     burn_subs = include_subtitles if include_subtitles is not None else channel.burn_subtitles
#     subtitle_var, filter_complex = "", ""
#     if burn_subs and channel.subtitle_pid is not None:
#         subtitle_var = f'SUBTITLE="{channel.subtitle_pid}"\n'
# #         filter_complex = f"""[0:v]yadif=mode=0:parity=-1:deint=0,fps=$FPS_P1[v_deint]; \\
# # [v_deint][0:s:$SUBTITLE]overlay=eof_action=pass:repeatlast=0[v_subbed]; \\
# # [v_subbed]split=2[v_b1][v_b4]; \\
# # [v_b1]scale={scale_p1}:flags=fast_bilinear,setsar=1,format=yuv420p[vout1]; \\
# # [v_b4]fps=$FPS_P2,scale=852:480:flags=fast_bilinear,setsar=1,format=yuv420p[vout2]"""
#         filter_complex = f"""[0:v]bwdif=mode=0:parity=-1:deint=1,setpts=PTS-STARTPTS[v_st]; \\
# [0:$SUBTITLE]setpts=PTS-STARTPTS[sub_synced]; \\
# [v_subbed]split=2[v_b1][v_b4]; \\
# [v_st][sub_synced]overlay=x=0:y=0:eof_action=pass[v_burned]; \\
# [v_burned]split=2[v_b1][v_b4]; \\
# [v_b1]scale={scale_p1}:flags=fast_bilinear,fps=$FPS_P1,format=nv12[vout1]; \\
# [v_b4]scale=852:480:flags=fast_bilinear,fps=$FPS_P2,format=nv12[vout2]"""

#     else:
# #         filter_complex = f"""[0:v]yadif=mode=0:parity=-1:deint=0,split=2[v_b1][v_b4]; \\
# # [v_b1]fps=$FPS_P1,scale={scale_p1}:flags=fast_bilinear,setsar=1,format=yuv420p[vout1]; \\
# # [v_b4]fps=$FPS_P2,scale=852:480:flags=fast_bilinear,setsar=1,format=yuv420p[vout2]"""
#         filter_complex = f"""[0:v]bwdif=mode=0:parity=-1:deint=1,split=2[v_b1][v_b4]; \\
# [v_b1]scale={scale_p1}:flags=fast_bilinear,fps=$FPS_P1,format=nv12[vout1]; \\
# [v_b4]scale=852:480:flags=fast_bilinear,fps=$FPS_P2,format=nv12[vout2]"""

#     return f"""#!/bin/bash
# set -euo pipefail

# # ---- parametros estaticos ---- #
# ORIGEN_IP="{origen_ip}"
# ORIGEN_PORT="{origen_port}"
# FPS_P1="{fps_p1}"
# GOP_P1="{gop_p1}"
# FPS_P2="{fps_p2}"
# GOP_P2="{gop_p2}"
# LOCADDRESS="{locaddress}"
# DEST_IP="{dest_ip}"
# DEST_P1="{dest_p1}"
# DEST_P4="{dest_p4}"
# DEST_PA="{dest_pa}"
# AUDIO_MAP="{audio_map}"
# {subtitle_var}
# # ---- #
# ORIGEN_URL="udp://$ORIGEN_IP:$ORIGEN_PORT?localaddr=$LOCADDRESS&fifo_size=2000000&overrun_nonfatal=1&buffer_size=26214400"
# DEST_P1="udp://$DEST_IP:$DEST_P1?localaddr=$LOCADDRESS&fifo_size=65536&buffer_size=65536&reuse=1&pkt_size=1316&ttl=32"
# DEST_P4="udp://$DEST_IP:$DEST_P4?localaddr=$LOCADDRESS&fifo_size=65536&buffer_size=65536&reuse=1&pkt_size=1316&ttl=32"
# # ---- #

# /opt/homebrew/bin/ffmpeg -hide_banner -loglevel info  -y \\
# -fflags nobuffer -flags low_delay \\
# -probesize 2M -analyzeduration 2M  \\
# -i "$ORIGEN_URL" \\
# -filter_complex \\
# "{filter_complex}" \\
# \\
# -map "[vout1]" \\
# $AUDIO_MAP \\
# -c:v h264_videotoolbox -profile:v main \\
# -b:v {bitrate_p1} -maxrate {bitrate_m1} -bufsize {bitrate_m1} \\
# -g {gop_p1} -keyint_min {gop_p1}  -color_range tv \\
# -allow_sw 0 -realtime 1 -fps_mode cfr \\
# -bsf:v h264_mp4toannexb \\
# -c:a aac -b:a 128k -ar 48000 \\
# -muxdelay 0 -muxpreload 0 -flush_packets 1 -max_delay 0 \\
# -f mpegts -mpegts_flags +initial_discontinuity+resend_headers -mpegts_copyts 1 \\
# "$DEST_P1" \\
# -map "[vout2]" \\
# -c:v h264_videotoolbox -profile:v main \\
# -b:v {bitrate_p4} -maxrate {bitrate_m4} -bufsize {bitrate_m4} \\
# -g {gop_p2} -keyint_min {gop_p2}  -color_range tv \\
# -allow_sw 0 -realtime 1 -fps_mode cfr \\
# -bsf:v h264_mp4toannexb \\
# -muxdelay 0 -muxpreload 0 -flush_packets 1 -max_delay 0 \\
# -f mpegts -mpegts_flags +initial_discontinuity+resend_headers -mpegts_copyts 1 \\
# "$DEST_P4"

# # ---- #

# """

def generate_mac_encoder_bash(channel, node, include_subtitles=None, use_backup=False):
    """Genera el script estático para un Encoder Mac usando VideoToolbox mediante Python"""

    if use_backup and channel.origin_count > 1 and channel.origin2_multicast_ip and channel.origin2_multicast_port:
        origen_ip = channel.origin2_multicast_ip
        origen_port = channel.origin2_multicast_port
    else:
        origen_ip = channel.origin_multicast_ip
        origen_port = channel.origin_multicast_port
        
    fps_p1, gop_p1 = float(channel.fps_p1 or 29.97), int(channel.gop_p1 or 120)
    fps_p2, gop_p2 = float(channel.fps_p2 or 29.97), int(channel.gop_p2 or 120)
    if fps_p1 == 30.0:
        fps = "30000/1001"
    else:
        fps = "60000/1001"

    locaddress = node.ip_multicast
    dest_ip = channel.multicast_ip_out
    dest_p1 = channel.port_1080p
    dest_p4 = channel.port_480p

    bitrate_p1 = channel.bitrate_p1.strip() if channel.bitrate_p1 else "5000k"
    bitrate_p4 = channel.bitrate_p2.strip() if channel.bitrate_p2 else "2500k"
    bitrate_m1 = channel.bitrate_high_max.strip() if channel.bitrate_high_max else "5000k"
    bitrate_m4 = channel.bitrate_low_max.strip() if channel.bitrate_low_max else "2500k"

    resolucion_bd = channel.resolution_p1 if channel.resolution_p1 else "1920x1080"
    if resolucion_bd == "1280x720": 
        scale_p1 = "1280:720"
    else: 
        scale_p1 = "1920:1080"

    # Procesamos el mapeo de audio para que encaje en la lista del script generado
    audio_map = channel.audio_mapping.strip() if channel.audio_mapping else "-map 0:a:0"
    audio_map_list_str = ",\n        ".join([f'"{part}"' for part in audio_map.split()])

    burn_subs = include_subtitles if include_subtitles is not None else channel.burn_subtitles
    if burn_subs and channel.subtitle_pid is not None:
        sub_pid = channel.subtitle_pid
        filter_complex = f"[0:v]bwdif=mode=0:parity=-1:deint=1[v_st];[v_st][0:{sub_pid}]overlay=x=0:y=0:eof_action=pass[v_burned];[v_burned]split=2[v_b1][v_b4];[v_b1]scale={scale_p1}:flags=fast_bilinear,setsar=1,fps={fps},format=nv12[vout1];[v_b4]scale=852:480:flags=fast_bilinear,setsar=1,fps={fps},format=nv12[vout2]"
    else:
        filter_complex = f"[0:v]bwdif=mode=0:parity=-1:deint=1,split=2[v_b1][v_b4]; [v_b1]scale={scale_p1}:flags=fast_bilinear,setsar=1,fps={fps},format=nv12[vout1]; [v_b4]scale=852:480:flags=fast_bilinear,setsar=1,fps={fps},format=nv12[vout2]"

    # Retornamos el script de Python directamente. 
    # IMPORTANTE: Observa que las llaves en la línea del print del error están escapadas como {{e}}
    return f"""#!/usr/bin/env python3
import subprocess
import sys
import time
import signal

keep_running = True
ffmpeg_process = None

def handle_termination_signal(signum, frame):
    global keep_running, ffmpeg_process
    print("\\n[Orquestador] Señal de apagado recibida. Deteniendo el flujo de manera segura...")
    keep_running = False
    if ffmpeg_process and ffmpeg_process.poll() is None:
        ffmpeg_process.terminate()

def run_transcoder():
    global keep_running, ffmpeg_process
    
    ORIGEN_URL = "udp://{origen_ip}:{origen_port}?localaddr={locaddress}&fifo_size=2000000&overrun_nonfatal=1&buffer_size=26214400" 
    DEST_P1_URL = "udp://{dest_ip}:{dest_p1}?localaddr={locaddress}&fifo_size=65536&buffer_size=65536&reuse=1&pkt_size=1316&ttl=32" 
    DEST_P4_URL = "udp://{dest_ip}:{dest_p4}?localaddr={locaddress}&fifo_size=65536&buffer_size=65536&reuse=1&pkt_size=1316&ttl=32"

    ffmpeg_cmd = [
        "/opt/homebrew/bin/ffmpeg",
        "-hide_banner",
        "-loglevel", "info",
        "-y",
        "-use_wallclock_as_timestamps", "1",
        #"-fflags", "+genpts+discardcorrupt",
        "-fflags", "+discardcorrupt",
        "-flags", "low_delay",
        "-probesize", "5M",
        "-analyzeduration", "5M",
        "-ignore_unknown",
        "-i", ORIGEN_URL,
        
        "-filter_complex", 
        "{filter_complex}",
        
        "-map", "[vout1]",
        "-map", {audio_map_list_str},
        
        "-c:v", "h264_videotoolbox",
        "-profile:v", "main",
        "-b:v", "{bitrate_p1}",
        "-maxrate", "{bitrate_m1}",
        "-bufsize", "{bitrate_m1}",
        "-g", "{gop_p1}",
        "-keyint_min", "{gop_p1}",
        #"-sc_threshold", "0",
        "-color_range", "tv",
        "-allow_sw", "0",
        "-realtime", "1",
        "-fps_mode", "cfr",
        "-bsf:v", "h264_mp4toannexb",
        
        "-c:a", "aac",
        "-max_muxing_queue_size", "9999",
        "-b:a", "128k",
        "-ar", "48000",
        #"-af", "aresample=async=1:min_hard_comp=0.100000",
        "-af", "aresample=48000:first_pts=0",
        #"-af", "aresample=48000:async=1000:first_pts=0",
        
        "-muxdelay", "0.7",
        "-muxpreload", "0.7",
        "-muxrate", "5.5M",
        "-f", "mpegts",
        #"-mpegts_flags", "+resend_headers+pat_pmt_at_frames",
        "-mpegts_flags", "+initial_discontinuity+resend_headers",
        "-pcr_period", "20",
        DEST_P1_URL,
        
        "-map", "[vout2]",
        "-c:v", "h264_videotoolbox",
        "-profile:v", "main",
        "-b:v", "{bitrate_p4}",
        "-maxrate", "{bitrate_m4}",
        "-bufsize", "{bitrate_m4}",
        "-g", "{gop_p2}",
        "-keyint_min", "{gop_p2}",
        #"-sc_threshold", "0",
        "-color_range", "tv",
        "-allow_sw", "0",
        "-realtime", "1",
        "-fps_mode", "cfr",
        "-bsf:v", "h264_mp4toannexb",
        
        "-muxdelay", "0.7",
        "-muxpreload", "0.7",
        "-muxrate", "3.5M",
        "-f", "mpegts",
        #"-mpegts_flags", "+resend_headers+pat_pmt_at_frames",
        "-mpegts_flags", "+initial_discontinuity+resend_headers",
        "-pcr_period", "20",
        DEST_P4_URL
    ]

    signal.signal(signal.SIGINT, handle_termination_signal)
    signal.signal(signal.SIGTERM, handle_termination_signal)
    
    print("[Orquestador] Servicio de Transcodificación Iniciado con Auto-Recuperación.")
    
    while keep_running:
        print("[Orquestador] Lanzando FFmpeg...")
        try:
            ffmpeg_process = subprocess.Popen(
                ffmpeg_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True
            )
            
            discontinuity_counter = 0
            
            for line in ffmpeg_process.stdout:
                sys.stdout.write(line)
                sys.stdout.flush()
                
                if "timestamp discontinuity" in line:
                    discontinuity_counter += 1
                    if discontinuity_counter > 20:
                        print("\\n[ALERTA CRÍTICA] Exceso de discontinuidades detectado.")
                        print("[ORQUESTADOR] Forzando reinicio para limpiar relojes...\\n")
                        ffmpeg_process.terminate()
                        break
                        
            ffmpeg_process.wait()
            
        except Exception as e:
            # Aquí usamos el doble escape para que no falle el F-String en el backend
            print(f"[Orquestador] Error al invocar el binario: {{e}}")
        
        if keep_running:
            print("[Orquestador] Levantando servicio nuevamente en 5 segundos...\\n")
            time.sleep(5)
        else:
            print("[Orquestador] Apagado completado exitosamente.")

if __name__ == "__main__":
    run_transcoder()
"""


# --------- #
def compress_command(script):
    import zlib, base64
    return base64.b64encode(zlib.compress(script.encode('utf-8'))).decode('utf-8')


# ----  fin de archivo ---- #