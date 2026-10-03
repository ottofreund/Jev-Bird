import asyncio
import concurrent.futures
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from jev_bird.decisions import ActionDecision, GameAction
from jev_bird.jev import Jev


def action_response(action: GameAction, confidence: float = 0.87) -> SimpleNamespace:
    return SimpleNamespace(
        answers={
            "action": SimpleNamespace(choice=action.value, confidence=confidence)
        }
    )


class RecordingClient:
    def __init__(self) -> None:
        self.calls: list[tuple[int, asyncio.AbstractEventLoop, dict]] = []

    async def system_one(self, *, state: dict, questions: dict) -> SimpleNamespace:
        self.calls.append(
            (threading.get_ident(), asyncio.get_running_loop(), state)
        )
        return action_response(GameAction.JUMP)


class BlockingClient:
    def __init__(self) -> None:
        self.started = threading.Event()

    async def system_one(self, *, state: dict, questions: dict) -> SimpleNamespace:
        self.started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


class JevTests(unittest.TestCase):
    def test_close_releases_owned_client_once(self):
        client = SimpleNamespace(aclose=AsyncMock())
        with patch("jev_bird.jev.AsyncTypeSafeClient", return_value=client):
            jev = Jev()
        jev.close()
        jev.close()
        client.aclose.assert_awaited_once()
        self.assertFalse(jev._thread.is_alive())

    def test_close_does_not_release_borrowed_client(self):
        client = SimpleNamespace(aclose=AsyncMock())
        with Jev(client):
            pass
        client.aclose.assert_not_awaited()

    def test_get_action_returns_concurrent_future_and_reports_response_time(self):
        client = SimpleNamespace(
            system_one=AsyncMock(return_value=action_response(GameAction.JUMP))
        )
        state = {
            "bird": {"position": None, "motion": "level"},
            "next_pipe": None,
            "bird_jump_height": "Roughly third of pipe gap",
            "y_axis": "y grows downward; smaller y is higher up",
            "length_unit": "pixel",
        }

        with Jev(client) as jev:
            with (
                patch("jev_bird.jev.time.perf_counter", side_effect=[10.0, 10.25]),
                patch("jev_bird.jev.LOGGER") as logger,
            ):
                future = jev.get_action(state)
                action = future.result(timeout=1)

        self.assertIsInstance(future, concurrent.futures.Future)
        self.assertEqual(action, ActionDecision(GameAction.JUMP, 0.87))
        self.assertIs(client.system_one.await_args.kwargs["state"], state)
        logger.info.assert_called_once_with("JEV response time: %.3f seconds", 0.25)

    def test_choice_criteria_use_semantic_state_not_removed_clearances(self):
        client = SimpleNamespace(
            system_one=AsyncMock(return_value=action_response(GameAction.FALL))
        )
        state = {
            "bird": {"position": "below the gap", "motion": "falling"},
            "next_pipe": {
                "distance_x": "20",
                "gap_top_y": "180",
                "gap_bottom_y": "350",
            },
            "bird_jump_height": "Roughly third of pipe gap",
            "y_axis": "y grows downward; smaller y is higher up",
            "length_unit": "pixel",
        }

        with Jev(client) as jev:
            jev.get_action(state).result(timeout=1)

        question = client.system_one.await_args.kwargs["questions"]["action"]
        criteria_text = " ".join(question.criteria.values())
        self.assertIn("upward correction", criteria_text)
        self.assertIn("position", criteria_text)
        self.assertIn("motion", criteria_text)
        self.assertIn("distance", criteria_text)
        self.assertIn("gap geometry", criteria_text)
        self.assertNotIn("clearance", criteria_text)

    def test_requests_share_one_background_thread_and_event_loop(self):
        client = RecordingClient()

        with Jev(client) as jev:
            first = jev.get_action({"request": "first"}).result(timeout=1)
            second = jev.get_action({"request": "second"}).result(timeout=1)

        self.assertEqual(first, ActionDecision(GameAction.JUMP, 0.87))
        self.assertEqual(second, ActionDecision(GameAction.JUMP, 0.87))
        self.assertEqual(client.calls[0][0], client.calls[1][0])
        self.assertIs(client.calls[0][1], client.calls[1][1])
        self.assertNotEqual(client.calls[0][0], threading.get_ident())

    def test_close_stops_accepting_requests(self):
        client = RecordingClient()
        jev = Jev(client)

        jev.close()

        with self.assertRaisesRegex(RuntimeError, "Jev is closed"):
            jev.get_action({})

    def test_close_cancels_an_outstanding_request(self):
        client = BlockingClient()
        jev = Jev(client)
        future = jev.get_action({})
        self.assertTrue(client.started.wait(timeout=1))

        jev.close()

        self.assertTrue(future.cancelled())


if __name__ == "__main__":
    unittest.main()
