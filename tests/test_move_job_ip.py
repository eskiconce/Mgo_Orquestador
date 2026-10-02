"""
Tests de move_job — sincronización de IP multicast en el script (issue #15 / cambio move-nodo-encoder-ip).
"""
import base64
import zlib

import pytest

import models
import routers.processes as processes


@pytest.fixture
def no_agent(monkeypatch):
    """Evita llamadas HTTP al agente/HAProxy durante los tests."""
    monkeypatch.setattr(processes.requests, "delete", lambda *a, **k: None)
    monkeypatch.setattr(processes, "sync_haproxy_map", lambda db: None)


def _node(db, hostname, tipo, ip_multicast):
    node = models.Node(hostname=hostname, ip_address="127.0.0.1", ip_multicast=ip_multicast,
                       tipo=tipo, enabled=True, status="online")
    db.add(node)
    db.commit()
    return node


def _channel(db, name):
    ch = models.Channel(channel_name=name, unique_id="910", origin_multicast_ip="239.1.1.1",
                        origin_multicast_port=5000, multicast_ip_out="239.100.1.1", ruta=name.lower())
    db.add(ch)
    db.commit()
    return ch


def _job(db, channel, node, command):
    job = models.EncodingJob(channel_id=channel.id, node_id=node.id, command=command, status="stopped")
    db.add(job)
    db.commit()
    return job


def _move(admin_client, job, target, expect=303):
    resp = admin_client.post("/orchestrator/move-job",
                             data={"job_id": job.id, "new_node_id": target.id},
                             allow_redirects=False)
    assert resp.status_code == expect, resp.text
    return resp


LINUX_CMD = (
    '    LOCADDRESS = "10.0.0.5"\n'
    '    origen_url = f"udp://{ORIGEN_IP}:{ORIGEN_PORT}?localaddr={LOCADDRESS}&fifo_size=2000000"\n'
    '    dest_p1_url = f"udp://{DEST_IP}:{DEST_P1}?localaddr={LOCADDRESS}&reuse=1"\n'
    '    OUT_CUSTOM = "no-tocar"'
)

MAC_CMD = (
    'ORIGEN_URL = "udp://239.1.1.1:5000?localaddr=10.0.0.5&fifo_size=2000000"\n'
    'DEST_P1_URL = "udp://239.100.1.1:3140?localaddr=10.0.0.5&fifo_size=65536"\n'
    'DEST_P4_URL = "udp://239.100.1.1:3141?localaddr=10.0.0.5&ttl=32"'
)

PACKAGER_CMD = (
    'INTERFACE="10.0.0.5"\n'
    'exec packager "in=udp://239.1.1.1:5000?interface=$INTERFACE&reuse=1"'
)


class TestMoveEncoderLinux:
    def test_parchea_locaddress_y_preserva_referencia(self, admin_client, db_session, no_agent):
        src = _node(db_session, "enc_a", "Encoder", "10.0.0.5")
        dst = _node(db_session, "enc_b", "Encoder", "10.0.0.9")
        ch = _channel(db_session, "CanalLinux")
        job = _job(db_session, ch, src, LINUX_CMD)

        _move(admin_client, job, dst)
        db_session.refresh(job)

        assert job.node_id == dst.id
        assert 'LOCADDRESS = "10.0.0.9"' in job.command
        assert "localaddr={LOCADDRESS}" in job.command  # referencia a variable intacta
        assert "10.0.0.5" not in job.command
        assert 'OUT_CUSTOM = "no-tocar"' in job.command  # ediciones manuales intactas

    def test_command_compress_deriva_de_command(self, admin_client, db_session, no_agent):
        src = _node(db_session, "enc_a2", "Encoder", "10.0.0.5")
        dst = _node(db_session, "enc_b2", "Encoder", "10.0.0.9")
        ch = _channel(db_session, "CanalCompress")
        job = _job(db_session, ch, src, LINUX_CMD)

        _move(admin_client, job, dst)
        db_session.refresh(job)

        decompressed = zlib.decompress(base64.b64decode(job.command_compress)).decode("utf-8")
        assert 'LOCADDRESS = "10.0.0.9"' in decompressed
        assert "10.0.0.5" not in decompressed


class TestMoveEncoderMac:
    def test_parchea_localaddr_inline_tres_ocurrencias(self, admin_client, db_session, no_agent):
        src = _node(db_session, "mac_a", "Encoder", "10.0.0.5")
        dst = _node(db_session, "mac_b", "Encoder", "10.0.0.9")
        ch = _channel(db_session, "CanalMac")
        job = _job(db_session, ch, src, MAC_CMD)

        _move(admin_client, job, dst)
        db_session.refresh(job)

        assert job.node_id == dst.id
        assert job.command.count("localaddr=10.0.0.9") == 3
        assert "10.0.0.5" not in job.command
        assert "&fifo_size=2000000" in job.command  # resto de la URL intacto


class TestMovePackagerSinCambios:
    def test_command_intacto(self, admin_client, db_session, no_agent):
        src = _node(db_session, "pkg_a", "Packager", "10.0.0.5")
        dst = _node(db_session, "pkg_b", "Packager", "10.0.0.9")
        ch = _channel(db_session, "CanalPkg")
        job = _job(db_session, ch, src, PACKAGER_CMD)

        _move(admin_client, job, dst)
        db_session.refresh(job)

        assert job.node_id == dst.id
        assert job.command == PACKAGER_CMD  # IP de packager fuera de alcance (issue #15)


class TestDefensivo:
    def test_command_vacio_sin_error(self, admin_client, db_session, no_agent):
        src = _node(db_session, "enc_e1", "Encoder", "10.0.0.5")
        dst = _node(db_session, "enc_e2", "Encoder", "10.0.0.9")
        ch = _channel(db_session, "CanalVacio")
        job = _job(db_session, ch, src, "")

        _move(admin_client, job, dst)
        db_session.refresh(job)

        assert job.node_id == dst.id
        assert job.command == ""

    def test_ip_multicast_destino_none_sin_cambios(self, admin_client, db_session, no_agent):
        src = _node(db_session, "enc_n1", "Encoder", "10.0.0.5")
        dst = _node(db_session, "enc_n2", "Encoder", None)
        ch = _channel(db_session, "CanalSinIp")
        job = _job(db_session, ch, src, LINUX_CMD)

        _move(admin_client, job, dst)
        db_session.refresh(job)

        assert job.node_id == dst.id
        assert 'LOCADDRESS = "10.0.0.5"' in job.command  # sin cambios


class TestValidaciones:
    def test_job_running_no_se_mueve(self, admin_client, db_session, no_agent):
        src = _node(db_session, "enc_r1", "Encoder", "10.0.0.5")
        dst = _node(db_session, "enc_r2", "Encoder", "10.0.0.9")
        ch = _channel(db_session, "CanalRunning")
        job = _job(db_session, ch, src, LINUX_CMD)
        job.status = "running"
        db_session.commit()

        resp = admin_client.post("/orchestrator/move-job",
                                 data={"job_id": job.id, "new_node_id": dst.id},
                                 allow_redirects=False)
        assert resp.status_code == 400

    def test_canal_duplicado_en_destino_no_se_mueve(self, admin_client, db_session, no_agent):
        src = _node(db_session, "enc_d1", "Encoder", "10.0.0.5")
        dst = _node(db_session, "enc_d2", "Encoder", "10.0.0.9")
        ch = _channel(db_session, "CanalDup")
        _job(db_session, ch, dst, LINUX_CMD)  # ya existe en destino
        job = _job(db_session, ch, src, LINUX_CMD)

        resp = admin_client.post("/orchestrator/move-job",
                                 data={"job_id": job.id, "new_node_id": dst.id},
                                 allow_redirects=False)
        assert resp.status_code == 400
