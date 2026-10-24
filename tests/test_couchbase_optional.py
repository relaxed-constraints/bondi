"""Query descriptions must remain usable without the optional execution SDK."""

import subprocess
import sys


def test_queries_without_sdk_and_actionable_executor_error():
    code = """
import builtins
original_import = builtins.__import__
def without_sdk(name, *args, **kwargs):
    if name.split('.')[0] in ('couchbase', 'acouchbase'):
        raise ModuleNotFoundError(name, name=name)
    return original_import(name, *args, **kwargs)
builtins.__import__ = without_sdk
from dbrtoolkit.couchbase import CouchbaseQuery, AsyncCouchbaseExecutor
from dbrtoolkit.workload import Workload, WorkloadEntry
from dbrtoolkit.execution import ExecutionResult
query = CouchbaseQuery('SELECT RAW 1')
assert CouchbaseQuery.from_json(query.to_json()) == query
assert len(Workload([WorkloadEntry(query)])) == 1
assert ExecutionResult(1, error=ValueError('bad')).status == 'error'
try:
    AsyncCouchbaseExecutor(None)
except ImportError as error:
    assert 'uv sync --extra couchbase' in str(error)
else:
    raise AssertionError('Missing SDK did not produce an installation hint')
"""
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True, text=True)
