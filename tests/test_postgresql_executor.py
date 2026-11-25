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
            for stmt in (
                "SELECT 1; SELECT 2",
                "DELETE FROM pg_class",
                "WITH changed AS (DELETE FROM pg_class RETURNING oid) SELECT * FROM changed",
            ):
                with pytest.raises(pg.Error):
                    executor.run(PostgresQuery(stmt))
                with pytest.raises(pg.Error):
                    executor.profile(PostgresQuery(stmt))
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


@pytest.mark.live
def test_standalone_parallel_aggregate(tmp_path, monkeypatch, live_ports):
    """Compare both BONDI diagnostics to native PostgreSQL with default planner costs."""
    pg = pytest.importorskip("psycopg")
    pytest.importorskip("psycopg_pool")
    monkeypatch.setenv("BONDI_DEPLOYMENT_DIR", str(tmp_path))
    db = deploy_postgresql("parallel-aggregate", port=live_ports.claim("postgresql")[0])
    query = PostgresQuery("SELECT sum(n) AS total FROM measurements WHERE n >= %s", [1])

    def gather_workers(plan):
        if plan["Node Type"] in ("Gather", "Gather Merge"):
            return plan
        for child in plan.get("Plans", []):
            if found := gather_workers(child):
                return found
        return None

    try:
        with pg.connect(db.uri, user=db.username, password=db.password, autocommit=True) as conn:
            conn.execute("CREATE TABLE measurements AS SELECT generate_series(1, 1000000) AS n")
            conn.execute("ANALYZE measurements")
            native = conn.execute(
                "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + query.statement,
                query.positional_parameters,
            ).fetchone()[0]
            cursor = conn.execute(
                "EXPLAIN (FORMAT JSON) DECLARE old_cursor CURSOR FOR " + query.statement,
                query.positional_parameters,
            ).fetchone()[0]
            # Instrument fresh sessions in this disposable instance to observe run()
            # itself, independently of the two explicit diagnostic operations.
            conn.execute("ALTER ROLE postgres SET session_preload_libraries = 'auto_explain'")
            conn.execute("ALTER ROLE postgres SET auto_explain.log_analyze = on")
            conn.execute("ALTER ROLE postgres SET auto_explain.log_min_duration = 0")
        with PostgresExecutor.from_connection(db.connection) as executor:
            run = executor.run(query, collect_results=True)
            stream_log = db.logs(tail=100)
            assert "Query Text: SELECT sum(n) AS total FROM measurements" in stream_log
            assert "Workers Launched: 2" in stream_log or "Workers Launched: 1" in stream_log
            estimated = executor.explain(query).raw
            observed = executor.profile(query).raw
        native_gather = gather_workers(native[0]["Plan"])
        estimated_gather = gather_workers(estimated["explain"][0]["Plan"])
        observed_gather = gather_workers(observed["explain"][0]["Plan"])
        assert native_gather and native_gather["Workers Launched"] > 0
        assert estimated_gather and estimated_gather["Workers Planned"] > 0
        assert observed_gather and observed_gather["Workers Launched"] > 0
        assert (
            summarize({"explain": native}).plan_stages
            == summarize(estimated).plan_stages
            == summarize(observed).plan_stages
        )
        assert gather_workers(cursor[0]["Plan"]) is None
        assert run.documents == [{"total": 500000500000}] and run.row_count == 1
        print(
            f"Native workers launched={native_gather['Workers Launched']}, "
            f"BONDI planned={estimated_gather['Workers Planned']}, "
            f"BONDI launched={observed_gather['Workers Launched']}, "
            f"stages={summarize(observed).plan_stages}"
        )
    finally:
        db.remove()
