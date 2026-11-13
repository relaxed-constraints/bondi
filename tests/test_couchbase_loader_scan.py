"""Replacement and scan cleanup regressions without database writes."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

pytest.importorskip("couchbase")

from bondi.couchbase import CouchbaseCollectionRef
from bondi.data import CouchbaseConnection, LoadDataError, load_documents
from bondi.data._writers import CouchbaseWriter

DEST = ("travel", "_default", "users")


@pytest.fixture
def writer():
    writer = CouchbaseWriter.__new__(CouchbaseWriter)
    writer.cluster = Mock()
    writer.buckets = {"travel": Mock()}
    manager = writer.buckets["travel"].collections.return_value
    manager.get_all_scopes.return_value = [
        SimpleNamespace(name="_default", collections=[SimpleNamespace(name="users")])
    ]
    writer._scan = Mock()
    return writer


@pytest.mark.parametrize("new_scope", [False, True])
def test_replace_new_collection_does_not_scan(writer, new_scope):
    manager = writer.buckets["travel"].collections.return_value
    manager.get_all_scopes.return_value = (
        [] if new_scope else [SimpleNamespace(name="_default", collections=[])]
    )
    writer.prepare(DEST, "replace")
    manager.create_collection.assert_called_once_with("_default", "users")
    assert manager.create_scope.call_count == int(new_scope)
    writer._scan.assert_not_called()


def test_creation_race_propagates_without_scanning(writer):
    manager = writer.buckets["travel"].collections.return_value
    manager.get_all_scopes.return_value = []
    error = RuntimeError("collection already exists")
    manager.create_collection.side_effect = error
    with pytest.raises(RuntimeError) as caught:
        writer.prepare(DEST, "replace")
    assert caught.value is error
    writer._scan.assert_not_called()


@pytest.mark.parametrize("operation", ["preflight", "prepare"])
def test_scan_failure_not_masked_by_cancellation(writer, operation):
    error = RuntimeError("original scan failure")
    scan = Mock()
    scan.__iter__ = Mock(side_effect=error)
    scan.cancel_scan.side_effect = AttributeError("scan iterator is None")
    writer._scan.return_value = scan
    with pytest.raises(RuntimeError) as caught:
        if operation == "preflight":
            writer.preflight(DEST, None)
        else:
            writer.prepare(DEST, "replace")
    assert caught.value is error
    scan.cancel_scan.assert_called_once_with()


def test_replace_existing_collection_removes_documents_and_cancels(writer):
    scan = Mock()
    scan.__iter__ = Mock(return_value=iter([SimpleNamespace(id="old")]))
    writer._scan.return_value = scan
    writer.prepare(DEST, "replace")
    writer._collection(DEST).remove.assert_called_once_with("old")
    scan.cancel_scan.assert_called_once_with()
    writer.buckets["travel"].collections.return_value.create_collection.assert_not_called()


def test_delete_failure_not_masked_by_cancellation(writer):
    scan = Mock()
    scan.__iter__ = Mock(return_value=iter([SimpleNamespace(id="old")]))
    scan.cancel_scan.side_effect = AttributeError("cleanup failed")
    writer._scan.return_value = scan
    error = RuntimeError("delete failed")
    writer._collection(DEST).remove.side_effect = error
    with pytest.raises(RuntimeError) as caught:
        writer.prepare(DEST, "replace")
    assert caught.value is error
    scan.cancel_scan.assert_called_once_with()


def test_cleanup_failure_without_primary_error_is_visible(writer):
    scan = Mock()
    scan.__iter__ = Mock(return_value=iter([]))
    scan.cancel_scan.side_effect = RuntimeError("cleanup failed")
    writer._scan.return_value = scan
    with pytest.raises(RuntimeError, match="cleanup failed"):
        writer.preflight(DEST, None)


def test_public_loader_reports_original_error_type_without_credentials(writer, monkeypatch):
    class OriginalScanError(Exception):
        pass

    scan = Mock()
    scan.__iter__ = Mock(side_effect=OriginalScanError("secret URI"))
    scan.cancel_scan.side_effect = AttributeError("secondary failure")
    writer._scan.return_value = scan
    monkeypatch.setattr("bondi.data._loader.CouchbaseWriter", lambda target: writer)
    with pytest.raises(LoadDataError, match="destination preparation: OriginalScanError") as caught:
        load_documents(
            [{"_id": "a"}],
            target=CouchbaseConnection("couchbase://unused", "user", "secret"),
            collection=CouchbaseCollectionRef(*DEST),
            mode="replace",
        )
    assert "secret" not in str(caught.value)
    assert "AttributeError" not in str(caught.value)
    writer.cluster.close.assert_called_once_with()
