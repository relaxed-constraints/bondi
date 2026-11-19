"""Shared settings, deployment bridges and client ownership at API boundaries."""

import asyncio
from dataclasses import FrozenInstanceError
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bondi import (
    CouchbaseConnection,
    IndexSet,
    MongoConnection,
    create_indexes,
    remove_indexes,
)
from bondi.couchbase import AsyncCouchbaseExecutor, CouchbaseExecutor
from bondi.data import (
    load_aptmql_dataset,
    load_aptmql_repository,
    load_demo_data,
    load_documents,
    load_file,
    load_hf_dataset,
    load_hf_repository,
)
from bondi.deployment import Deployment
from bondi.mongodb import AsyncMongoExecutor, MongoCollectionRef, MongoExecutor


def deployment(tmp_path, backend="mongodb"):
    return Deployment(
        "settings",
        27019 if backend == "mongodb" else 8191,
        "test:1",
        tmp_path,
        "test-settings",
        backend=backend,
        kv_port=11310 if backend == "couchbase" else None,
        username="researcher",
        password="secret",
    )


@pytest.mark.parametrize("backend", ["mongodb", "couchbase"])
def test_deployment_settings_are_pure_immutable_and_redacted(tmp_path, backend):
    db = deployment(tmp_path, backend)
    expected_type = MongoConnection if backend == "mongodb" else CouchbaseConnection
    with patch.object(Deployment, "_run", side_effect=AssertionError("Docker access")):
        settings = db.connection
    assert isinstance(settings, expected_type)
    assert settings.uri == db.uri
    assert (settings.username, settings.password) == ("researcher", "secret")
    assert "secret" not in repr(settings)
    assert settings.uri not in repr(settings)
    with pytest.raises(FrozenInstanceError):
        settings.password = "changed"


@pytest.mark.parametrize("backend", ["mongodb", "couchbase"])
def test_start_and_stop_return_same_handle(tmp_path, backend):
    db = deployment(tmp_path, backend)
    with (
        patch.object(Deployment, "_run", return_value="") as run,
        patch("bondi.deployment._couchbase.initialize") as initialize,
    ):
        assert db.start() is db
        assert db.stop() is db
    assert run.call_count == 2
    assert initialize.call_count == (1 if backend == "couchbase" else 0)


@pytest.mark.parametrize("keep_data", [False, True])
def test_remove_returns_none_and_preserves_existing_data_policy(tmp_path, keep_data):
    db = deployment(tmp_path / "saved")
    db._path.mkdir()
    with patch.object(Deployment, "_run", return_value="") as run:
        assert db.remove(keep_data=keep_data) is None
    assert db._path.exists() is keep_data
    expected = ("down",) if keep_data else ("down", "--volumes")
    assert run.call_args.args == expected


@pytest.mark.parametrize("credentials", [{}, {"username": "override"}, {"password": "p@ss:/%"}])
def test_mongo_executor_forwards_settings_without_reencoding(credentials):
    uri = "mongodb://uri-user:uri-pass@example/?authSource=admin"
    connection = MongoConnection(uri, **credentials)
    client = MagicMock()
    client.close = AsyncMock()
    with patch("bondi.mongodb.executor.AsyncMongoClient", return_value=client) as create:
        executor = AsyncMongoExecutor.from_connection(
            connection, client_kwargs={"appname": "research"}
        )
        create.assert_called_once_with(uri, appname="research", **credentials)
        asyncio.run(executor.close())
    client.close.assert_awaited_once()


@pytest.mark.parametrize("field", ["host", "username", "password", "HOST", "Username", "PASSWORD"])
def test_mongo_executor_rejects_duplicate_connection_options_before_creating_client(field):
    with patch("bondi.mongodb.executor.AsyncMongoClient") as create:
        with pytest.raises(ValueError, match="reserved"):
            AsyncMongoExecutor.from_connection(
                MongoConnection("mongodb://example"), client_kwargs={field: "value"}
            )
    create.assert_not_called()


@pytest.mark.parametrize(
    "factory", [MongoExecutor, AsyncMongoExecutor, CouchbaseExecutor, AsyncCouchbaseExecutor]
)
@pytest.mark.parametrize("invalid", ["uri", "deployment", "wrong_backend"])
def test_executor_factories_require_matching_settings(factory, invalid, tmp_path):
    is_mongo = factory in (MongoExecutor, AsyncMongoExecutor)
    value = {
        "uri": "mongodb://example",
        "deployment": deployment(tmp_path),
        "wrong_backend": (
            CouchbaseConnection("couchbase://example", "u", "p")
            if is_mongo
            else MongoConnection("mongodb://example")
        ),
    }[invalid]
    with pytest.raises(TypeError, match="connection must be a"):
        if factory is AsyncCouchbaseExecutor:
            asyncio.run(factory.from_connection(value))
        else:
            factory.from_connection(value)


@pytest.mark.parametrize("invalid", ["uri", "deployment"])
def test_all_loaders_and_index_dispatchers_require_settings(invalid, tmp_path):
    value = "mongodb://example" if invalid == "uri" else deployment(tmp_path)
    collection = MongoCollectionRef("db", "c")
    operations = [
        lambda: load_documents([], connection=value, collection=collection),
        lambda: load_file("missing.json", connection=value, collection=collection),
        lambda: load_demo_data(connection=value, collection=collection),
        lambda: load_hf_dataset("org/data", connection=value, collection=collection),
        lambda: load_hf_repository("org/data", connection=value, database="db"),
        lambda: load_aptmql_dataset("beer_factory", connection=value),
        lambda: load_aptmql_repository(connection=value),
        lambda: create_indexes(value, indexes=IndexSet({}), database="db"),
        lambda: remove_indexes(value, indexes=IndexSet({}), database="db"),
    ]
    for operation in operations:
        with pytest.raises(TypeError, match="Expected MongoConnection or CouchbaseConnection"):
            operation()


def test_couchbase_executor_forwards_settings_to_authenticator_and_cluster():
    pytest.importorskip("couchbase")
    connection = CouchbaseConnection("couchbases://example", "researcher", "p@ss:/%")
    client = MagicMock()
    client.wait_until_ready = AsyncMock()
    client.close = AsyncMock()

    async def scenario():
        with (
            patch("couchbase.auth.PasswordAuthenticator") as auth,
            patch("couchbase.options.ClusterOptions") as options,
            patch("acouchbase.cluster.Cluster.connect", AsyncMock(return_value=client)) as connect,
        ):
            executor = await AsyncCouchbaseExecutor.from_connection(
                connection, cluster_kwargs={"query_timeout": "native-option"}
            )
            auth.assert_called_once_with("researcher", "p@ss:/%")
            options.assert_called_once_with(auth.return_value, query_timeout="native-option")
            connect.assert_awaited_once_with(connection.uri, options.return_value)
            await executor.close()
        client.close.assert_awaited_once()

    asyncio.run(scenario())


def test_couchbase_executor_rejects_duplicate_authenticator_before_connecting():
    pytest.importorskip("couchbase")

    async def scenario():
        with patch("acouchbase.cluster.Cluster.connect", AsyncMock()) as connect:
            with pytest.raises(ValueError, match="reserved"):
                await AsyncCouchbaseExecutor.from_connection(
                    CouchbaseConnection("couchbase://example", "u", "p"),
                    cluster_kwargs={"authenticator": object()},
                )
            connect.assert_not_awaited()

    asyncio.run(scenario())


@pytest.mark.parametrize("uri", [None, 27017, ["mongodb://example"], {}])
@pytest.mark.parametrize("backend", ["mongodb", "couchbase"])
def test_connection_settings_reject_non_string_uri(uri, backend):
    with pytest.raises(TypeError, match="uri must be a string"):
        if backend == "mongodb":
            MongoConnection(uri)
        else:
            CouchbaseConnection(uri, "u", "p")
