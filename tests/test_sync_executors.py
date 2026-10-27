"""Exercise synchronous lifecycles without database dependencies."""

import asyncio
import inspect
from concurrent.futures import ThreadPoolExecutor

import pytest

from dbrtoolkit.couchbase import AsyncCouchbaseExecutor, CouchbaseExecutor
from dbrtoolkit.mongodb import AsyncMongoExecutor, MongoExecutor

PAIRS = [
    (MongoExecutor, AsyncMongoExecutor, {}),
    (CouchbaseExecutor, AsyncCouchbaseExecutor, {"username": "u", "password": "p"}),
]
METHODS = ("run", "explain", "profile", "run_workload", "explain_workload", "profile_workload")


@pytest.fixture(params=PAIRS)
def adapter(request, monkeypatch):
    sync, asynchronous, options = request.param
    created = []

    class Fake:
        def __init__(self):
            self.loop = asyncio.get_running_loop()
            self.closed = 0

        async def close(self):
            assert asyncio.get_running_loop() is self.loop
            self.closed += 1

        def __getattr__(self, name):
            async def call(*args, **kwargs):
                assert asyncio.get_running_loop() is self.loop
                if args == ("fail",):
                    raise ValueError("query failed")
                await asyncio.sleep(0)
                return name, args, kwargs

            return call

    def factory(*args, **kwargs):
        fake = Fake()
        created.append(fake)
        return fake

    async def async_factory(*args, **kwargs):
        return factory(*args, **kwargs)

    monkeypatch.setattr(
        asynchronous,
        "from_uri",
        async_factory if asynchronous is AsyncCouchbaseExecutor else factory,
    )
    return sync, options, created


def test_operations_and_cleanup(adapter):
    sync, options, created = adapter
    executor = sync.from_uri("unused", **options)
    for name in METHODS:
        result = getattr(executor, name)("input", query_kwargs={"test": 1})
        assert result[:2] == (name, ("input",))
        assert result[2]["query_kwargs"] == {"test": 1}
    executor.close()
    executor.close()
    assert created[0].closed == 1
    assert created[0].loop.is_closed()
    with pytest.raises(RuntimeError, match="closed"):
        executor.run("input")


@pytest.mark.parametrize("sync,asynchronous,options", PAIRS)
def test_signature_parity(sync, asynchronous, options):
    for name in (*METHODS, "from_uri"):
        assert inspect.signature(getattr(sync, name), eval_str=True) == inspect.signature(
            getattr(asynchronous, name), eval_str=True
        )


def test_exception_cleanup(adapter):
    sync, options, created = adapter
    with pytest.raises(ValueError, match="query failed"):
        with sync.from_uri("unused", **options) as executor:
            executor.run("fail")
    assert created[0].closed == 1
    assert created[0].loop.is_closed()


def test_guards(adapter):
    sync, options, created = adapter
    executor = sync.from_uri("unused", **options)

    async def check():
        with sync.from_uri("unused", **options) as notebook_executor:
            assert notebook_executor.run("input")[0] == "run"
            assert notebook_executor._loop is not asyncio.get_running_loop()
        assert executor.run("input")[0] == "run"

    asyncio.run(check())
    with ThreadPoolExecutor() as pool:
        with pytest.raises(RuntimeError, match="creating thread"):
            pool.submit(executor.run, "input").result()
    executor.close()


@pytest.mark.parametrize("sync,asynchronous,options", PAIRS)
def test_failed_factory_closes_loop(sync, asynchronous, options, monkeypatch):
    loops = []

    def fail(*args, **kwargs):
        loops.append(asyncio.get_running_loop())
        raise ValueError("connection failed")

    async def async_fail(*args, **kwargs):
        return fail()

    monkeypatch.setattr(
        asynchronous, "from_uri", async_fail if asynchronous is AsyncCouchbaseExecutor else fail
    )
    with pytest.raises(ValueError, match="connection failed"):
        sync.from_uri("unused", **options)
    assert loops[0].is_closed()


@pytest.mark.parametrize("during_close", [False, True])
def test_interrupt_waits_for_cleanup(adapter, monkeypatch, during_close):
    import os
    import signal
    from threading import Event, Thread

    sync, options, created = adapter
    executor = sync.from_uri("unused", **options)
    started = Event()
    cleaned = Event()

    async def slow():
        started.set()
        try:
            await asyncio.sleep(0.15 if during_close else 30)
        finally:
            await asyncio.sleep(0.02)
            cleaned.set()

    def interrupt():
        assert started.wait(3)
        os.kill(os.getpid(), signal.SIGINT)

    sender = Thread(target=interrupt)
    sender.start()
    try:
        with pytest.raises(KeyboardInterrupt):
            if during_close:
                monkeypatch.setattr(executor._executor, "close", slow)
                executor.close()
            else:
                executor._submit(slow)
        assert cleaned.is_set()
        if not during_close:
            assert executor.run("after interrupt")[0] == "run"
    finally:
        sender.join()
        executor.close()
    assert not executor._worker.is_alive()
    assert executor._loop.is_closed()


@pytest.mark.parametrize("sync,asynchronous,options", PAIRS)
def test_interrupted_factory_unwinds(sync, asynchronous, options, monkeypatch):
    import os
    import signal
    from threading import Event, Thread

    started, cleaned = Event(), Event()
    loops = []

    async def factory(*args, **kwargs):
        loops.append(asyncio.get_running_loop())
        started.set()
        try:
            await asyncio.sleep(30)
        finally:
            await asyncio.sleep(0.01)
            cleaned.set()

    # Both adapter factories await their private connect coroutine. Mongo's public
    # factory is synchronous, so exercise the common bridge directly for this case.
    def interrupt():
        if started.wait(3):
            os.kill(os.getpid(), signal.SIGINT)

    sender = Thread(target=interrupt)
    sender.start()
    try:
        with pytest.raises(KeyboardInterrupt):
            sync._create(factory)
    finally:
        sender.join()
    assert cleaned.is_set()
    assert loops[0].is_closed()


def test_close_error_still_stops_thread(adapter, monkeypatch):
    sync, options, created = adapter
    executor = sync.from_uri("unused", **options)

    async def fail():
        raise ValueError("close failed")

    monkeypatch.setattr(executor._executor, "close", fail)
    with pytest.raises(ValueError, match="close failed"):
        executor.close()
    executor.close()
    assert executor._loop.is_closed()
    assert not executor._worker.is_alive()
