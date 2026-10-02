"""
Tests de validaciones del formulario de canales (issue #13 / cambio mejoras-front-canales).
"""
import models


def _payload(**over):
    data = {
        "channel_name": "TVN_HD",
        "unique_id": "100",
        "origin_multicast_ip": "239.1.1.1",
        "origin_multicast_port": 5000,
        "multicast_ip_out": "239.100.1.1",
        "ruta": "tvn_hd",
    }
    data.update(over)
    return data


class TestNombreSinEspacios:
    def test_nombre_con_espacio_400(self, admin_client):
        resp = admin_client.post("/ui/channels/save", data=_payload(channel_name="TVN HD"))
        assert resp.status_code == 400
        assert "espacios" in resp.json()["error"]

    def test_nombre_con_espacio_inicial_400(self, admin_client):
        resp = admin_client.post("/ui/channels/save", data=_payload(channel_name=" TVN_HD"))
        assert resp.status_code == 400

    def test_nombre_sin_espacios_guarda(self, admin_client, db_session):
        resp = admin_client.post("/ui/channels/save", data=_payload(channel_name="Canal_OK", unique_id="901"),
                                 allow_redirects=False)
        assert resp.status_code == 303
        assert db_session.query(models.Channel).filter(models.Channel.channel_name == "Canal_OK").count() == 1


class TestUniqueIdNumerico:
    def test_unique_id_no_numerico_400(self, admin_client):
        resp = admin_client.post("/ui/channels/save", data=_payload(unique_id="ABC"))
        assert resp.status_code == 400
        assert "numérico" in resp.json()["error"]

    def test_unique_id_vacio_400(self, admin_client):
        resp = admin_client.post("/ui/channels/save", data=_payload(unique_id=""))
        assert resp.status_code == 400


class TestProgramIdDerivado:
    def test_alta_program_id_igual_unique_id(self, admin_client, db_session):
        resp = admin_client.post("/ui/channels/save", data=_payload(channel_name="Canal_P250", unique_id="250"),
                                 allow_redirects=False)
        assert resp.status_code == 303
        ch = db_session.query(models.Channel).filter(models.Channel.channel_name == "Canal_P250").one()
        assert ch.unique_id == "250"
        assert ch.program_id == 250

    def test_edicion_program_id_sigue_unique_id(self, admin_client, db_session):
        ch = models.Channel(channel_name="Canal_Edit", unique_id="111", program_id=999,
                            origin_multicast_ip="239.2.2.2", origin_multicast_port=5000,
                            multicast_ip_out="239.100.2.2", enabled=True)
        db_session.add(ch)
        db_session.commit()
        resp = admin_client.post("/ui/channels/save",
                                 data=_payload(channel_id=str(ch.id), channel_name="Canal_Edit", unique_id="250"),
                                 allow_redirects=False)
        assert resp.status_code == 303
        db_session.refresh(ch)
        assert ch.unique_id == "250"
        assert ch.program_id == 250


class TestBitratePerfil1:
    def test_bitrate_editable_guardado_como_enviado(self, admin_client, db_session):
        resp = admin_client.post("/ui/channels/save",
                                 data=_payload(channel_name="Canal_BW", unique_id="778",
                                               bitrate_p1="6000k", bitrate_high_max="9000k"),
                                 allow_redirects=False)
        assert resp.status_code == 303
        ch = db_session.query(models.Channel).filter(models.Channel.channel_name == "Canal_BW").one()
        assert ch.bitrate_p1 == "6000k"
        assert ch.bitrate_high_max == "6000k"

    def test_alta_default_4500k(self, admin_client, db_session):
        resp = admin_client.post("/ui/channels/save", data=_payload(channel_name="Canal_Dflt", unique_id="779"),
                                 allow_redirects=False)
        assert resp.status_code == 303
        ch = db_session.query(models.Channel).filter(models.Channel.channel_name == "Canal_Dflt").one()
        assert ch.bitrate_p1 == "4500k"
        assert ch.bitrate_high_max == "4500k"


class TestFormUI:
    def test_alta_sin_drm_con_program_id_derivado(self, admin_client):
        resp = admin_client.get("/ui/channels/new")
        assert resp.status_code == 200
        html = resp.text
        assert 'id="chIsDrm"' not in html
        assert 'name="program_id"' not in html
        assert 'Fijar Mapeo' not in html
        assert 'id="program_id_display"' in html
        assert 'placeholder="Ej: TVN_HD"' in html
        assert 'name="bitrate_p1"' in html and 'value="4500k"' in html

    def test_edicion_muestra_program_id_de_unique_id(self, admin_client, db_session):
        ch = models.Channel(channel_name="Canal_UI", unique_id="314", program_id=7,
                            origin_multicast_ip="239.3.3.3", origin_multicast_port=5000,
                            multicast_ip_out="239.100.3.3", enabled=True)
        db_session.add(ch)
        db_session.commit()
        resp = admin_client.get(f"/ui/channels/edit/{ch.id}")
        assert resp.status_code == 200
        html = resp.text
        assert 'id="program_id_display"' in html and 'value="314"' in html
        assert 'id="chIsDrm"' not in html
        assert 'value="7000k"' not in html
