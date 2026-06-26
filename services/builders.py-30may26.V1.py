from core.logging_service import logger
from core.config import OFFLINE_IP, OFFLINE_PORT

def parse_shaka_bw(bw_str, default="6000000"):
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
    canal = getattr(channel, "ruta", None) or getattr(channel, "channel_name", None) or "canal"
    canal = str(canal).strip()
    interface = node.ip_multicast
    output_dir = f"/storage/live/{canal}"

    bw_p1 = parse_shaka_bw(channel.bitrate_high_max, "6000000")
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
# ---- #
exec packager \\
  "in=udp://$ORIGEN:$PORT?interface=$INTERFACE&reuse=1,stream=video,init_segment=$OUTPUT_DIR/v1_init.mp4,segment_template=$OUTPUT_DIR/v1_\\$Time\\$.m4s,bw={bw_p2}" \\
  "in=udp://$ORIGEN:$PORT?interface=$INTERFACE&reuse=1,stream=audio,init_segment=$OUTPUT_DIR/a0_init.mp4,segment_template=$OUTPUT_DIR/a0_\\$Time\\$.m4s,language=spa,hls_group_id=audio,hls_name=Español,bw=128000" \\
  --default_language=es \\
  --time_shift_buffer_depth 21600 \\
  --segment_duration {segment_duration} \\
  --fragment_duration {segment_duration} \\
  --minimum_update_period {segment_duration} \\
  --suggested_presentation_delay 18 \\
  --allow_approximate_segment_timeline \\
  --utc_timings="urn:mpeg:dash:utc:http-iso:2014=https://time.akamai.com/?iso" \\
  --generate_static_mpd=false \\
  --mpd_output "$OUTPUT_DIR/$CANAL.mpd" \\
  --io_block_size 256000
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
# ---- #
mkdir -p "$OUTPUT_DIR"
# ---- #
exec packager \\
  "in=udp://$ORIGEN:$PORT1?interface=$INTERFACE&reuse=1&buffer_size=8388608,stream=video,init_segment=$OUTPUT_DIR/v1_init.mp4,segment_template=$OUTPUT_DIR/v1_\\$Time\\$.m4s,bw={bw_p1}" \\
  "in=udp://$ORIGEN:$PORT4?interface=$INTERFACE&reuse=1&buffer_size=8388608,stream=video,init_segment=$OUTPUT_DIR/v4_init.mp4,segment_template=$OUTPUT_DIR/v4_\\$Time\\$.m4s,bw={bw_p2}" \\
  "in=udp://$ORIGEN:$PORTA?interface=$INTERFACE&reuse=1&buffer_size=8388608,stream=audio,init_segment=$OUTPUT_DIR/a0_init.mp4,segment_template=$OUTPUT_DIR/a0_\\$Time\\$.m4s,language=spa,hls_group_id=audio,hls_name=Español,bw=192000" \\
  --default_language=spa \\
  --time_shift_buffer_depth 21600 \\
  --segment_duration {segment_duration} \\
  --fragment_duration {segment_duration} \\
  --minimum_update_period {segment_duration} \\
  --suggested_presentation_delay {suggested} \\
  --allow_approximate_segment_timeline \\
  --utc_timings="urn:mpeg:dash:utc:http-iso:2014=https://time.akamai.com/?iso" \\
  --generate_static_mpd=false \\
  --mpd_output "$OUTPUT_DIR/$CANAL.mpd" \\
  --io_block_size 512000
# ---- #

"""

# --------- #
def generate_packager_drm_bash(channel, node):
    """Genera el script de Packager con DRM y llamadas a KMS"""
    canal = getattr(channel, "ruta", None) or getattr(channel, "channel_name", None) or "canal"
    canal = str(canal).strip()
    interface = node.ip_multicast
    output_dir = f"/storage/live/{canal}"

    bw_p1 = parse_shaka_bw(channel.bitrate_high_max, "5000000")
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
  "in=udp://$ORIGEN:$PORT1?interface=$INTERFACE&reuse=1&buffer_size=8388608,stream=video,init_segment=$OUTPUT_DIR/v1_init.mp4,segment_template=$OUTPUT_DIR/v1_\\$Time\\$.m4s,bw={bw_p1},drm_label=HD" \\
  "in=udp://$ORIGEN:$PORT4?interface=$INTERFACE&reuse=1&buffer_size=8388608,stream=video,init_segment=$OUTPUT_DIR/v4_init.mp4,segment_template=$OUTPUT_DIR/v4_\\$Time\\$.m4s,bw={bw_p2},drm_label=SD" \\
  "in=udp://$ORIGEN:$PORTA?interface=$INTERFACE&reuse=1&buffer_size=8388608,stream=audio,init_segment=$OUTPUT_DIR/a0_init.mp4,segment_template=$OUTPUT_DIR/a0_\\$Time\\$.m4s,language=spa,hls_group_id=audio,hls_name=Español,bw=192000,drm_label=AUDIO" \\
  --enable_raw_key_encryption \\
  --keys label=AUDIO:key_id=$KID:key=$KEY,label=SD:key_id=$KID:key=$KEY,label=HD:key_id=$KID:key=$KEY \\
  --protection_systems Widevine \\
  --default_language=spa \\
  --time_shift_buffer_depth 21600 \\
  --segment_duration {segment_duration} \\
  --fragment_duration {segment_duration} \\
  --minimum_update_period {segment_duration} \\
  --suggested_presentation_delay {suggested} \\
  --allow_approximate_segment_timeline \\
  --utc_timings="urn:mpeg:dash:utc:http-iso:2014=https://time.akamai.com/?iso" \\
  --generate_static_mpd=false \\
  --mpd_output "$OUTPUT_DIR/$CANAL.mpd" \\
  --io_block_size 512000

  # ---- #
"""

# --------- #
def generate_linux_encoder_bash(channel, node, include_subtitles=None):
    """Genera el script estático para un Encoder Linux usando libx264 por CPU"""
    origen_ip = channel.origin_multicast_ip
    origen_port = channel.origin_multicast_port
    fps_p1, gop_p1 = float(channel.fps_p1 or 30), int(channel.gop_p1 or 60)
    fps_p2, gop_p2 = float(channel.fps_p2 or 30), int(channel.gop_p2 or 60)
    
    locaddress = node.ip_multicast
    dest_ip = channel.multicast_ip_out
    dest_p1 = channel.port_1080p
    dest_p4 = channel.port_480p
    dest_pa = channel.port_audio
    
    bitrate_p1 = channel.bitrate_p1.strip() if channel.bitrate_p1 else "5500k"                  
    bitrate_p4 = channel.bitrate_p2.strip() if channel.bitrate_p2 else "2000k"                  
    bitrate_m1 = channel.bitrate_high_max.strip() if channel.bitrate_high_max else "6000k"      
    bitrate_m4 = channel.bitrate_low_max.strip() if channel.bitrate_low_max else "2500k"        
    

    resolucion_bd = channel.resolution_p1 if channel.resolution_p1 else "1920x1080"
    if resolucion_bd == "1280x720": scale_p1, threads_p1, bufsize_p1 = "1280:720", 4, "10M"
    else: scale_p1, threads_p1, bufsize_p1 = "1920:1080", 6, "12M"

    audio_map = channel.audio_mapping.strip() if channel.audio_mapping else "-map 0:a:0"
    
    burn_subs = include_subtitles if include_subtitles is not None else channel.burn_subtitles
    subtitle_var, filter_complex = "", ""
    if burn_subs and channel.subtitle_pid is not None:
        subtitle_var = f'SUBTITLE="{channel.subtitle_pid}"\n'
        filter_complex = f"""[0:v]yadif=mode=0:parity=-1:deint=0,fps=$FPS_P1[v_deint]; \\
[v_deint][0:s:$SUBTITLE]overlay=eof_action=pass:repeatlast=0[v_subbed]; \\
[v_subbed]split=2[v_base1][v_base2]; \\
[v_base1]scale={scale_p1}:flags=fast_bilinear,setsar=1,format=yuv420p[vout1]; \\
[v_base2]fps=$FPS_P2,scale=852:480:flags=fast_bilinear,setsar=1,format=yuv420p[vout2]"""
    else:
        filter_complex = f"""[0:v]yadif=mode=0:parity=-1:deint=0,split=2[v_base1][v_base2]; \\
[v_base1]fps=$FPS_P1,scale={scale_p1}:flags=fast_bilinear,setsar=1,format=yuv420p[vout1]; \\
[v_base2]fps=$FPS_P2,scale=852:480:flags=fast_bilinear,setsar=1,format=yuv420p[vout2]"""

    return f"""#!/bin/bash

# ---- #
ORIGEN_IP="{origen_ip}"
ORIGEN_PORT="{origen_port}"
FPS_P1="{fps_p1}"
GOP_P1="{gop_p1}"
FPS_P2="{fps_p2}"
GOP_P2="{gop_p2}"
LOCADDRESS="{locaddress}"
DEST_IP="{dest_ip}"
DEST_P1="{dest_p1}"
DEST_P4="{dest_p4}"
DEST_PA="{dest_pa}"
AUDIO_MAP="{audio_map}"
{subtitle_var}
# ---- #
exec numactl --cpunodebind=0 --membind=0 \\
/usr/bin/ffmpeg -hide_banner -loglevel info -y \\
 -fflags +genpts+discardcorrupt -thread_queue_size 8192 -filter_threads 6 \\
 -probesize 2M -analyzeduration 2M -ignore_unknown \\
 -i "udp://$ORIGEN_IP:$ORIGEN_PORT?localaddr=$LOCADDRESS&fifo_size=2000000&overrun_nonfatal=1&buffer_size=8388608&reorder_queue_size=2500" \\
 -filter_complex " \\
 {filter_complex}" \\
\\
-map "[vout1]" -c:v:0 libx264 -threads {threads_p1} -preset fast -profile:v:0 high \\
-b:v:0 {bitrate_p1} -maxrate:v:0 {bitrate_m1} -minrate:v:0 {bitrate_p1} -bufsize:v:0 {bitrate_m1} \\
-g:v:0 $GOP_P1 -keyint_min:v:0 $GOP_P1 -sc_threshold:v:0 0 -bf:v:0 3 \\
-x264-params:v:0 "nal-hrd=cbr:aud=1:force-cfr=1:open-gop=0:ref=2" \\
$AUDIO_MAP -c:a aac -profile:a aac_low -b:a 128k -ar 48000 -ac 2 -af "aresample=async=1:min_hard_comp=0.100000" \\
-muxdelay 0.7 -muxpreload 0.7 -muxrate 6M \\
-f mpegts -mpegts_flags +resend_headers+pat_pmt_at_frames -pcr_period 20 \\
"udp://$DEST_IP:$DEST_P1?localaddr=$LOCADDRESS&pkt_size=1316&fifo_size=1000000&buffer_size=8388608&ttl=32" \\
\\
-map "[vout2]" -c:v:0 libx264 -threads 4 -preset fast -profile:v:0 high \\
-b:v:0 {bitrate_p4} -maxrate:v:0 {bitrate_m4} -minrate:v:0 {bitrate_p4} -bufsize:v:0 {bitrate_m4} \\
-g:v:0 $GOP_P2 -keyint_min:v:0 $GOP_P2 -sc_threshold:v:0 0 -bf:v:0 3 \\
-x264-params:v:0 "nal-hrd=cbr:aud=1:force-cfr=1:open-gop=0:ref=2" \\
-muxdelay 0.7 -muxpreload 0.7 -muxrate 5M \\
-f mpegts -mpegts_flags +resend_headers+pat_pmt_at_frames -pcr_period 20 \\
"udp://$DEST_IP:$DEST_P4?localaddr=$LOCADDRESS&pkt_size=1316&fifo_size=1000000&buffer_size=8388608&ttl=32"
# ---- #


"""

# --------- #


