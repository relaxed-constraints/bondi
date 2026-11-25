"""Run against a disposable PostgreSQL database selected by SPIKE_PG_DSN."""

import json
import os
from datetime import date, datetime
from decimal import Decimal
from functools import partial

import psycopg
import simplejson
from bson import Decimal128, ObjectId
from psycopg.types.json import Jsonb, set_json_loads

from bondi.data._values import convert, document_key


def main():
    oid = ObjectId("0123456789abcdef01234567")
    ids = [1, "1", oid, str(oid)]
    amount = Decimal128("1234567890.123456789")
    timestamp = datetime.fromisoformat("2026-11-26T11:30:00.123456+11:00")
    keys = [document_key(value) for value in ids]
    dumps = partial(simplejson.dumps, use_decimal=True, allow_nan=False)

    with psycopg.connect(os.environ["SPIKE_PG_DSN"]) as conn:
        conn.execute("CREATE TEMP TABLE fixture (id text PRIMARY KEY, doc jsonb NOT NULL)")
        for key, source_id in zip(keys, ids, strict=True):
            # Exercise the existing temporal and ObjectId conversions on their supported backend.
            doc = convert(
                {"_id": source_id, "day": date(2026, 11, 26), "instant": timestamp},
                "couchbase",
                {},
                {},
            )
            doc["values"] = [amount.to_decimal(), 0.25]
            conn.execute("INSERT INTO fixture VALUES (%s, %s)", (key, Jsonb(doc, dumps=dumps)))

        set_json_loads(partial(json.loads, parse_float=Decimal), conn)
        rows = dict(conn.execute("SELECT id, doc FROM fixture"))
        assert len(rows) == 4
        assert [rows[key]["_id"] for key in keys] == [1, "1", str(oid), str(oid)]
        for doc in rows.values():
            assert doc["day"] == "2026-11-26"
            assert doc["instant"] == "2026-11-26T00:30:00.123Z"
            assert doc["values"] == [amount.to_decimal(), Decimal("0.25")]
            assert all(isinstance(value, Decimal) for value in doc["values"])

        conn.execute(
            "INSERT INTO fixture VALUES (%s, %s) ON CONFLICT (id) DO UPDATE SET doc=excluded.doc",
            (document_key(oid), Jsonb({"_id": str(oid), "updated": True})),
        )
        updated = dict(conn.execute("SELECT id, doc FROM fixture"))
        assert len(updated) == 4 and updated[keys[2]]["updated"]
        assert all(updated[key] == rows[key] for key in (keys[0], keys[1], keys[3]))
        print("Verified four typed IDs, temporal and numeric readback, and isolated upsert.")


if __name__ == "__main__":
    main()
