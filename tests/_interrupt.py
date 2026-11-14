"""Portable interruption of the synchronous executor wait in tests."""


def interrupt_sync_wait(monkeypatch, started, *, ready_timeout=3):
    from concurrent.futures import Future

    class InterruptibleFuture(Future):
        def result(self, timeout=None):
            if timeout is None and not self.done():
                assert started.wait(ready_timeout)
                raise KeyboardInterrupt
            return super().result(timeout)

    # Interrupt the caller after the operation starts, without OS signal delivery.
    monkeypatch.setattr("bondi._sync.Future", InterruptibleFuture)
