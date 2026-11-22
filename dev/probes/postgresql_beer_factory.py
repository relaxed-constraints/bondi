"""Compare native MongoDB and PostgreSQL queries on fresh beer_factory destinations."""

import argparse
import json
import os
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb
from pymongo import MongoClient

from bondi.connection import MongoConnection
from bondi.data import load_aptmql_dataset

REVISION = "06ba1f0f29b1947e67a343c204e6a9b5eede6b17"
SCHEMA = "beer_factory"


def load(pg, mongo, uri):
    reports = load_aptmql_dataset(SCHEMA, connection=MongoConnection(uri), revision=REVISION)
    counts = {}
    pg.execute("CREATE SCHEMA beer_factory")
    for name, report in reports.items():
        table = sql.Identifier(SCHEMA, name)
        pg.execute(
            sql.SQL(
                "CREATE TABLE {} (document_id text PRIMARY KEY, "
                "doc jsonb NOT NULL CHECK (jsonb_typeof(doc) = 'object'))"
            ).format(table)
        )
        # Keep the original ID in the payload. A text key is valid for this fixture.
        documents = list(mongo[name].find())
        if any(type(doc["_id"]) is not str for doc in documents):
            raise ValueError(f"Non-string ID in {name}")
        with (
            pg.cursor() as cursor,
            cursor.copy(sql.SQL("COPY {} FROM STDIN").format(table)) as copy,
        ):
            for doc in documents:
                copy.write_row((doc["_id"], Jsonb(doc)))

        loaded = dict(pg.execute(sql.SQL("SELECT document_id, doc FROM {}").format(table)))
        if loaded != {doc["_id"]: doc for doc in documents} or len(loaded) != sum(
            report.destinations.values()
        ):
            raise AssertionError(f"Document mismatch in {name}")
        counts[name] = len(loaded)
        pg.execute(sql.SQL("ANALYZE {}").format(table))
    return counts


def cases(collection):
    select_ids = "SELECT document_id FROM beer_factory.transactions WHERE "
    for name, predicate, parameter, mongo_filter in [
        ("equality", "doc ->> 'customerId' = %s", "864896", {"customerId": "864896"}),
        (
            "range",
            "(doc #>> '{payment,purchasePrice}')::numeric < %s",
            2,
            {"payment.purchasePrice": {"$lt": 2}},
        ),
        (
            "containment",
            "doc @> %s",
            Jsonb({"item": {"brandId": "10016"}}),
            {"item.brandId": "10016"},
        ),
    ]:
        expected = [(doc["_id"],) for doc in collection.find(mongo_filter, {"_id": 1})]
        yield name, select_ids + predicate, (parameter,), expected

    groups = collection.aggregate([{"$group": {"_id": "$locationId", "n": {"$sum": 1}}}])
    yield (
        "aggregation",
        "SELECT doc ->> 'locationId', count(*) FROM beer_factory.transactions GROUP BY 1",
        (),
        [(row["_id"], row["n"]) for row in groups],
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="new file for native plans and counts")
    args = parser.parse_args()
    uri = os.environ["SPIKE_MONGO_URI"]
    with MongoClient(uri) as client, psycopg.connect(os.environ["SPIKE_PG_DSN"]) as pg:
        db = client[SCHEMA]
        # Require empty destinations before invoking the existing non-atomic loader.
        if (
            db.list_collection_names()
            or pg.execute("SELECT to_regnamespace('beer_factory')").fetchone()[0]
        ):
            raise ValueError("Use fresh disposable databases")
        report = {
            "revision": REVISION,
            "driver": psycopg.__version__,
            "postgres": pg.execute("SHOW server_version").fetchone()[0],
            "counts": load(pg, db, uri),
            "phases": {},
        }
        queries = list(cases(db.transactions))
        for phase in ["before", "after"]:
            if phase == "after":
                pg.execute(
                    "CREATE INDEX tx_customer ON beer_factory.transactions ((doc ->> 'customerId'))"
                )
                pg.execute(
                    "CREATE INDEX tx_price ON beer_factory.transactions "
                    "(((doc #>> '{payment,purchasePrice}')::numeric))"
                )
                pg.execute("CREATE INDEX tx_doc ON beer_factory.transactions USING gin (doc)")
                pg.execute("ANALYZE beer_factory.transactions")
            observations = {}
            for name, statement, params, expected in queries:
                rows = pg.execute(statement, params).fetchall()
                if sorted(rows) != sorted(expected):
                    raise AssertionError(f"{phase} {name} differs from MongoDB")
                observations[name] = {"rows": len(rows)}
                for label, options in [
                    ("explain", "FORMAT JSON"),
                    ("profile", "ANALYZE, BUFFERS, FORMAT JSON"),
                ]:
                    plan = pg.execute(f"EXPLAIN ({options}) " + statement, params).fetchone()[0]
                    observations[name][label] = plan
            report["phases"][phase] = observations

        with args.output.open("x") as stream:
            json.dump(report, stream, indent=2)
            stream.write("\n")


if __name__ == "__main__":
    main()
