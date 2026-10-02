"""
Tests de generate_recommendations — resolución y bitrates según origen (issue #17).
"""
import importlib.util
from pathlib import Path

import pytest

_MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "signal_analyzer.py"
_spec = importlib.util.spec_from_file_location("signal_analyzer", _MODULE_PATH)
sa = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sa)


def make_analysis(width, height):
    return {
        "video": {
            "width": width,
            "height": height,
            "fps_eval": 30.0,
            "interlaced": False,
            "interlace_type": "progressive",
        },
        "quality": {},
        "subtitle_streams": [],
    }


def recs_dict(analysis, **kwargs):
    recs = sa.generate_recommendations(analysis, **kwargs)
    return {r["category"]: r for r in recs}


class TestTierSD:
    def test_640x360_p2_50pct_y_bitrates_sd(self):
        r = recs_dict(make_analysis(640, 360), bitrate_p1=6500, bitrate_p4=2500, gop_p1=48)
        assert r["resolution_p1"]["value"] == "640x360"
        assert r["resolution_p4"]["value"] == "320x180"
        assert r["bitrate_p1"]["value"] == 2500  # SD gobierna sobre BD (6500)
        assert r["bitrate_p4"]["value"] == 700    # SD gobierna sobre BD (2500)
        assert "ignorado" in r["bitrate_p1"]["reason"]
        assert "ignorado" in r["bitrate_p4"]["reason"]

    def test_720x576_pal_pares(self):
        r = recs_dict(make_analysis(720, 576), bitrate_p1=6500, bitrate_p4=2500)
        assert r["resolution_p1"]["value"] == "720x576"
        assert r["resolution_p4"]["value"] == "360x288"

    def test_480x270_p2_sin_upscale_pares(self):
        r = recs_dict(make_analysis(480, 270), bitrate_p1=6500, bitrate_p4=2500)
        assert r["resolution_p1"]["value"] == "480x270"
        assert r["resolution_p4"]["value"] == "240x134"  # 135 redondeado a par

    def test_dimensiones_impares_en_p1_se_redondean(self):
        r = recs_dict(make_analysis(853, 479))
        assert r["resolution_p1"]["value"] == "852x478"

    def test_p2_nunca_mayor_que_p1(self):
        r = recs_dict(make_analysis(1024, 576))
        p1_w, p1_h = map(int, r["resolution_p1"]["value"].split("x"))
        p2_w, p2_h = map(int, r["resolution_p4"]["value"].split("x"))
        assert p2_w <= min(p1_w // 2, 640)
        assert p2_h <= min(p1_h // 2, 360)


class TestDefensaSinDeteccion:
    def test_width_cero_fallback_720(self):
        r = recs_dict(make_analysis(0, 0))
        assert r["resolution_p1"]["value"] == "1280x720"
        assert r["resolution_p4"]["value"] == "852x480"
        assert r["resolution_p1"]["value"] != "0x0"
        assert r["resolution_warning"]["value"] == "fallback_720p"

    def test_height_ausente_fallback_720(self):
        analysis = make_analysis(1920, 0)
        r = recs_dict(analysis)
        assert r["resolution_p1"]["value"] == "1280x720"
        assert "resolution_warning" in r


class TestTiersMayoresIntactos:
    def test_hd_1080_prioridad_bd(self):
        r = recs_dict(make_analysis(1920, 1080), bitrate_p1=5000, bitrate_p4=2500, gop_p1=60)
        assert r["resolution_p1"]["value"] == "1920x1080"
        assert r["resolution_p4"]["value"] == "852x480"
        assert r["bitrate_p1"]["value"] == 5000  # BD intacto
        assert r["bitrate_p4"]["value"] == 2500  # BD intacto
        assert "resolution_warning" not in r

    def test_720_prioridad_bd(self):
        r = recs_dict(make_analysis(1280, 720), bitrate_p1=4000, bitrate_p4=2500)
        assert r["resolution_p1"]["value"] == "1280x720"
        assert r["bitrate_p1"]["value"] == 4000
        assert r["bitrate_p4"]["value"] == 2500

    def test_hd_sin_bd_usa_sugerido(self):
        r = recs_dict(make_analysis(1920, 1080), bitrate_p1=None, bitrate_p4=2500)
        assert r["bitrate_p1"]["value"] == 4500


class TestGopYBufsize:
    @pytest.mark.parametrize("width,height", [(640, 360), (1280, 720), (1920, 1080)])
    def test_gop_siempre_de_bd(self, width, height):
        r = recs_dict(make_analysis(width, height), gop_p1=48)
        assert r["gop"]["value"] == 48

    @pytest.mark.parametrize("width,height", [(640, 360), (1920, 1080)])
    def test_bufsize_dos_x_bitrate_final(self, width, height):
        r = recs_dict(make_analysis(width, height), bitrate_p1=5000, bitrate_p4=2500)
        assert r["bufsize_p1"]["value"] == r["bitrate_p1"]["value"] * 2
        assert r["bufsize_p4"]["value"] == r["bitrate_p4"]["value"] * 2
