"""Exercise the managed PostgreSQL lifecycle with the image's native client."""

import pytest

from bondi.deployment import deploy_postgresql, get_deployment, list_deployments


@pytest.mark.live
def test_postgresql_lifecycle(tmp_path, monkeypatch, live_ports):
    monkeypatch.setenv("BONDI_DEPLOYMENT_DIR", str(tmp_path))
    port = live_ports.claim("postgresql")[0]
    db = deploy_postgresql(
        "pg-test", port=port, database="my db", username="tester", password="literal$secret"
    )

    def query(statement):
        return db._run(
            "exec",
            "-T",
            "-e",
            "PGPASSWORD=literal$secret",
            "postgresql",
            "psql",
            "-XAtw",
            "-h",
            "127.0.0.1",
            "-U",
            "tester",
            "-d",
            "my db",
            "-c",
            statement,
        ).strip()

    try:
        assert db.status() == "running"
        query("CREATE TABLE marker AS SELECT 42 AS n")
        db.stop()
        assert db.status() == "stopped"
        db = get_deployment(db.name).start()
        assert query("SELECT n FROM marker") == "42"
        db.remove(keep_data=True)
        assert db.status() == "removed"
        db.start()
        assert query("SELECT n FROM marker") == "42"
        assert db.logs()
    finally:
        db.remove()
    assert not db._data_volume_exists()
    assert list_deployments() == []
