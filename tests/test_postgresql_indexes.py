"""PostgreSQL index definitions, namespaces and catalog-based lifecycle."""

import pytest

from bondi import (
    FieldIndex,
    IndexCreationError,
    IndexSet,
    PostgresConnection,
    create_index,
    create_indexes,
    load_index,
    remove_index,
    remove_indexes,
)
from bondi.deployment import deploy_postgresql
from bondi.postgresql import PostgresCollectionRef, PostgresIndex, postgres_index_name


def test_index_artifacts_and_preflight(tmp_path):
    definition = PostgresIndex.gin(
        "doc -> 'tags'", operator_class="jsonb_path_ops", condition="doc ? 'tags'"
    )
    file = tmp_path / "gin.json"
    definition.save(file)
    assert load_index(file) == definition
    ref = PostgresCollectionRef("public", "items")
    assert postgres_index_name(ref, definition) != postgres_index_name(
        PostgresCollectionRef("public", "other"), definition
    )
    named = PostgresIndex.btree((("doc ->> 'city'", -1),), name="by_city")
    indexes = IndexSet({"items": [named, definition], "other": [named]})
    indexes.save(file)
    assert IndexSet.load(file).to_dict() == indexes.to_dict()
    with pytest.raises(ValueError, match="Conflicting"):
        create_indexes(PostgresConnection("unused"), schema="public", indexes=indexes)
    with pytest.raises(ValueError, match="operator class"):
        PostgresIndex.gin("doc", operator_class="bad")
    with pytest.raises(ValueError, match="63"):
        postgres_index_name(ref, FieldIndex((("x", 1),), name="é" * 32))


@pytest.mark.live
def test_index_lifecycle(tmp_path, monkeypatch, live_ports):
    pg = pytest.importorskip("psycopg")
    monkeypatch.setenv("BONDI_DEPLOYMENT_DIR", str(tmp_path))
    db = deploy_postgresql("indexes", port=live_ports.claim("postgresql")[0])
    target = PostgresCollectionRef("public", "items")
    other = PostgresCollectionRef("public", "other")
    field = FieldIndex((("value.n", 1), ("quote's.key", -1)))
    gin = PostgresIndex.gin(
        "doc -> 'tags'", operator_class="jsonb_path_ops", condition="doc ? 'tags'"
    )
    try:
        with pg.connect(db.uri, user=db.username, password=db.password, autocommit=True) as conn:
            for table in ("items", "other"):
                conn.execute(f"CREATE TABLE {table} (document_id text PRIMARY KEY, doc jsonb)")
            conn.execute(
                "ALTER TABLE items ADD CONSTRAINT keep_exclusion "
                "EXCLUDE USING btree (document_id WITH =)"
            )
            conn.execute("CREATE UNIQUE INDEX keep_replica ON items (document_id)")
            conn.execute("ALTER TABLE items REPLICA IDENTITY USING INDEX keep_replica")
            conn.execute("CREATE UNIQUE INDEX keep_unique ON items ((doc ->> 'code'))")
            conn.execute("CREATE INDEX disposable ON items (doc)")
            conn.execute("CREATE TABLE partitioned (n int) PARTITION BY RANGE(n)")
            create_indexes(
                db.connection,
                schema="public",
                indexes=IndexSet({"items": [field], "other": [field]}),
            )
            other_name = postgres_index_name(other, field)
            wrong_table = PostgresIndex.btree((("doc", 1),), name=other_name)
            assert not remove_index(db.connection, collection=target, index=wrong_table)
            assert create_index(db.connection, collection=target, index=gin) == postgres_index_name(
                target, gin
            )
            for protected in ("items_pkey", "keep_unique", "keep_exclusion", "keep_replica"):
                forbidden = FieldIndex((("unused", 1),), name=protected)
                with pytest.raises(ValueError, match="protected"):
                    remove_indexes(
                        db.connection,
                        schema="public",
                        indexes=IndexSet({"items": [gin, forbidden]}),
                    )
            with pytest.raises(IndexCreationError) as partition:
                create_indexes(
                    db.connection,
                    schema="public",
                    indexes=IndexSet({"items": [], "partitioned": []}),
                    replace=True,
                )
            assert partition.value.phase == "inspect"
            assert conn.execute("SELECT to_regclass('disposable')").fetchone()[0] == "disposable"
            assert create_indexes(
                db.connection, schema="public", indexes=IndexSet({"items": []}), replace=True
            ) == {"items": []}
            remaining = {
                row[0]
                for row in conn.execute(
                    "SELECT indexname FROM pg_indexes WHERE schemaname='public'"
                )
            }
            assert remaining == {
                "items_pkey",
                "other_pkey",
                "keep_unique",
                "keep_exclusion",
                "keep_replica",
                other_name,
            }
            bad = PostgresIndex.btree((("nonexistent_column", 1),))
            with pytest.raises(IndexCreationError) as failure:
                create_indexes(
                    db.connection, schema="public", indexes=IndexSet({"items": [gin, bad]})
                )
            assert failure.value.completed == {"items": [postgres_index_name(target, gin)]}
            assert failure.value.collection == "items" and failure.value.position == 1
            assert remove_index(db.connection, collection=target, index=gin)
            assert not remove_index(db.connection, collection=target, index=gin)
    finally:
        db.remove()
