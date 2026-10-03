"""The simulator and controller must work without the API client or viewers."""

from pathlib import Path
import subprocess
import sys
import unittest


class OfflineSimulationTests(unittest.TestCase):
    def test_simulation_can_apply_actions_and_review_failure_without_sdk(self):
        script = """
import sys
sys.modules['typesafe_sdk'] = None
sys.modules['decision_viewer'] = None
from concurrent.futures import Future
from jev_bird.controller import GameController
from jev_bird.decisions import GameAction
from jev_bird.game import GameState, SCREEN_HEIGHT

class LocalActions:
    def get_action(self, state):
        future = Future()
        future.set_result(GameAction.JUMP)
        return future

state = GameState()
now = [10.0]
controller = GameController(state, LocalActions(), now=lambda: now[0])
controller.update(0.0, request_due=True)
now[0] = 10.25
controller.update(0.0)
assert state.bird.velocity_y < 0
assert not controller.decision_view.failure_recorded
state.bird.y = SCREEN_HEIGHT
controller.update(0.0)
assert controller.decision_view.completed.action == GameAction.JUMP
"""
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
