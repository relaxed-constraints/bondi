"""Index DDL and readiness checks on disposable deployments only."""

import pytest
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError

from bondi import FieldIndex, IndexSet
from bondi.couchbase import CouchbaseCollectionRef, CouchbaseIndex
from bondi.couchbase import create_couchbase_index as cb_create
from bondi.couchbase import create_couchbase_indexes as cb_many
from bondi.mongodb import MongoCollectionRef, MongoIndex
from bondi.mongodb import create_mongo_index as create_index
from bondi.mongodb import create_mongo_indexes as create_indexes

pytestmark = pytest.mark.live


def test_mongodb_indexes(live_mongodb, tmp_path):
    target = MongoCollectionRef("demo", "business")
    indexes = IndexSet(
        {
            "business": [
                FieldIndex((("_id", 1),)),
                FieldIndex((("Model Year", 1), ("item.Model Year", -1)), name="spaced_fields"),
                FieldIndex((("city", 1), ("stars", -1)), name="bondi_city_stars"),
                MongoIndex((("name", 1),), name="bondi_unique_name", unique=True),
                MongoIndex(
                    (("stars", 1),), name="bondi_partial", partial_filter={"stars": {"$gt": 3}}
                ),
                MongoIndex((("optional", 1),), name="bondi_sparse", sparse=True),
            ]
        }
    )
    indexes.save(tmp_path / "indexes.json")
    names = create_indexes(
        live_mongodb, indexes=IndexSet.load(tmp_path / "indexes.json"), database="demo"
    )
    assert names["business"][0] == "_id_"
    with MongoClient(live_mongodb.uri) as client:
        collection = client.demo.business
        definitions = collection.index_information()
        assert definitions["bondi_unique_name"]["unique"]
        assert definitions["bondi_sparse"]["sparse"]
        assert definitions["bondi_partial"]["partialFilterExpression"] == {"stars": {"$gt": 3}}
        assert definitions["bondi_city_stars"]["key"] == [("city", 1), ("stars", -1)]
        with pytest.raises(DuplicateKeyError):
            collection.insert_one({"name": collection.find_one()["name"]})
    assert (
        create_index(live_mongodb, target=target, index=indexes["business"][2])
        == "bondi_city_stars"
    )


def test_couchbase_indexes(live_deployments, tmp_path):
    pytest.importorskip("couchbase")
    from couchbase.auth import PasswordAuthenticator
    from couchbase.cluster import Cluster
    from couchbase.options import ClusterOptions

    db = live_deployments("community")
    target = CouchbaseCollectionRef("demo", "_default", "business")
    indexes = IndexSet(
        {
            "business": [
                FieldIndex((("city", 1), ("stars", -1)), name="bondi_shared"),
                FieldIndex((("Model Year", 1), ("item.Model Year", -1)), name="spaced_fields"),
                CouchbaseIndex(
                    (("LOWER(`name`)", 1),),
                    name="bondi_functional",
                    condition="`stars` > 3",
                    include_missing=True,
                ),
                CouchbaseIndex(
                    (("DISTINCT ARRAY t FOR t IN `tags` END", 1),),
                    name="bondi_array",
                    include_missing=True,
                ),
            ]
        }
    )
    indexes.save(tmp_path / "indexes.json")
    result = cb_many(
        db, indexes=IndexSet.load(tmp_path / "indexes.json"), bucket="demo", scope="_default"
    )
    cluster = Cluster(db.uri, ClusterOptions(PasswordAuthenticator(db.username, db.password)))
    try:
        manager = cluster.bucket("demo").scope("_default").collection("business").query_indexes()
        observed = {index.name: index for index in manager.get_all_indexes()}
        assert all(observed[name].state == "online" for name in result["business"])
        assert observed["bondi_functional"].condition
        assert "DISTINCT" in observed["bondi_array"].index_key[0].upper()
        with pytest.raises(Exception):
            cb_create(db, target=target, index=indexes["business"][0])
    finally:
        cluster.close()


def test_mongodb_index_lifecycle(live_mongodb):
    from bondi import create_index, create_indexes, remove_index, remove_indexes

    target = MongoCollectionRef("lifecycle", "records")
    old = FieldIndex((("old", 1),), name="old")
    new = FieldIndex((("new", -1),), name="new")
    with MongoClient(live_mongodb.uri) as client:
        collection = client.lifecycle.records
        collection.insert_one({"old": 1, "new": 2})
        collection.create_index("external", name="external")
        client.lifecycle.untouched.insert_one({"x": 1})
        client.lifecycle.untouched.create_index("x", name="keep")
        create_index(live_mongodb, target=target, index=old)
        assert create_indexes(
            live_mongodb, database="lifecycle", indexes=IndexSet({"records": [new]}), replace=True
        ) == {"records": ["new"]}
        assert set(collection.index_information()) == {"_id_", "new"}
        assert "keep" in client.lifecycle.untouched.index_information()
        assert remove_index(live_mongodb, target=target, index=new)
        assert not remove_index(live_mongodb, target=target, index=new)
        create_index(live_mongodb, target=target, index=new)
        assert remove_indexes(
            live_mongodb, database="lifecycle", indexes=IndexSet({"records": [new]})
        ) == {"records": ["new"]}
        create_index(live_mongodb, target=target, index=new)
        create_indexes(
            live_mongodb, database="lifecycle", indexes=IndexSet({"records": []}), replace=True
        )
        assert set(collection.index_information()) == {"_id_"}
        with pytest.raises(ValueError, match="protected"):
            remove_index(live_mongodb, target=target, index=FieldIndex((("_id", 1),)))


def test_couchbase_index_lifecycle(live_deployments):
    pytest.importorskip("couchbase")
    from couchbase.auth import PasswordAuthenticator
    from couchbase.cluster import Cluster
    from couchbase.options import ClusterOptions

    from bondi import create_index as cb_create
    from bondi import create_indexes as cb_many
    from bondi import remove_index, remove_indexes

    db = live_deployments("community")
    target = CouchbaseCollectionRef("demo", "_default", "business")
    cluster = Cluster(db.uri, ClusterOptions(PasswordAuthenticator(db.username, db.password)))
    try:
        manager = cluster.bucket("demo").scope("_default").collection("business").query_indexes()
        cluster.query(
            "CREATE PRIMARY INDEX `lifecycle_primary` ON `demo`.`_default`.`business`"
        ).execute()
        new = FieldIndex((("city", -1),), name="lifecycle_new")
        result = cb_many(
            db, bucket="demo", scope="_default", indexes=IndexSet({"business": [new]}), replace=True
        )
        assert result == {"business": ["lifecycle_new"]}
        observed = manager.get_all_indexes()
        assert {i.name for i in observed if not i.is_primary} == {"lifecycle_new"}
        assert any(i.name == "lifecycle_primary" and i.is_primary for i in observed)
        with pytest.raises(ValueError, match="protected"):
            remove_index(db, target=target, index=FieldIndex((("x", 1),), name="lifecycle_primary"))
        assert remove_index(db, target=target, index=new)
        assert not remove_index(db, target=target, index=new)
        cb_create(db, target=target, index=new)
        assert remove_indexes(
            db, bucket="demo", scope="_default", indexes=IndexSet({"business": [new]})
        ) == {"business": ["lifecycle_new"]}
        cb_create(db, target=target, index=new)
        cb_many(
            db, bucket="demo", scope="_default", indexes=IndexSet({"business": []}), replace=True
        )
        assert all(i.is_primary for i in manager.get_all_indexes())
    finally:
        cluster.close()
