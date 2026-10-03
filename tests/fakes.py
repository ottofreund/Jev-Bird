"""Shared local action provider for deterministic controller and loop tests."""

import concurrent.futures

from jev_bird.decisions import GameAction, JevState


class FakeJev:
    def __init__(self) -> None:
        self.requests: list[JevState] = []
        self.futures: list[concurrent.futures.Future[GameAction]] = []
        self.closed = False

    def get_action(self, state: JevState) -> concurrent.futures.Future[GameAction]:
        future: concurrent.futures.Future[GameAction] = concurrent.futures.Future()
        self.requests.append(state)
        self.futures.append(future)
        return future

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True
        for future in self.futures:
            future.cancel()
