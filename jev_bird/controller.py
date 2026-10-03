"""Apply asynchronous actions, track latency, and retain failure-review snapshots."""

from __future__ import annotations

import concurrent.futures
import logging
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from .decisions import (
    ActionDecision,
    CompletedDecision,
    DecisionSnapshot,
    DecisionView,
    GameAction,
    JevState,
)
from .game import GameState


INITIAL_RESPONSE_SECONDS = 0.25
MAX_BUFFERED_REQUESTS = 12
LOGGER = logging.getLogger(__name__)


class ActionProvider(Protocol):
    """An action source that may complete after the game has advanced."""

    def get_action(
        self, state: JevState
    ) -> (
        concurrent.futures.Future[ActionDecision]
        | concurrent.futures.Future[GameAction]
    ):
        ...


@dataclass
class _PendingRequest:
    """Keep a response inseparable from the state and time that produced it."""

    future: (
        concurrent.futures.Future[ActionDecision]
        | concurrent.futures.Future[GameAction]
    )
    snapshot: DecisionSnapshot
    started_at: float
    apply_at: float
    completed_at: float | None = None


class GameController:
    """Coordinate game rules and an action provider without depending on a viewer."""

    def __init__(
        self,
        state: GameState,
        action_provider: ActionProvider,
        *,
        now: Callable[[], float] = time.perf_counter,
    ) -> None:
        self.state = state
        self._action_provider = action_provider
        self._now = now
        self.average_response_seconds = INITIAL_RESPONSE_SECONDS
        self._response_count = 0
        self._pending_requests: deque[_PendingRequest] = deque()
        self._last_applied_decision: CompletedDecision | None = None
        self._decision_view = DecisionView()
        self._request_on_next_update = False

    @property
    def decision_view(self) -> DecisionView:
        """Retain the last failed run's final applied decision until another crash."""
        return self._decision_view

    def pause(self) -> None:
        """Discard work based on a timeline that is about to stop advancing."""
        self._discard_buffered_requests()
        self._request_on_next_update = False

    def resume(self) -> None:
        """Request an action from the current frozen state on the next update."""
        self._request_on_next_update = True

    def close(self) -> None:
        """Detach and cancel all action work during application shutdown."""
        self._discard_buffered_requests()
        self._request_on_next_update = False

    def update(self, elapsed_seconds: float, *, request_due: bool = False) -> None:
        self.state.update(elapsed_seconds)
        if self.state.game_over:
            self._restart_after_failure()
            return

        self._consume_actions()
        if (
            (request_due or self._request_on_next_update)
            and len(self._pending_requests) < MAX_BUFFERED_REQUESTS
        ):
            self._request_action()

    def _restart_after_failure(self) -> None:
        self._decision_view = DecisionView(
            completed=self._last_applied_decision, failure_recorded=True
        )
        self._discard_buffered_requests()
        self._last_applied_decision = None
        self.state.reset()
        self._request_on_next_update = True

    def _discard_buffered_requests(self) -> None:
        requests = tuple(self._pending_requests)
        self._pending_requests.clear()
        # Cancellation can fail once work is running, so detach every request
        # before trying to stop its future.
        for request in requests:
            request.future.cancel()

    def _remove_failed_requests(self) -> None:
        """Free capacity for failures without reordering successful decisions."""
        retained: deque[_PendingRequest] = deque()
        for request in self._pending_requests:
            if not request.future.done():
                retained.append(request)
                continue
            try:
                request.future.result()
            except concurrent.futures.CancelledError:
                continue
            except Exception:
                LOGGER.exception("Failed to get JEV action")
                continue
            retained.append(request)
        self._pending_requests = retained

    def _consume_actions(self) -> None:
        self._remove_failed_requests()
        while self._pending_requests:
            request = self._pending_requests[0]
            if not request.future.done():
                return

            # A completed future can become visible just before its callbacks finish.
            if request.completed_at is None:
                return

            if self._now() < request.apply_at:
                return

            result = request.future.result()
            self._pending_requests.popleft()

            if isinstance(result, ActionDecision):
                action = result.action
                confidence = result.confidence
            else:
                # Keep simple local action providers usable without the API SDK.
                action = result
                confidence = None

            response_seconds = request.completed_at - request.started_at
            self._response_count += 1
            self.average_response_seconds += (
                response_seconds - self.average_response_seconds
            ) / self._response_count
            self._last_applied_decision = CompletedDecision(
                snapshot=request.snapshot,
                action=action,
                response_seconds=response_seconds,
                confidence=confidence,
            )
            if action == GameAction.JUMP:
                self.state.flap()
            LOGGER.info("JEV action: %s", action.name)
            LOGGER.info(
                "JEV action latency: %.3f seconds (average: %.3f seconds)",
                response_seconds,
                self.average_response_seconds,
            )

            if action == GameAction.JUMP:
                self._discard_buffered_requests()
                self._request_action()
                return

    def _request_action(self) -> None:
        self._request_on_next_update = False
        snapshot = self.state.capture_decision_snapshot(self.average_response_seconds)
        started_at = self._now()
        try:
            future = self._action_provider.get_action(snapshot.to_state_dict())
        except Exception:
            LOGGER.exception("Failed to submit JEV action request")
            return

        request = _PendingRequest(
            future=future,
            snapshot=snapshot,
            started_at=started_at,
            apply_at=started_at + snapshot.prediction_seconds,
        )
        self._pending_requests.append(request)
        future.add_done_callback(
            lambda _future: self._record_completion_time(request)
        )

    def _record_completion_time(self, request: _PendingRequest) -> None:
        request.completed_at = self._now()
