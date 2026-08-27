#!/usr/bin/env python3
"""
Signal Analyzer & Encoding Script Generator (Cross-Platform)
Fase 1: Analiza la senal de origen durante 5 minutos
Fase 2: Genera el script de encoding optimizado basado en el analisis

Detecta automaticamente el SO y usa:
  - macOS: h264_videotoolbox (hardware)
  - Linux: libx264 (software, preset veryfast)

Uso: python3 signal_analyzer.py <source_url> <local_ip> <dest_multicast> [opciones]
"""

import subprocess
import sys
import os
import json
import time
import signal
import re
import platform
import shutil
from datetime import datetime
from pathlib import Path


# ============================================================
# CONFIGURACION CROSS-PLATFORM
# ============================================================

PLATFORM = platform.system()  # "Darwin" o "Linux"

# Buscar ffmpeg en el PATH o usar ruta por defecto
FFMPEG = shutil.which("ffmpeg") or ("/opt/homebrew/bin/ffmpeg" if PLATFORM == "Darwin" else "/usr/bin/ffmpeg")
FFPROBE = shutil.which("ffprobe") or ("/opt/homebrew/bin/ffprobe" if PLATFORM == "Darwin" else "/usr/bin/ffprobe")

ANALYSIS_DURATION = 300  # 5 minutos en segundos
ANALYSIS_OUTPUT = os.path.join(os.path.expanduser("~"), "signal_analysis.json")
SCRIPT_OUTPUT = os.path.join(os.path.expanduser("~"), "encoder_script.py")


def build_url(base_url, local_ip, extra_params=""):
    """Construye URL con localaddr. Usa ? si no hay query, & si ya existe."""
    separator = "&" if "?" in base_url else "?"
    url = f"{base_url}{separator}localaddr={local_ip}"
    if extra_params:
        url += f"&{extra_params}"
    return url


class C:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BOLD = '\033[1m'
    END = '\033[0m'


def log(msg, level="INFO"):
    colors = {"INFO": C.CYAN, "OK": C.GREEN, "WARN": C.YELLOW, "ERR": C.RED, "PHASE": C.BOLD}
    color = colors.get(level, C.END)
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"{color}[{ts}][{level}] {msg}{C.END}")


def get_encoder_config():
    """Retorna configuracion del encoder segun el plataforma."""
    if PLATFORM == "Darwin":
        return {
            "name": "h264_videotoolbox",
            "type": "hardware",
            "extra_args": ["-allow_sw", "0", "-realtime", "1"],
            "preset_arg": [],
            "profile_arg": ["-profile:v", "main"],
        }
    else:  # Linux
        return {
            "name": "libx264",
            "type": "software",
            "extra_args": ["-preset", "veryfast", "-tune", "zerolatency"],
            "preset_arg": [],
            "profile_arg": ["-profile:v", "main", "-x264-params", "keyint=120:min-keyint=120:scenecut=0:open-gop=0:nal-hrd=cbr"],
        }


# ============================================================
# FASE 1: ANALISIS DE LA SENAL
# ============================================================

def analyze_source(source_url, local_ip, duration=ANALYSIS_DURATION, gop_p1=60, audio_mapping="0:a:0"):
    """Analiza la senal de origen y retorna metricas completas."""
    
    log(f"Plataforma detectada: {PLATFORM} ({'VideoToolbox' if PLATFORM == 'Darwin' else 'libx264'})", "PHASE")
    log(f"FFmpeg: {FFMPEG}", "INFO")
    log(f"Iniciando analisis de {duration}s sobre: {source_url}", "PHASE")
    log("=" * 60, "PHASE")
    
    analysis = {
        "timestamp": datetime.now().isoformat(),
        "platform": PLATFORM,
        "encoder": "h264_videotoolbox" if PLATFORM == "Darwin" else "libx264",
        "source_url": source_url,
        "local_ip": local_ip,
        "analysis_duration": duration,
        "video": {},
        "audio_streams": [],
        "quality": {},
        "warnings": [],
        "recommendations": []
    }
    
    # --- Paso 1: ffprobe rapido para metadata ---
    log("Paso 1/4: Obteniendo metadata del stream...", "INFO")
    probe_data = ffprobe_streams(source_url, local_ip)
    if not probe_data:
        log("No se pudo obtener metadata del stream", "ERR")
        return None
    
    analysis["video"] = probe_data["video"]
    analysis["audio_streams"] = probe_data["audio"]
    
    # --- Paso 2: Captura extendida para analisis de calidad ---
    log(f"Paso 2/4: Capturando {duration}s para analisis de calidad...", "INFO")
    quality_data = capture_and_analyze(source_url, local_ip, duration)
    analysis["quality"] = quality_data
    
    # --- Paso 3: Deteccion de interlacing ---
    log("Paso 3/4: Detectando interlacing...", "INFO")
    interlace_data = detect_interlacing(source_url, local_ip)
    analysis["video"]["interlaced"] = interlace_data["interlaced"]
    analysis["video"]["interlace_type"] = interlace_data["type"]
    
    # --- Paso 4: Generar recomendaciones ---
    log("Paso 4/4: Generando recomendaciones...", "INFO")
    analysis["recommendations"] = generate_recommendations(analysis, gop_p1=gop_p1, audio_mapping=audio_mapping)
    analysis["warnings"] = generate_warnings(analysis)
    
    # Guardar analisis
    with open(ANALYSIS_OUTPUT, 'w') as f:
        json.dump(analysis, f, indent=2, ensure_ascii=False)
    
    log(f"Analisis guardado en: {ANALYSIS_OUTPUT}", "OK")
    print_analysis_summary(analysis)
    
    return analysis


def ffprobe_streams(source_url, local_ip):
    """Obtiene metadata de todos los streams via ffprobe."""
    
    full_url = build_url(source_url, local_ip)
    
    cmd = [
        FFPROBE,
        "-hide_banner",
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        "-analyzeduration", "10000000",
        "-probesize", "10000000",
        full_url
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            log(f"ffprobe error: {result.stderr[:200]}", "ERR")
            return None
        
        data = json.loads(result.stdout)
        
        video_info = {}
        audio_streams = []
        
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                video_info = {
                    "codec": stream.get("codec_name", "unknown"),
                    "profile": stream.get("profile", "unknown"),
                    "width": stream.get("width", 0),
                    "height": stream.get("height", 0),
                    "fps_raw": stream.get("r_frame_rate", "0/1"),
                    "fps_eval": eval(stream.get("r_frame_rate", "0/1")) if "/" in stream.get("r_frame_rate", "0/1") else 0,
                    "pix_fmt": stream.get("pix_fmt", "unknown"),
                    "color_range": stream.get("color_range", "unknown"),
                    "color_space": stream.get("color_space", "unknown"),
                    "color_transfer": stream.get("color_transfer", "unknown"),
                    "color_primaries": stream.get("color_primaries", "unknown"),
                    "bit_rate": int(stream.get("bit_rate", 0)),
                    "start_time": float(stream.get("start_time", 0)),
                    "sar": stream.get("sample_aspect_ratio", "1:1"),
                    "dar": stream.get("display_aspect_ratio", "unknown"),
                    "refs": stream.get("refs", 0),
                    "has_b_frames": stream.get("has_b_frames", 0),
                }
            
            elif stream.get("codec_type") == "audio":
                audio_streams.append({
                    "index": stream.get("index", 0),
                    "stream_id": stream.get("index", 0) - 1,
                    "codec": stream.get("codec_name", "unknown"),
                    "profile": stream.get("profile", "unknown"),
                    "sample_rate": int(stream.get("sample_rate", 0)),
                    "channels": stream.get("channels", 0),
                    "channel_layout": stream.get("channel_layout", "unknown"),
                    "bit_rate": int(stream.get("bit_rate", 0)),
                    "language": stream.get("tags", {}).get("language", "und"),
                    "start_time": float(stream.get("start_time", 0)),
                })
        
        return {"video": video_info, "audio": audio_streams}
        
    except subprocess.TimeoutExpired:
        log("ffprobe timeout - el stream no responde", "ERR")
        return None
    except Exception as e:
        log(f"Error en ffprobe: {e}", "ERR")
        return None


def capture_and_analyze(source_url, local_ip, duration):
    """Captura durante el analisis y recopila metricas de calidad."""
    
    full_url = build_url(source_url, local_ip)
    
    cmd = [
        FFMPEG,
        "-hide_banner",
        "-v", "info",
        "-fflags", "+genpts+discardcorrupt",
        "-flags", "low_delay",
        "-probesize", "5M",
        "-analyzeduration", "5M",
        "-i", full_url,
        "-t", str(duration),
        "-f", "null",
        "-"
    ]
    
    quality = {
        "frames_total": 0,
        "frames_video": 0,
        "frames_audio": 0,
        "dup_count": 0,
        "drop_count": 0,
        "discontinuity_count": 0,
        "decode_errors": 0,
        "timestamp_errors": 0,
        "speed_factor": 0,
        "avg_fps": 0,
        "avg_bitrate_kbps": 0,
        "timestamps": [],
    }
    
    try:
        log(f"Captura iniciada - esperando {duration}s de stream...", "INFO")
        log("(Si no ves progreso, verifica que el stream UDP este activo)", "WARN")
        
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True
        )
        
        discontinuity_count = 0
        decode_errors = 0
        timestamp_errors = 0
        start_time = time.time()
        last_progress = 0
        
        for line in proc.stdout:
            elapsed = time.time() - start_time
            progress_pct = min(100, int(elapsed / duration * 100))
            if progress_pct >= last_progress + 10:
                remaining = max(0, duration - elapsed)
                log(f"Progreso: {progress_pct}% ({int(elapsed)}s / {duration}s) - quedan ~{int(remaining)}s", "INFO")
                last_progress = progress_pct
            
            if "timestamp discontinuity" in line:
                discontinuity_count += 1
            if "mmco: unref short failure" in line:
                decode_errors += 1
            if "number of reference frames" in line:
                decode_errors += 1
            if "dts < pcr" in line:
                timestamp_errors += 1
            if "Non-monotonic" in line:
                timestamp_errors += 1
            
            frame_match = re.search(r'frame=\s*(\d+)', line)
            if frame_match:
                quality["frames_total"] = int(frame_match.group(1))
            fps_match = re.search(r'fps=\s*([\d.]+)', line)
            if fps_match:
                quality["avg_fps"] = float(fps_match.group(1))
            time_match = re.search(r'time=(\d+:\d+:\d+\.\d+)', line)
            if time_match:
                quality["elapsed_time"] = time_match.group(1)
            dup_match = re.search(r'dup=(\d+)', line)
            if dup_match:
                quality["dup_count"] = int(dup_match.group(1))
            drop_match = re.search(r'drop=(\d+)', line)
            if drop_match:
                quality["drop_count"] = int(drop_match.group(1))
            speed_match = re.search(r'speed=\s*([\d.]+)x', line)
            if speed_match:
                quality["speed_factor"] = float(speed_match.group(1))
            bitrate_match = re.search(r'bitrate=\s*([\d.]+)kbits/s', line)
            if bitrate_match:
                quality["avg_bitrate_kbps"] = float(bitrate_match.group(1))
        
        proc.wait()
        
        quality["discontinuity_count"] = discontinuity_count
        quality["decode_errors"] = decode_errors
        quality["timestamp_errors"] = timestamp_errors
        
        total_time = int(time.time() - start_time)
        log(f"Captura completada en {total_time}s - {quality['frames_total']} frames analizados", "OK")
        
    except Exception as e:
        log(f"Error durante captura: {e}", "ERR")
    
    return quality


def detect_interlacing(source_url, local_ip, sample_duration=10):
    """Detecta si el source es interlaced analizando una muestra corta."""
    
    full_url = build_url(source_url, local_ip)
    
    cmd = [
        FFMPEG,
        "-hide_banner",
        "-v", "info",
        "-fflags", "+genpts",
        "-probesize", "5M",
        "-analyzeduration", "5M",
        "-i", full_url,
        "-t", str(sample_duration),
        "-vf", "idet",
        "-an",
        "-f", "null",
        "-"
    ]
    
    result = {"interlaced": False, "type": "progressive", "tff": 0, "bff": 0, "progressive": 0, "undetermined": 0}
    
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True
        )
        
        for line in proc.stdout:
            idet_match = re.search(
                r'Single frame detection:.*?TFF:\s*(\d+).*?BFF:\s*(\d+).*?Progressive:\s*(\d+).*?Undetermined:\s*(\d+)',
                line
            )
            if idet_match:
                result["tff"] = int(idet_match.group(1))
                result["bff"] = int(idet_match.group(2))
                result["progressive"] = int(idet_match.group(3))
                result["undetermined"] = int(idet_match.group(4))
                
                total = result["tff"] + result["bff"] + result["progressive"] + result["undetermined"]
                if total > 0:
                    interlaced_pct = (result["tff"] + result["bff"]) / total * 100
                    if interlaced_pct > 10:
                        result["interlaced"] = True
                        if result["tff"] > result["bff"]:
                            result["type"] = "tff"
                        else:
                            result["type"] = "bff"
        
        proc.wait()
        
    except Exception as e:
        log(f"Error en deteccion de interlacing: {e}", "WARN")
    
    return result


def generate_recommendations(analysis, gop_p1=60, audio_mapping="0:a:0"):
    """Genera recomendaciones de encoding basadas en el analisis."""
    
    recs = []
    video = analysis["video"]
    quality = analysis["quality"]
    
    # Deinterlacer
    if video.get("interlaced"):
        recs.append({
            "category": "deinterlace",
            "value": "bwdif" if video.get("interlace_type") == "tff" else "w3fdif",
            "reason": f"Source interlaced detectado ({video.get('interlace_type', 'unknown').upper()})"
        })
    else:
        recs.append({
            "category": "deinterlace",
            "value": "none",
            "reason": "Source ya es progressive"
        })
    
    # GOP (from BD, not from analysis)
    fps = video.get("fps_eval", 29.97)
    recs.append({"category": "gop", "value": gop_p1, "reason": f"Source {fps}fps, GOP={gop_p1} (desde BD)"})
    
    # Bitrate y resolucion
    width = video.get("width", 0)
    height = video.get("height", 0)
    
    if width >= 1920:
        recs.append({"category": "bitrate_p1", "value": 4500, "reason": "1080p: 4500k recomendado"})
        recs.append({"category": "resolution_p1", "value": "1920x1080", "reason": "Escalar a 1080p"})
        recs.append({"category": "resolution_p4", "value": "852x480", "reason": "480p como perfil bajo"})
    elif width >= 1280:
        recs.append({"category": "bitrate_p1", "value": 4000, "reason": "720p: 4000k recomendado"})
        recs.append({"category": "resolution_p1", "value": "1280x720", "reason": "Mantener 720p nativo"})
        recs.append({"category": "resolution_p4", "value": "852x480", "reason": "480p como perfil bajo"})
    else:
        recs.append({"category": "bitrate_p1", "value": 2500, "reason": f"{width}x{height}: bitrate moderado"})
        recs.append({"category": "resolution_p1", "value": f"{width}x{height}", "reason": "Mantener resolucion nativa"})
        recs.append({"category": "resolution_p4", "value": "640x360", "reason": "360p como perfil bajo"})
    
    # Audio mapping (from BD, not auto-selected)
    recs.append({"category": "audio_mapping", "value": audio_mapping, "reason": f"Mapeo de audio desde BD: {audio_mapping}"})
    
    # FPS
    if fps >= 59.9:
        recs.append({"category": "output_fps", "value": "30000/1001", "reason": f"Source {fps}fps, output 29.97fps (2:1 decimation)"})
    else:
        recs.append({"category": "output_fps", "value": "30000/1001", "reason": f"Source {fps}fps, mantener 29.97fps"})
    
    # Bufsize
    bitrate_p1 = next((r["value"] for r in recs if r["category"] == "bitrate_p1"), 4000)
    recs.append({"category": "bufsize_p1", "value": bitrate_p1 * 2, "reason": f"bufsize = 2x bitrate ({bitrate_p1 * 2}k)"})
    recs.append({"category": "bufsize_p4", "value": 2500 * 2, "reason": "bufsize = 2x bitrate (5000k)"})
    
    # Muxrate
    recs.append({"category": "muxrate", "value": "none", "reason": "No usar muxrate fijo (causa dts<pcr)"})
    
    return recs


def select_best_audio(audio_streams):
    """Selecciona el mejor stream de audio priorizando español."""
    if not audio_streams:
        return None
    
    def lang_score(lang):
        lang = lang.lower()
        if lang in ("spa", "es", "spanish", "castellano"):
            return 1000
        elif lang in ("eng", "en", "english"):
            return 100
        else:
            return 0
    
    codec_priority = {"eac3": 4, "ac3": 3, "aac": 2, "mp2": 1, "mp3": 1}
    
    scored = []
    for stream in audio_streams:
        codec_score = codec_priority.get(stream["codec"], 0)
        channel_score = stream["channels"]
        bitrate_score = stream["bit_rate"] / 100000
        language = lang_score(stream.get("language", "und"))
        
        total_score = language + codec_score * 100 + channel_score * 10 + bitrate_score
        scored.append((total_score, stream))
    
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1] if scored else None


def generate_warnings(analysis):
    """Genera warnings basados en problemas detectados."""
    
    warnings = []
    quality = analysis["quality"]
    
    if quality.get("dup_count", 0) > 10:
        warnings.append({"level": "HIGH", "message": f"{quality['dup_count']} frames duplicados - posible perdida de paquetes UDP"})
    if quality.get("drop_count", 0) > 5:
        warnings.append({"level": "HIGH", "message": f"{quality['drop_count']} frames descartados - source inestable"})
    if quality.get("discontinuity_count", 0) > 10:
        warnings.append({"level": "MEDIUM", "message": f"{quality['discontinuity_count']} discontinuidades de timestamp"})
    if quality.get("timestamp_errors", 0) > 0:
        warnings.append({"level": "HIGH", "message": f"{quality['timestamp_errors']} errores dts<pcr en la fuente"})
    if quality.get("decode_errors", 0) > 50:
        warnings.append({"level": "MEDIUM", "message": f"{quality['decode_errors']} errores de decode"})
    if quality.get("speed_factor", 0) < 0.8:
        warnings.append({"level": "HIGH", "message": f"Speed factor {quality['speed_factor']}x - no mantiene tiempo real"})
    
    return warnings


def print_analysis_summary(analysis):
    """Imprime un resumen del analisis."""
    
    print()
    print(f"{C.BOLD}{'=' * 60}{C.END}")
    print(f"{C.BOLD}  RESUMEN DEL ANALISIS{C.END}")
    print(f"{C.BOLD}{'=' * 60}{C.END}")
    
    video = analysis["video"]
    quality = analysis["quality"]
    
    print(f"\n{C.CYAN}PLATAFORMA:{C.END}")
    print(f"  SO:         {analysis.get('platform', '?')}")
    print(f"  Encoder:    {analysis.get('encoder', '?')}")
    
    print(f"\n{C.CYAN}VIDEO:{C.END}")
    print(f"  Codec:      {video.get('codec', '?')} ({video.get('profile', '?')})")
    print(f"  Resolucion: {video.get('width', '?')}x{video.get('height', '?')}")
    print(f"  FPS:        {video.get('fps_eval', '?')}")
    print(f"  Pixel fmt:  {video.get('pix_fmt', '?')}")
    print(f"  Color:      {video.get('color_range', '?')} / {video.get('color_space', '?')}")
    print(f"  Interlaced: {video.get('interlaced', '?')} ({video.get('interlace_type', 'n/a')})")
    print(f"  Bitrate:    {video.get('bit_rate', 0) / 1000:.0f} kbps")
    
    print(f"\n{C.CYAN}AUDIO:{C.END}")
    for audio in analysis.get("audio_streams", []):
        lang = audio.get("language", "und")
        print(f"  Stream #{audio['stream_id']}: {audio['codec']} {audio['channels']}ch {audio['sample_rate']}Hz {audio['bit_rate']/1000:.0f}kbps [{lang}]")
    
    print(f"\n{C.CYAN}CALIDAD:{C.END}")
    print(f"  Frames capturados:    {quality.get('frames_total', 0)}")
    print(f"  FPS promedio:         {quality.get('avg_fps', 0)}")
    print(f"  Bitrate promedio:     {quality.get('avg_bitrate_kbps', 0):.0f} kbps")
    print(f"  Frames duplicados:    {quality.get('dup_count', 0)}")
    print(f"  Frames descartados:   {quality.get('drop_count', 0)}")
    print(f"  Discontinuidades:     {quality.get('discontinuity_count', 0)}")
    print(f"  Errores de timestamp: {quality.get('timestamp_errors', 0)}")
    print(f"  Errores de decode:    {quality.get('decode_errors', 0)}")
    print(f"  Speed factor:         {quality.get('speed_factor', 0)}x")
    
    if analysis.get("warnings"):
        print(f"\n{C.RED}WARNINGS:{C.END}")
        for w in analysis["warnings"]:
            icon = "!!" if w["level"] == "HIGH" else "! "
            print(f"  {C.RED}[{icon}]{C.END} {w['message']}")
    
    print(f"\n{C.GREEN}RECOMENDACIONES:{C.END}")
    for r in analysis.get("recommendations", []):
        print(f"  [{r['category']}] {r['value']} - {r['reason']}")
    
    print()


# ============================================================
# FASE 2: GENERADOR DE SCRIPT DE ENCODING
# ============================================================

def generate_encoder_script(analysis, source_url, local_ip, dest_p1, dest_p4, output_path=SCRIPT_OUTPUT, burn_subtitles=False, service_id=None, service_name=None, gop_p1=60, audio_mapping="0:a:0"):
    """Genera el script de encoding basado en el analisis y la plataforma."""
    
    recs = {r["category"]: r["value"] for r in analysis.get("recommendations", [])}
    video = analysis["video"]
    audio_streams = analysis.get("audio_streams", [])
    platform_name = analysis.get("platform", PLATFORM)
    encoder_name = analysis.get("encoder", "libx264")
    
    # Parametros del video
    fps = video.get("fps_eval", 29.97)
    width = video.get("width", 1280)
    height = video.get("height", 720)
    interlaced = video.get("interlaced", False)
    interlace_type = video.get("interlace_type", "progressive")
    
    # Parametros de output
    bitrate_p1 = recs.get("bitrate_p1", 4000)
    resolution_p1 = recs.get("resolution_p1", "1280x720")
    resolution_p4 = recs.get("resolution_p4", "852x480")
    gop = gop_p1  # Usar GOP de la BD para ambos perfiles
    output_fps = recs.get("output_fps", "30000/1001")
    bufsize_p1 = recs.get("bufsize_p1", 8000)
    bufsize_p4 = recs.get("bufsize_p4", 5000)
    audio_mapping_val = recs.get("audio_mapping", "0:a:0")
    audio_downmix = recs.get("audio_downmix", False)
    
    # Metadatos MPEG-TS (formato correcto)
    mpegts_metadata = []
    if service_id:
        mpegts_metadata.append(f'        "-mpegts_service_id", "{service_id}",')
    if service_name:
        mpegts_metadata.append(f'        "-metadata", "service_name={service_name}",')
        mpegts_metadata.append(f'        "-metadata", "service_provider={service_name}",')
    
    # Convertir metadatos a string para el template
    mpegts_metadata_str = "\n".join(mpegts_metadata) if mpegts_metadata else ""
    
    # URLs
    source_full = build_url(source_url, local_ip, extra_params="fifo_size=2000000&overrun_nonfatal=1&buffer_size=26214400")
    dest_p1_full = build_url(dest_p1, local_ip)
    dest_p4_full = build_url(dest_p4, local_ip)
    
    # Resoluciones
    p1_w, p1_h = resolution_p1.split("x")
    p4_w, p4_h = resolution_p4.split("x")
    
    # Filtro de video
    vf_parts = []
    if interlaced:
        if interlace_type == "tff":
            vf_parts.append("bwdif=mode=0:parity=tff:deint=1")
        else:
            vf_parts.append("bwdif=mode=0:parity=bff:deint=1")
    
    # Subtitulos
    subtitle_filter = ""
    subtitle_map = ""
    subtitle_codec = ""
    subtitle_stream = "0:s:0"  # Primer stream de subtítulos por defecto
    
    # Detectar stream de subtítulos del análisis
    if burn_subtitles:
        # Buscar stream de subtítulos en los datos del análisis
        # Si no se detecta, usar 0:s:0 como fallback
        subtitle_map = ""
        subtitle_codec = ""
    
    # Filtro completo
    # Deinterlacer (si aplica) se aplica primero sobre el video original
    deint_chain = ""
    deint_out = "0:v"
    if vf_parts:
        deint_chain = f"[{deint_out}]{' , '.join(vf_parts)}[v_deint]"
        deint_out = "v_deint"
    
    if burn_subtitles:
        # Orden correcto: overlay → fps → split → scale
        # 1. Overlay de subtitulos sobre el video (original o deinterlaced)
        # 2. fps conversion sobre el video + subtitulos combinados
        # 3. split en dos streams
        # 4. scale cada stream a su resolucion
        overlay_chain = f"[{deint_out}][{subtitle_stream}]overlay=eof_action=pass:repeatlast=0[v_subbed]"
        
        chains = []
        if deint_chain:
            chains.append(deint_chain)
        chains.append(overlay_chain)
        chains.append(f"[v_subbed]fps={output_fps},split=2[v_b1][v_b4]")
        chains.append(f"[v_b1]scale={p1_w}:{p1_h}:flags=fast_bilinear,setsar=1,format=nv12[vout1]")
        chains.append(f"[v_b4]scale={p4_w}:{p4_h}:flags=fast_bilinear,setsar=1,format=nv12[vout2]")
        
        filter_complex = "; ".join(chains)
    else:
        # Sin subtitulos: deint → fps → split → scale
        fps_chain = f"[{deint_out}]fps={output_fps},split=2[v_b1][v_b4]"
        
        chains = []
        if deint_chain:
            chains.append(deint_chain)
        chains.append(fps_chain)
        chains.append(f"[v_b1]scale={p1_w}:{p1_h}:flags=fast_bilinear,setsar=1,format=nv12[vout1]")
        chains.append(f"[v_b4]scale={p4_w}:{p4_h}:flags=fast_bilinear,setsar=1,format=nv12[vout2]")
        
        filter_complex = "; ".join(chains)
    
    # Audio filter
    audio_filter = "aresample=48000:async=2000:first_pts=0"
    if audio_downmix:
        audio_filter += ",pan=stereo|FL=c0+0.5*c2+0.5*c4|FR=c1+0.5*c2+0.5*c4"
    
    # Configuracion del encoder segun plataforma
    encoder_config = get_encoder_config()
    encoder_args = encoder_config["extra_args"]
    profile_args = encoder_config["profile_arg"]
    
    # fflags y vsync: mismos para ambos modos (genpts + cfr = estable)
    fflags = "+genpts+discardcorrupt+nobuffer"
    vsync = "cfr"
    
    # Construir argumentos del encoder como string para el template
    encoder_args_str = ",\n        ".join([f'"{a}"' for a in encoder_args])
    profile_args_str = ",\n        ".join([f'"{a}"' for a in profile_args])
    
    # Ruta de ffmpeg segun plataforma
    ffmpeg_path = FFMPEG
    
    # Generar script
    script = f'''#!/usr/bin/env python3
"""
Encoder auto-generado por Signal Analyzer
Fecha: {analysis.get('timestamp', 'unknown')}
Plataforma: {platform_name} ({encoder_name})
Source: {source_url}

Analisis:
  - Video: {video.get('codec', '?')} {video.get('profile', '?')} {width}x{height} {fps}fps
  - Interlaced: {interlaced} ({interlace_type})
  - Audio: {audio_mapping_val}
  - GOP: {gop} frames
  - Bitrate P1: {bitrate_p1}k, P4: 2500k
  - Encoder: {encoder_name} ({encoder_config['type']})
"""

import subprocess
import sys
import time
import signal


keep_running = True
ffmpeg_process = None


def handle_termination_signal(signum, frame):
    global keep_running, ffmpeg_process
    print("\\n[Orquestador] Senal de apagado recibida. Deteniendo el flujo de manera segura...")
    keep_running = False
    if ffmpeg_process and ffmpeg_process.poll() is None:
        ffmpeg_process.terminate()


def run_transcoder():
    global keep_running, ffmpeg_process
    
    ORIGEN_URL = "{source_full}"
    DEST_P1_URL = "{dest_p1_full}"
    DEST_P4_URL = "{dest_p4_full}"

    # NUMA binding para Linux (default node 0)
    import platform as _platform
    _is_linux = _platform.system() == "Linux"
    _numa_prefix = ["numactl", "--cpunodebind=0", "--membind=0"] if _is_linux else []

    ffmpeg_cmd = _numa_prefix + [
        "{ffmpeg_path}",
        "-hide_banner",
        "-loglevel", "info",
        "-y",
        "-thread_queue_size", "10240",
        "-fflags", "{fflags}",
        "-flags", "low_delay",
        "-probesize", "5M",
        "-analyzeduration", "5M",
        "-ignore_unknown",
        "-max_delay", "500000",
        "-i", ORIGEN_URL,
        
        "-filter_complex", 
        "{filter_complex}",
        
        "-map", "[vout1]",
        "-map", "{audio_mapping_val}",
        {subtitle_map}
        "-c:v", "{encoder_name}",
        "-aspect", "16:9",
        {profile_args_str},
        "-b:v", "{bitrate_p1}k",
        "-maxrate", "{bitrate_p1}k",
        "-bufsize", "{bufsize_p1}k",
        "-g", "{gop}",
        "-keyint_min", "{gop}",
        "-color_range", "tv",
        {encoder_args_str},
        "-fps_mode", "{vsync}",
        "-bsf:v", "h264_mp4toannexb",
        
        "-c:a", "aac",
        "-max_muxing_queue_size", "9999",
        "-b:a", "128k",
        "-ar", "48000",
        "-ac", "2",
        "-af", "{audio_filter}",
        {subtitle_codec}
        "-muxdelay", "0",
        "-muxpreload", "0",
        "-f", "mpegts",
        "-mpegts_flags", "+resend_headers+pat_pmt_at_frames",
        "-pcr_period", "20",
{mpegts_metadata_str}
        DEST_P1_URL,
        
        "-map", "[vout2]",
        "-c:v", "{encoder_name}",
        "-aspect", "16:9",
        {profile_args_str},
        "-b:v", "2500k",
        "-maxrate", "2500k",
        "-bufsize", "{bufsize_p4}k",
        "-g", "{gop}",
        "-keyint_min", "{gop}",
        "-color_range", "tv",
        {encoder_args_str},
        "-fps_mode", "{vsync}",
        "-bsf:v", "h264_mp4toannexb",
        
        "-muxdelay", "0",
        "-muxpreload", "0",
        "-f", "mpegts",
        "-mpegts_flags", "+resend_headers+pat_pmt_at_frames",
        "-pcr_period", "20",
{mpegts_metadata_str}
        DEST_P4_URL
    ]


    signal.signal(signal.SIGINT, handle_termination_signal)
    signal.signal(signal.SIGTERM, handle_termination_signal)
    
    print(f"[Orquestador] Servicio de Transcodificacion Iniciado ({encoder_name}).")
    
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
                        print("\\n[ALERTA CRITICA] Exceso de discontinuidades detectado.")
                        print("[ORQUESTADOR] Forzando reinicio para limpiar relojes...\\n")
                        ffmpeg_process.terminate()
                        break
                        
            ffmpeg_process.wait()
            
        except Exception as e:
            print(f"[Orquestador] Error al invocar el binario: {{e}}")
        
        if keep_running:
            print("[Orquestador] Levantando servicio nuevamente en 5 segundos...\\n")
            time.sleep(5)
        else:
            print("[Orquestador] Apagado completado exitosamente.")


if __name__ == "__main__":
    run_transcoder()
'''
    
    with open(output_path, 'w') as f:
        f.write(script)
    
    os.chmod(output_path, 0o755)
    log(f"Script de encoding generado en: {output_path}", "OK")
    log(f"Plataforma: {platform_name} | Encoder: {encoder_name}", "OK")
    
    return output_path


# ============================================================
# MAIN
# ============================================================

def main():
    if len(sys.argv) < 4:
        print(f"""
{C.BOLD}Signal Analyzer & Encoding Script Generator (Cross-Platform){C.END}
{C.BOLD}{'=' * 55}{C.END}
  Plataforma: {PLATFORM} | Encoder: {'h264_videotoolbox' if PLATFORM == 'Darwin' else 'libx264'}

Uso:
  python3 signal_analyzer.py <source_url> <local_ip> <dest_multicast_base> [opciones]

Argumentos:
  source_url          URL UDP del origen (ej: udp://226.0.0.26:1026)
  local_ip            IP local para multicast (ej: 10.0.10.10)
  dest_multicast_base Base de destino (ej: 238.0.0.130)

Opciones:
  --analyze-only      Solo ejecutar analisis, no generar script
  --generate-only     Solo generar script desde analisis existente
  --duration=N        Duracion del analisis en segundos (default: 300)
  --p1-port=XXXX      Puerto para perfil P1
  --p4-port=XXXX      Puerto para perfil P4
  --burn-subtitles    Quemar subtitulos en el video
  --service-id=N      Service ID para MPEG-TS (ej: 100)
  --service-name=X    Nombre del canal/servicio (ej: "Canal 13 HD")
  --gop-p1=N          GOP para ambos perfiles (default: 60)
  --audio-mapping=X   Mapeo de audio FFmpeg (default: "0:a:0")

Ejemplo:
  python3 signal_analyzer.py udp://226.0.0.26:1026 10.0.10.10 238.0.0.130
  python3 signal_analyzer.py udp://226.0.0.26:1026 10.0.10.10 238.0.0.130 --burn-subtitles
  python3 signal_analyzer.py udp://226.0.0.26:1026 10.0.10.10 238.0.0.130 --service-id=100 --service-name="Canal 13 HD"
""")
        sys.exit(1)
    
    source_url = sys.argv[1]
    local_ip = sys.argv[2]
    dest_base = sys.argv[3]
    
    # Parsear opciones
    analyze_only = "--analyze-only" in sys.argv
    generate_only = "--generate-only" in sys.argv
    burn_subtitles = "--burn-subtitles" in sys.argv
    duration = ANALYSIS_DURATION
    service_id = None
    service_name = None
    
    gop_p1 = 60  # Default
    audio_mapping = "0:a:0"  # Default
    
    for arg in sys.argv:
        if arg.startswith("--duration="):
            duration = int(arg.split("=")[1])
        elif arg.startswith("--service-id="):
            service_id = arg.split("=", 1)[1]
        elif arg.startswith("--service-name="):
            service_name = arg.split("=", 1)[1]
        elif arg.startswith("--gop-p1="):
            gop_p1 = int(arg.split("=")[1])
        elif arg.startswith("--audio-mapping="):
            audio_mapping = arg.split("=", 1)[1]
    
    # Calcular puertos destino
    port_match = re.search(r':(\d+)', source_url.split("://")[1] if "://" in source_url else source_url)
    if port_match:
        src_port = port_match.group(1)
        suffix = src_port[-3:]
    else:
        suffix = "130"
    
    p1_port = f"4{suffix}"
    p4_port = f"5{suffix}"
    
    for arg in sys.argv:
        if arg.startswith("--p1-port="):
            p1_port = arg.split("=")[1]
        if arg.startswith("--p4-port="):
            p4_port = arg.split("=")[1]
    
    dest_p1 = f"udp://{dest_base}:{p1_port}?fifo_size=65536&buffer_size=65536&reuse=1&pkt_size=1316&ttl=32"
    dest_p4 = f"udp://{dest_base}:{p4_port}?fifo_size=65536&buffer_size=65536&reuse=1&pkt_size=1316&ttl=32"
    
    encoder_type = "h264_videotoolbox (hardware)" if PLATFORM == "Darwin" else "libx264 (software)"
    
    print(f"""
{C.BOLD}Signal Analyzer & Encoding Script Generator{C.END}
{C.BOLD}{'=' * 50}{C.END}
  Plataforma:   {PLATFORM} ({encoder_type})
  Source:       {source_url}
  Local IP:     {local_ip}
  Dest P1:      {dest_base}:{p1_port}
  Dest P4:      {dest_base}:{p4_port}
  Duracion:     {duration}s
  Subtitulos:   {'Quemados (hardcoded)' if burn_subtitles else 'No'}
  Service ID:   {service_id or 'No especificado'}
  Service Name: {service_name or 'No especificado'}
  GOP P1:       {gop_p1}
  Audio Map:    {audio_mapping}
  Modo:         {'Solo analisis' if analyze_only else 'Solo generar' if generate_only else 'Completo'}
""")
    
    analysis = None
    
    # Fase 1: Analisis
    if not generate_only:
        analysis = analyze_source(source_url, local_ip, duration, gop_p1=gop_p1, audio_mapping=audio_mapping)
        if not analysis:
            log("El analisis fallo. No se puede continuar.", "ERR")
            sys.exit(1)
    
    # Fase 2: Generar script
    if not analyze_only:
        if not analysis:
            if os.path.exists(ANALYSIS_OUTPUT):
                log(f"Cargando analisis existente desde: {ANALYSIS_OUTPUT}", "INFO")
                with open(ANALYSIS_OUTPUT, 'r') as f:
                    analysis = json.load(f)
            else:
                log("No se encontro analisis existente. Ejecute sin --generate-only primero.", "ERR")
                sys.exit(1)
        
        script_path = generate_encoder_script(
            analysis, source_url, local_ip, dest_p1, dest_p4, 
            burn_subtitles=burn_subtitles,
            service_id=service_id,
            service_name=service_name,
            gop_p1=gop_p1,
            audio_mapping=audio_mapping
        )
        
        print(f"\n{C.GREEN}Script generado: {script_path}{C.END}")
        print(f"Ejecutar con: python3 {script_path}")


if __name__ == "__main__":
    main()
