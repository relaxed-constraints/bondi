"""PostgreSQL native query persistence, diagnostic parsing and live execution."""

import asyncio
from decimal import Decimal
from threading import get_ident

import pytest

from bondi.deployment import deploy_postgresql
from bondi.load import Sequential
from bondi.postgresql import AsyncPostgresExecutor, PostgresExecutor, PostgresQuery, summarize
from bondi.workload import Workload, WorkloadEntry


def test_persist(tmp_path):
    q = PostgresQuery("SELECT %s", ["x"])
    w = Workload([WorkloadEntry(q, 2)])
    path = tmp_path / "workload.jsonl"
    w.save(path)
    loaded = Workload.load(path)[0]
    assert loaded.pattern_id == 2 and loaded.query.fingerprint() == q.fingerprint()
    with pytest.raises(TypeError):
        PostgresQuery("SELECT %s", [[1]])
    with pytest.raises(ValueError):
        PostgresQuery.from_json(q.to_json().replace('"statement":', '"statement":"x","statement":'))


def test_summary():
    root = {
        "Node Type": "Aggregate",
        "Actual Rows": 2,
        "Actual Loops": 1,
        "Plans": [
            {
                "Node Type": "Index Scan",
                "Index Name": "tx_price",
                "Actual Rows": 6312,
                "Actual Loops": 1,
            }
        ],
    }
    summary = summarize({"explain": [{"Plan": root, "Execution Time": 0.25}]})
    assert summary.rows_returned == 2 and summary.execution_time_ms == 0.25
    assert summary.plan_stages == ("Aggregate", "Index Scan") and summary.index_names == (
        "tx_price",
    )
    assert summary.keys_examined is summary.documents_examined is None
    root["Plans"][0]["Node Type"] = "Custom Scan"
    assert summarize({"explain": [{"Plan": root}]}).index_names is None


@pytest.mark.live
def test_postgres_execution(tmp_path, monkeypatch, live_ports):
    pg = pytest.importorskip("psycopg")
    pytest.importorskip("psycopg_pool")
    monkeypatch.setenv("BONDI_DEPLOYMENT_DIR", str(tmp_path))
    db = deploy_postgresql("execution", port=live_ports.claim("postgresql")[0])
    try:
        query = PostgresQuery("SELECT i FROM generate_series(1,%s) AS i", [520])
        workload = Workload(
            [WorkloadEntry(query), WorkloadEntry(PostgresQuery("SELECT 1/0")), WorkloadEntry(query)]
        )
        with PostgresExecutor.from_connection(
            db.connection, concurrency=2, continue_on_error=True, health_check_timeout_seconds=2
        ) as executor:
            assert executor.run(query).row_count == 520
            assert executor.run(query, collect_results=True).documents[-1] == {"i": 520}
            numeric = PostgresQuery("""SELECT '{"v":1.234567890123456789}'::jsonb AS doc""")
            assert executor.run(numeric, collect_results=True).documents == [
                {"doc": {"v": Decimal("1.234567890123456789")}}
            ]
            with pytest.raises(ValueError, match="unique"):
                executor.run(
                    PostgresQuery("SELECT 1 AS x, 2 AS x WHERE false"), collect_results=True
                )
            for stmt in ("SELECT 1; SELECT 2", "DELETE FROM pg_class"):
                with pytest.raises(pg.Error):
                    executor.run(PostgresQuery(stmt))
            assert summarize(executor.explain(query).raw).rows_returned is None
            profile = executor.profile(query)
            assert profile.row_count is profile.documents is None
            assert summarize(profile.raw).rows_returned == 520
            callbacks = []
            results = executor.run_workload(
                workload, on_result=lambda i, e, r: callbacks.append((i, get_ident()))
            )
            assert [r.status for r in results] == ["success", "error", "success"]
            assert sorted(callbacks) == [(i, get_ident()) for i in range(3)]
            valid = Workload([WorkloadEntry(query)])
            assert (
                executor.explain_workload(valid)[0].raw and executor.profile_workload(valid)[0].raw
            )
            assert executor.generate_load(
                valid, selection=Sequential(), measurement_seconds=0.1, drain_timeout_seconds=2
            )

        async def recovery():
            async with await AsyncPostgresExecutor.from_connection(
                db.connection, timeout_seconds=0.2
            ) as ex:
                with pytest.raises(TimeoutError):
                    await ex.run(PostgresQuery("SELECT pg_sleep(1)"))
                assert (await ex.run(query)).row_count == 520
                task = asyncio.create_task(ex.run(PostgresQuery("SELECT pg_sleep(1)")))
                await asyncio.sleep(0.05)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
                assert (await ex.run(query)).row_count == 520

                failing = Workload(
                    [WorkloadEntry(PostgresQuery("SELECT pg_sleep(1)")), WorkloadEntry(query)]
                )
                outcomes = await ex.run_workload(failing)
                assert outcomes[0].status == "timeout" and outcomes[1] is None

            # Saturate both connections and verify overlapping calls use distinct server sessions.
            async with await AsyncPostgresExecutor.from_connection(
                db.connection, concurrency=2
            ) as ex:
                q = PostgresQuery("SELECT pg_backend_pid() AS pid, pg_sleep(0.15)")
                rows = await asyncio.gather(*(ex.run(q, collect_results=True) for _ in range(2)))
                assert len({r.documents[0]["pid"] for r in rows}) == 2
                borrowed = AsyncPostgresExecutor(ex.pool, timeout_seconds=0.05)
                async with ex.pool.connection(), ex.pool.connection():
                    with pytest.raises(TimeoutError):
                        await borrowed.run(query)
                await borrowed.close()
                assert (await ex.run(query)).row_count == 520

        asyncio.run(recovery())
    finally:
        db.remove()
