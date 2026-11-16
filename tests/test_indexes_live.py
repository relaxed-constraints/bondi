"""Index DDL and readiness checks on disposable deployments only."""

import pytest
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError

from bondi import FieldIndex, IndexSet
from bondi.couchbase import CouchbaseCollectionRef, CouchbaseIndex
from bondi.couchbase import create_index as cb_create
from bondi.couchbase import create_indexes as cb_many
from bondi.mongodb import MongoCollectionRef, MongoIndex, create_index, create_indexes

pytestmark = pytest.mark.live


def test_mongodb_indexes(live_mongodb, tmp_path):
    target = MongoCollectionRef("demo", "business")
    indexes = IndexSet(
        {
            "business": [
                FieldIndex((("_id", 1),)),
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
        live_mongodb, indexes=IndexSet.load(tmp_path / "indexes.json"), targets={"business": target}
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
        create_index(live_mongodb, target=target, index=indexes["business"][1])
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
        db, indexes=IndexSet.load(tmp_path / "indexes.json"), targets={"business": target}
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
