"""Asynchronous TypeSafe API adapter with an owned background event loop."""

import asyncio
import concurrent.futures
import logging
import threading
import time

from typesafe_sdk import AsyncTypeSafeClient, Choice

from .decisions import ActionDecision, GameAction, JevState


LOGGER = logging.getLogger(__name__)
ACTION_INSTRUCTIONS = "Which action best avoids colliding with the next pipe?"
ACTION_CRITERIA = {
    GameAction.JUMP.value: (
        "Choose jump when the semantic position and motion indicate that an upward "
        "correction is needed. Use the next-pipe distance and gap geometry to avoid "
        "jumping too early."
    ),
    GameAction.FALL.value: (
        "Choose fall when the semantic position and motion indicate that no upward "
        "correction is needed. Use the next-pipe distance and gap geometry to avoid "
        "falling too late."
    ),
}


class Jev:
    def __init__(self, client: AsyncTypeSafeClient | None = None) -> None:
        self.client = client if client is not None else AsyncTypeSafeClient()
        self._owns_client = client is None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_ready = threading.Event()
        self._lifecycle_lock = threading.Lock()
        self._closed = False
        self._thread = threading.Thread(
            target=self._run_event_loop,
            name="Jev event loop",
            daemon=True,
        )
        self._thread.start()
        self._loop_ready.wait()

    def _run_event_loop(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._loop_ready.set()
        try:
            loop.run_forever()
        finally:
            asyncio.set_event_loop(None)
            loop.close()

    def get_action(
        self, state: JevState
    ) -> concurrent.futures.Future[ActionDecision]:
        with self._lifecycle_lock:
            if self._closed:
                raise RuntimeError("Jev is closed")

            assert self._loop is not None
            return asyncio.run_coroutine_threadsafe(
                self._get_action(state),
                self._loop,
            )

    async def _get_action(self, state: JevState) -> ActionDecision:
        started_at = time.perf_counter()
        response = await self.client.system_one(
            state=state,
            questions={
                "action": Choice(
                    instructions=ACTION_INSTRUCTIONS,
                    criteria=ACTION_CRITERIA,
                )
            },
        )
        elapsed_seconds = time.perf_counter() - started_at
        LOGGER.info("JEV response time: %.3f seconds", elapsed_seconds)
        answer = response.answers["action"]
        return ActionDecision(
            action=GameAction(answer.choice),
            confidence=answer.confidence,
        )

    async def _shutdown(self) -> None:
        current_task = asyncio.current_task()
        pending_tasks = [
            task
            for task in asyncio.all_tasks()
            if task is not current_task and not task.done()
        ]
        for task in pending_tasks:
            task.cancel()
        if pending_tasks:
            await asyncio.gather(*pending_tasks, return_exceptions=True)

        if self._owns_client:
            await self.client.aclose()

    def close(self) -> None:
        with self._lifecycle_lock:
            if self._closed:
                return
            self._closed = True
            assert self._loop is not None
            shutdown_future = asyncio.run_coroutine_threadsafe(
                self._shutdown(),
                self._loop,
            )

        try:
            shutdown_future.result()
        finally:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join()

    def __enter__(self) -> "Jev":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()
