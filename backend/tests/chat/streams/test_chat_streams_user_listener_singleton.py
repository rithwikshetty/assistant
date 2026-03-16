import asyncio
from contextlib import suppress

from app.services import chat_streams


def test_start_user_event_listener_is_singleton_under_concurrency(monkeypatch) -> None:
    async def _run() -> None:
        existing = chat_streams._user_listener_task
        if existing is not None and not existing.done():
            existing.cancel()
            with suppress(asyncio.CancelledError):
                await existing
        chat_streams._user_listener_task = None
        chat_streams._local_user_subscribers.clear()

        started = asyncio.Event()
        release = asyncio.Event()
        run_calls = 0

        async def _fake_run_listener() -> None:
            nonlocal run_calls
            run_calls += 1
            started.set()
            await release.wait()

        monkeypatch.setattr(chat_streams, "_run_user_event_listener", _fake_run_listener)

        created_tasks = 0
        real_create_task = chat_streams.asyncio.create_task

        def _counting_create_task(coro):
            nonlocal created_tasks
            created_tasks += 1
            return real_create_task(coro)

        monkeypatch.setattr(chat_streams.asyncio, "create_task", _counting_create_task)

        await asyncio.gather(*[chat_streams._start_user_event_listener() for _ in range(25)])
        await asyncio.wait_for(started.wait(), timeout=1.0)

        assert run_calls == 1
        assert created_tasks == 1
        assert chat_streams._user_listener_task is not None
        assert not chat_streams._user_listener_task.done()

        release.set()
        await asyncio.wait_for(chat_streams._user_listener_task, timeout=1.0)
        chat_streams._user_listener_task = None

    asyncio.run(_run())
