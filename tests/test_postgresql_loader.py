"""PostgreSQL document conversion and native writer behavior."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from bson import Decimal128, ObjectId

from bondi._cli import main
from bondi.data import LoadDataError, load_documents
from bondi.data._values import convert
from bondi.deployment import deploy_postgresql
from bondi.postgresql import PostgresCollectionRef


def test_postgres_value_conversion():
    value = {
        "amount": Decimal128("19.9900"),
        "big": 2**63 - 1,
        "when": datetime(2026, 11, 26, 1, 2, 3, 123456, UTC),
    }
    converted = convert(value, "postgresql", {}, {})
    assert converted == {
        "amount": Decimal("19.9900"),
        "big": 2**63 - 1,
        "when": "2026-11-26T01:02:03.123Z",
    }
    with pytest.raises(ValueError, match=r"\$\.bad"):
        convert({"bad": "a\0b"}, "postgresql", {}, {})


@pytest.mark.live
def test_pg_document_loader(tmp_path, monkeypatch, live_ports):
    pg = pytest.importorskip("psycopg")
    monkeypatch.setenv("BONDI_DEPLOYMENT_DIR", str(tmp_path))
    db = deploy_postgresql("writer", port=live_ports.claim("postgresql")[0])
    options = dict(connection=db.connection, collection=PostgresCollectionRef("sample", "docs"))
    oid = ObjectId()
    amount = Decimal128("1234567890.123456789")
    docs = [{"_id": key, "amount": amount} for key in (1, "1", oid, str(oid))]
    try:
        result = load_documents(docs, **options)
        assert result.destinations == {"sample.docs": 4}
        with pytest.raises(LoadDataError, match="empty"):
            load_documents(docs, **options)
        load_documents([{"_id": oid, "changed": True}], mode="upsert", **options)
        with pg.connect(db.uri, user=db.username, password=db.password, autocommit=True) as client:
            rows = client.execute("SELECT (doc->>'amount')::numeric FROM sample.docs").fetchall()
            assert rows.count((amount.to_decimal(),)) == 3 and rows.count((None,)) == 1
            client.execute("CREATE INDEX keep_me ON sample.docs USING gin(doc)")
            load_documents(docs[:1], mode="replace", **options)
            assert client.execute(
                "SELECT count(*), to_regclass('sample.keep_me') FROM sample.docs"
            ).fetchone() == (1, "sample.keep_me")
            client.execute("CREATE TABLE sample.foreign_layout AS SELECT 1 AS keep")
            with pytest.raises(LoadDataError, match="Incompatible"):
                load_documents(
                    [],
                    connection=db.connection,
                    collection=PostgresCollectionRef("sample", "foreign_layout"),
                    mode="replace",
                )
            assert client.execute("SELECT keep FROM sample.foreign_layout").fetchone() == (1,)
        source = tmp_path / "fixture.jsonl"
        source.write_text('{"_id":1}\n{"_id":2}\n')
        assert (
            main(
                [
                    "dataset",
                    "load-file",
                    str(source),
                    "--deployment",
                    db.name,
                    "--schema",
                    "sample",
                    "--collection",
                    "from_file",
                ]
            )
            == 0
        )
        with pytest.raises(LoadDataError) as failure:
            load_documents(
                [{"_id": 1}, {"_id": 2, "bad": "a\0b"}],
                collection=PostgresCollectionRef("sample", "partial"),
                connection=db.connection,
                batch_size=1,
            )
        assert failure.value.result.destinations == {"sample.partial": 1}
    finally:
        db.remove()
