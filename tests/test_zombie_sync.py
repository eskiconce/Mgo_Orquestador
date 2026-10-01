"""
Tests Issue #12 — zombie-crashloop-sync (Fase A).

Cubre:
- A1  stop_job honesto (502 sin alterar BD si el agente no confirma)
- A2  anti-zombie efímero (uptime < 30s -> ZOMBIE_UNSTABLE + error, sin adoptar)
- A3  rate-limit de notificaciones CMS (10 min por canal+evento)
- A4  dedupe de ZOMBIE_DETECTED (5 min por job)
- A5  log_monitor_event sin commit propio
- A6  eventos CMS_* en monitor_logs
- A7  timestamp consola/BD idéntico (microsegundos truncados)
"""
from datetime import datetime, timedelta

import httpx
import pytest

import models
from services.settings_service import save_section


# ---------------------------------------------------------------- Helpers

class _Resp:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        return self._payload


class _FakeAgentSession:
    """Fake de create_sync_client(): /jobs/status -> procesos, resto -> 500."""

    def __init__(self, processes):
        self.processes = processes

    def get(self, url, **kwargs):
        if "/jobs/status" in url:
            return _Resp(200, self.processes)
        return _Resp(500)

    def post(self, url, **kwargs):
        return _Resp(200)

    def close(self):
        pass


def _setup_job(db, status="stopped", auto_started=False, tipo="Encoder"):
    ch = models.Channel(channel_name="CanalZombie", unique_id="777")
    node = models.Node(hostname="enc-test", ip_address="10.0.0.9",
                       tipo=tipo, status="online", enabled=True)
    db.add_all([ch, node])
    db.commit()
    job = models.EncodingJob(channel_id=ch.id, node_id=node.id,
                             status=status, auto_started=auto_started)
    db.add(job)
    db.commit()
    return ch, node, job


def _run_cycle(db, monkeypatch, node_id, processes):
    import monitor
    monkeypatch.setattr(monitor, "SessionLocal", lambda: db)
    monkeypatch.setattr(monitor, "create_sync_client", lambda: _FakeAgentSession(processes))
    monitor.process_node_thread(node_id)


def _events(db, event_type):
    return db.query(models.MonitorLog).filter(
        models.MonitorLog.event_type == event_type).all()


@pytest.fixture(autouse=True)
def _clean_module_state():
    """Limpia dicts de estado en memoria entre tests."""
    import monitor
    import monitor.alerts as ma
    monitor._zombie_watch.clear()
    monitor._zombie_last_log.clear()
    ma._cms_last_sent.clear()
    yield
    monitor._zombie_watch.clear()
    monitor._zombie_last_log.clear()
    ma._cms_last_sent.clear()


# ---------------------------------------------------------------- A1

class TestStopJobHonesty:

    def _job(self, db):
        return _setup_job(db, status="running")[2]

    def test_agent_http_error_returns_502_and_status_unchanged(self, db_session, operator_client, monkeypatch):
        job = self._job(db_session)

        class FakeAsyncClient:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, *a, **k):
                return _Resp(500)

        monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
        resp = operator_client.post(f"/orchestrator/stop-job/{job.id}")
        assert resp.status_code == 502
        db_session.refresh(job)
        assert job.status == "running"

    def test_agent_unreachable_returns_502_and_status_unchanged(self, db_session, operator_client, monkeypatch):
        job = self._job(db_session)

        class FakeAsyncClient:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, *a, **k):
                raise RuntimeError("connection refused")

        monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
        resp = operator_client.post(f"/orchestrator/stop-job/{job.id}")
        assert resp.status_code == 502
        db_session.refresh(job)
        assert job.status == "running"

    def test_agent_confirms_stop_marks_stopped(self, db_session, operator_client, monkeypatch):
        job = self._job(db_session)

        class FakeAsyncClient:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, *a, **k):
                return _Resp(200)

        monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
        resp = operator_client.post(f"/orchestrator/stop-job/{job.id}")
        assert resp.status_code == 200
        db_session.refresh(job)
        assert job.status == "stopped"


# ---------------------------------------------------------------- A2 + A4

class TestZombieStability:

    def _prepare(self, db, status="stopped"):
        """Crea canal+nodo+job y captura ids antes de que el ciclo cierre la sesión."""
        ch, node, job = _setup_job(db, status=status)
        return ch.channel_name, node.id, job.id

    def test_unstable_zombie_marked_error_and_not_adopted(self, db_session, monkeypatch):
        channel_name, node_id, job_id = self._prepare(db_session)
        procs = [{"name": f"channel_{channel_name}_{job_id}", "statename": "RUNNING",
                  "start": 0, "bitrate": "600k", "fps": 30.0}]

        _run_cycle(db_session, monkeypatch, node_id, procs)

        job = db_session.query(models.EncodingJob).get(job_id)
        assert job.status == "error"
        assert job.auto_started is False
        assert job.started_at is None
        assert len(_events(db_session, "ZOMBIE_UNSTABLE")) == 1
        assert _events(db_session, "ZOMBIE_DETECTED") == []
        assert _events(db_session, "PROCESS_SYNCED") == []

    def test_unstable_zombie_stays_error_and_not_resynced(self, db_session, monkeypatch):
        channel_name, node_id, job_id = self._prepare(db_session)
        procs = [{"name": f"channel_{channel_name}_{job_id}", "statename": "RUNNING", "start": 0}]

        _run_cycle(db_session, monkeypatch, node_id, procs)
        _run_cycle(db_session, monkeypatch, node_id, procs)

        job = db_session.query(models.EncodingJob).get(job_id)
        assert job.status == "error"
        assert job.started_at is None
        # sin log duplicado y sin sync a running
        assert len(_events(db_session, "ZOMBIE_UNSTABLE")) == 1
        assert _events(db_session, "PROCESS_SYNCED") == []

    def test_stable_zombie_adopted_after_watch_window(self, db_session, monkeypatch):
        import monitor
        channel_name, node_id, job_id = self._prepare(db_session)
        procs = [{"name": f"channel_{channel_name}_{job_id}", "statename": "RUNNING", "start": 0}]

        # ventana de observación con > 30s acumulados
        monitor._zombie_watch[job_id] = datetime.now() - timedelta(seconds=31)

        _run_cycle(db_session, monkeypatch, node_id, procs)

        job = db_session.query(models.EncodingJob).get(job_id)
        assert job.status == "running"
        assert job.started_at is not None
        assert len(_events(db_session, "ZOMBIE_DETECTED")) == 1
        assert _events(db_session, "ZOMBIE_UNSTABLE") == []
        assert job_id not in monitor._zombie_watch

    def test_zombie_detected_deduped_within_window(self, db_session, monkeypatch):
        import monitor
        channel_name, node_id, job_id = self._prepare(db_session)
        procs = [{"name": f"channel_{channel_name}_{job_id}", "statename": "RUNNING", "start": 0}]

        monitor._zombie_watch[job_id] = datetime.now() - timedelta(seconds=31)
        monitor._zombie_last_log[job_id] = datetime.now()  # log reciente < 5 min

        _run_cycle(db_session, monkeypatch, node_id, procs)

        job = db_session.query(models.EncodingJob).get(job_id)
        # se adopta (estable) pero NO se loguea por dedupe
        assert job.status == "running"
        assert _events(db_session, "ZOMBIE_DETECTED") == []

    def test_vanished_process_resets_watch(self, db_session, monkeypatch):
        import monitor
        channel_name, node_id, job_id = self._prepare(db_session)

        monitor._zombie_watch[job_id] = datetime.now() - timedelta(seconds=20)
        # proceso desapareció (crash-loop): el agente no lo reporta
        _run_cycle(db_session, monkeypatch, node_id, [])

        assert job_id not in monitor._zombie_watch
        job = db_session.query(models.EncodingJob).get(job_id)
        assert job.status == "stopped"
        assert _events(db_session, "ZOMBIE_DETECTED") == []


# ---------------------------------------------------------------- A3 + A6

class TestCmsRateLimitAndEvents:

    def _channel(self, db):
        ch = models.Channel(channel_name="CanalCMS", ruta="canal_cms", unique_id="888")
        db.add(ch)
        db.commit()
        return ch

    def _notify(self, monkeypatch, posts, calls, channel_id, status, desc):
        import monitor.alerts as ma
        monkeypatch.setattr(ma, "SessionLocal", lambda: calls["db"])

        class FakeClient:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def post(self, url, **kw):
                posts.append((url, kw["json"]["status"]))

        monkeypatch.setattr(ma.httpx, "Client", lambda **kw: FakeClient())
        ma.notify_cms_channel_status(channel_id, status, desc)

    def test_second_same_event_within_window_is_skipped(self, db_session, monkeypatch):
        ch = self._channel(db_session)
        save_section(db_session, "cms", {"enabled": "1", "webhook_url": "https://cms/w"})
        cid = ch.id
        posts = []
        calls = {"db": db_session}

        self._notify(monkeypatch, posts, calls, cid, "offline", "primera")
        self._notify(monkeypatch, posts, calls, cid, "offline", "segunda")

        # solo la primera notificación salió (rate-limit 10 min)
        assert len(posts) == 1
        assert posts[0][1] == "offline"
        # A6: fila CMS_OFFLINE registrada exactamente una vez
        assert len(_events(db_session, "CMS_OFFLINE")) == 1

    def test_different_status_is_not_rate_limited(self, db_session, monkeypatch):
        ch = self._channel(db_session)
        save_section(db_session, "cms", {"enabled": "1", "webhook_url": "https://cms/w"})
        cid = ch.id
        posts = []
        calls = {"db": db_session}

        self._notify(monkeypatch, posts, calls, cid, "offline", "caida")
        self._notify(monkeypatch, posts, calls, cid, "online", "ok")

        assert [p[1] for p in posts] == ["offline", "online"]
        assert len(_events(db_session, "CMS_OFFLINE")) == 1
        assert len(_events(db_session, "CMS_ONLINE")) == 1


# ---------------------------------------------------------------- A5 + A7

class TestLogMonitorEvent:

    def test_does_not_commit(self, db_session):
        from utils.helpers import log_monitor_event
        commits = []
        original_commit = db_session.commit

        def spy_commit(*a, **k):
            commits.append(1)
            return original_commit(*a, **k)

        db_session.commit = spy_commit
        try:
            log_monitor_event(db_session, "TEST_EVT", "mensaje de prueba")
            assert commits == []  # el helper no ejecutó commit
            row = db_session.query(models.MonitorLog).filter_by(event_type="TEST_EVT").first()
            assert row is not None  # flush sí ocurrió (visible en la sesión)
            original_commit()
        finally:
            db_session.commit = original_commit

    def test_truncates_microseconds_for_parity(self, db_session):
        from utils.helpers import log_monitor_event
        ts = datetime(2026, 9, 30, 12, 34, 56, 789123)

        log_monitor_event(db_session, "TEST_TS", "paridad", timestamp=ts)
        db_session.commit()

        row = db_session.query(models.MonitorLog).filter_by(event_type="TEST_TS").first()
        assert row.timestamp.microsecond == 0
        assert row.timestamp == ts.replace(microsecond=0)
