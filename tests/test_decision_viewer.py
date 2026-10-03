import os
import random
import unittest
from dataclasses import FrozenInstanceError
from unittest.mock import Mock, patch

os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"

import pygame

from jev_bird.decisions import ActionDecision, CompletedDecision, DecisionView, GameAction
from jev_bird.controller import GameController
from jev_bird.game import GRAVITY, PIPE_WIDTH, SCREEN_HEIGHT, GameState, PipePair
from jev_bird.decision_viewer import (
    CONFIDENCE_BAR_BOUNDS,
    GAP,
    PANEL_WIDTH,
    PLAYFIELD,
    PREDICTED,
    WARNING,
    DecisionViewer,
)
from tests.fakes import FakeJev


class DecisionSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.state = GameState(random.Random(7))
        self.state.bird.y = 250.75
        self.state.bird.velocity_y = -350.0
        self.state.pipes = [
            PipePair(x=20.0, gap_top=100, scored=True),
            PipePair(x=200.5, gap_top=180),
        ]

    def test_snapshot_matches_payload_and_preserves_fractional_geometry(self):
        snapshot = self.state.capture_decision_snapshot(0.25)

        self.assertEqual(snapshot.to_state_dict(), self.state.to_state_dict(0.25))
        self.assertEqual(snapshot.bird.y, 250.75)
        self.assertAlmostEqual(
            snapshot.bird.predicted_y, 250.75 - 350 * 0.25 + 0.5 * GRAVITY * 0.25**2
        )
        self.assertEqual(snapshot.pipe.x, 200.5)
        self.assertEqual(snapshot.pipe.gap_top, 180)
        self.assertEqual(snapshot.pipe.gap_bottom, 350)
        self.assertEqual(snapshot.prediction_seconds, 0.25)

    def test_snapshot_is_immutable_and_independent_of_live_world_and_payload(self):
        snapshot = self.state.capture_decision_snapshot(0.25)
        payload = snapshot.to_state_dict()
        self.state.bird.y = 500
        self.state.pipes[1].x = 100
        self.state.pipes[1].gap_top = 300
        payload["bird"]["position"] = None
        payload["next_pipe"]["distance_x"] = "0"

        self.assertEqual(snapshot.bird.y, 250.75)
        self.assertEqual(snapshot.pipe.x, 200.5)
        self.assertEqual(snapshot.pipe.gap_top, 180)
        self.assertEqual(
            snapshot.to_state_dict()["bird"]["position"],
            "inside the gap, upper half",
        )
        self.assertEqual(snapshot.to_state_dict()["next_pipe"]["distance_x"], "86")
        with self.assertRaises(FrozenInstanceError):
            snapshot.bird.y = 0

    def test_snapshot_keeps_out_of_bounds_prediction_and_no_pipe_nulls(self):
        self.state.bird.y = 570
        self.state.bird.velocity_y = 0
        self.state.pipes = []

        snapshot = self.state.capture_decision_snapshot(0.25)

        self.assertEqual(snapshot.bird.predicted_y, 601.25)
        self.assertIsNone(snapshot.pipe)
        self.assertIsNone(snapshot.to_state_dict()["bird"]["position"])
        self.assertEqual(snapshot.to_state_dict()["bird"]["motion"], "falling")
        self.assertIsNone(snapshot.to_state_dict()["next_pipe"])

    def test_all_cleared_pipes_are_treated_as_no_next_pipe(self):
        for pipe in self.state.pipes:
            pipe.x = self.state.bird.front_edge_x() - PIPE_WIDTH
        snapshot = self.state.capture_decision_snapshot(0.25)
        self.assertIsNone(snapshot.pipe)
        self.assertIsNone(snapshot.to_state_dict()["bird"]["position"])
        self.assertIsNone(snapshot.to_state_dict()["next_pipe"])


class DecisionLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.state = GameState(random.Random(7))
        self.jev = FakeJev()
        self.now = Mock(return_value=10.0)
        self.controller = GameController(self.state, self.jev, now=self.now)
        logger = patch("jev_bird.controller.LOGGER")
        logger.start()
        self.addCleanup(logger.stop)

    def request(self):
        self.controller.update(0, request_due=True)
        return self.jev.futures[-1]

    def complete(self, action=GameAction.FALL):
        snapshot = self.state.capture_decision_snapshot(self.controller.average_response_seconds)
        started_at = self.now.return_value
        prediction_seconds = self.controller.average_response_seconds
        future = self.request()
        self.now.return_value += 0.1
        future.set_result(action)
        response_seconds = self.now.return_value - started_at
        self.now.return_value = started_at + prediction_seconds
        self.controller.update(0)
        return CompletedDecision(snapshot, action, response_seconds)

    def crash(self):
        self.state.bird.y = SCREEN_HEIGHT - self.state.bird.height
        self.controller.update(0)

    def test_shows_submission_snapshot_only_after_failure(self):
        self.assertIsNone(self.controller.decision_view.completed)
        self.assertFalse(self.controller.decision_view.failure_recorded)
        original_y = self.state.bird.y
        original_pipe_x = self.state.pipes[0].x
        future = self.request()
        self.controller.update(0.05)
        self.now.return_value = 10.3
        future.set_result(GameAction.JUMP)
        self.controller.update(0)
        self.assertIsNone(self.controller.decision_view.completed)
        self.crash()

        decision = self.controller.decision_view.completed
        self.assertEqual(decision.action, GameAction.JUMP)
        self.assertEqual(decision.snapshot.bird.y, original_y)
        self.assertEqual(decision.snapshot.pipe.x, original_pipe_x)
        self.assertEqual(decision.snapshot.to_state_dict(), self.jev.requests[0])
        self.assertEqual(decision.snapshot.prediction_seconds, 0.25)
        self.assertAlmostEqual(decision.response_seconds, 0.3)
        self.assertTrue(self.controller.decision_view.failure_recorded)

    def test_preserves_confidence_of_last_action_at_failure(self):
        future = self.request()
        self.now.return_value = 10.3
        future.set_result(ActionDecision(GameAction.JUMP, 0.823))
        self.controller.update(0)

        self.crash()

        decision = self.controller.decision_view.completed
        self.assertEqual(decision.action, GameAction.JUMP)
        self.assertEqual(decision.confidence, 0.823)

    def test_only_last_applied_action_is_published_at_failure(self):
        first = self.request()
        self.now.return_value = 10.125
        first.set_result(GameAction.FALL)
        self.controller.update(0)

        self.now.return_value = 10.25
        self.controller.update(0, request_due=True)

        self.assertIsNone(self.controller.decision_view.completed)
        self.now.return_value = 10.3
        self.jev.futures[1].set_result(GameAction.JUMP)
        self.now.return_value = 10.375
        self.controller.update(0)
        self.assertIsNone(self.controller.decision_view.completed)
        self.crash()
        second_decision = self.controller.decision_view.completed
        self.assertEqual(second_decision.action, GameAction.JUMP)
        self.assertEqual(second_decision.snapshot.prediction_seconds, 0.125)
        self.assertEqual(second_decision.snapshot.to_state_dict(), self.jev.requests[1])

    def test_failed_and_cancelled_requests_do_not_replace_last_applied_action(self):
        completed = self.complete()
        for cancel in (False, True):
            with self.subTest(cancel=cancel):
                future = self.request()
                self.assertIsNone(self.controller.decision_view.completed)
                if cancel:
                    future.cancel()
                else:
                    future.set_exception(RuntimeError("offline"))
                self.controller.update(0)
                self.assertIsNone(self.controller.decision_view.completed)
        self.crash()
        self.assertEqual(self.controller.decision_view.completed, completed)

    def test_submission_error_does_not_replace_last_applied_action_and_can_retry(self):
        completed = self.complete()
        with patch.object(self.jev, "get_action", side_effect=RuntimeError("offline")):
            self.controller.update(0, request_due=True)
        self.assertIsNone(self.controller.decision_view.completed)
        self.crash()
        self.assertEqual(self.controller.decision_view.completed, completed)
        self.complete(GameAction.JUMP)
        self.assertEqual(self.controller.decision_view.completed, completed)
        self.crash()
        self.assertEqual(self.controller.decision_view.completed.action, GameAction.JUMP)

    def test_failure_view_persists_through_restart_and_ignores_late_response(self):
        completed = self.complete()
        stale = self.request()
        stale.set_running_or_notify_cancel()
        self.crash()
        self.assertEqual(self.controller.decision_view.completed, completed)
        failure_view = self.controller.decision_view
        self.controller.update(0)
        stale.set_result(GameAction.JUMP)
        self.controller.update(0)
        self.assertIs(self.controller.decision_view, failure_view)
        self.now.return_value += self.controller.average_response_seconds
        self.jev.futures[-1].set_result(GameAction.FALL)
        self.controller.update(0)
        self.assertIs(self.controller.decision_view, failure_view)
        self.crash()
        self.assertEqual(self.controller.decision_view.completed.action, GameAction.FALL)

    def test_restart_discards_response_already_completed(self):
        completed = self.complete()
        self.request().set_result(GameAction.JUMP)
        self.crash()
        self.assertEqual(self.controller.decision_view.completed, completed)

    def test_failure_without_applied_action_does_not_reuse_previous_run_action(self):
        self.complete()
        self.crash()
        self.assertIsNotNone(self.controller.decision_view.completed)
        self.request()
        self.crash()
        self.assertTrue(self.controller.decision_view.failure_recorded)
        self.assertIsNone(self.controller.decision_view.completed)

    def test_first_failure_with_only_pending_action_has_no_completed_decision(self):
        future = self.request()
        self.crash()
        self.assertTrue(future.cancelled())
        self.assertTrue(self.controller.decision_view.failure_recorded)
        self.assertIsNone(self.controller.decision_view.completed)


class DecisionRenderingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()

    @classmethod
    def tearDownClass(cls):
        pygame.quit()

    def setUp(self):
        self.surface = pygame.Surface((PANEL_WIDTH, SCREEN_HEIGHT))
        self.viewer = DecisionViewer(400, SCREEN_HEIGHT)
        self.state = GameState(random.Random(7))
        self.state.bird.y = 250.75
        self.state.bird.velocity_y = -100
        self.state.pipes = [PipePair(x=200, gap_top=180)]

    def render(self, view):
        with patch.object(self.viewer, "_text", wraps=self.viewer._text) as text:
            self.viewer.draw(self.surface, view)
        return [call.args[1] for call in text.call_args_list]

    def decision(self, action):
        return CompletedDecision(self.state.capture_decision_snapshot(0.25), action, 0.3)

    def color_count(self, color, rect):
        return sum(
            self.surface.get_at((x, y))[:3] == color
            for x in range(rect.left, rect.right)
            for y in range(rect.top, rect.bottom)
        )

    def test_waiting_and_failure_states_have_clear_labels(self):
        self.assertIn("Waiting for first failure...", self.render(DecisionView()))
        labels = self.render(DecisionView(failure_recorded=True))
        self.assertIn("No JEV action was applied before this failure.", labels)
        decision = self.decision(GameAction.JUMP)
        labels = self.render(DecisionView(completed=decision, failure_recorded=True))
        self.assertIn("Jump", labels)
        self.assertIn("Last action before failure / frozen state", labels)

    def test_shows_decision_confidence_as_percentage_and_bar_meter(self):
        snapshot = self.state.capture_decision_snapshot(0.25)
        decision = CompletedDecision(snapshot, GameAction.JUMP, 0.3, confidence=0.823)

        labels = self.render(DecisionView(completed=decision, failure_recorded=True))

        self.assertIn("Confidence: 82.3%", labels)
        x, y, width, height = CONFIDENCE_BAR_BOUNDS
        inner_width = width - 4
        filled_width = round(inner_width * 0.823)
        meter_y = y + height // 2
        self.assertEqual(self.surface.get_at((x + 2, meter_y))[:3], PREDICTED)
        self.assertEqual(
            self.surface.get_at((x + 2 + filled_width - 1, meter_y))[:3],
            PREDICTED,
        )
        self.assertEqual(
            self.surface.get_at((x + 2 + filled_width, meter_y))[:3],
            PLAYFIELD,
        )

    def test_unavailable_confidence_draws_an_empty_bar_meter(self):
        labels = self.render(
            DecisionView(completed=self.decision(GameAction.JUMP), failure_recorded=True)
        )

        self.assertIn("Confidence: unavailable", labels)
        x, y, width, height = CONFIDENCE_BAR_BOUNDS
        self.assertEqual(
            self.color_count(PLAYFIELD, pygame.Rect(x + 2, y + 2, width - 4, height - 4)),
            (width - 4) * (height - 4),
        )

    def test_actions_change_arrow_direction_and_drawing_preserves_state(self):
        snapshot = self.state.capture_decision_snapshot(0.25)
        before_bird = vars(self.state.bird).copy()
        before_pipe = vars(self.state.pipes[0]).copy()
        jump_view = DecisionView(
            completed=self.decision(GameAction.JUMP), failure_recorded=True
        )
        self.assertIn("Jump", self.render(jump_view))
        # Only the arrow occupies this region to the right of the predicted bird.
        arrow_region = pygame.Rect(100, 270, 28, 55)
        jump_pixels = pygame.image.tobytes(self.surface.subsurface(arrow_region), "RGB")
        self.assertGreater(self.color_count(PREDICTED, arrow_region), 0)
        fall_view = DecisionView(
            completed=self.decision(GameAction.FALL), failure_recorded=True
        )
        self.assertIn("Fall", self.render(fall_view))
        self.assertNotIn("Fall / no flap", self.render(fall_view))
        fall_pixels = pygame.image.tobytes(self.surface.subsurface(arrow_region), "RGB")
        self.assertNotEqual(jump_pixels, fall_pixels)
        self.assertEqual(self.state.capture_decision_snapshot(0.25), snapshot)
        self.assertEqual(vars(self.state.bird), before_bird)
        self.assertEqual(vars(self.state.pipes[0]), before_pipe)

    def test_out_of_bounds_prediction_and_no_pipe_payload_are_visible(self):
        self.state.pipes.clear()
        for y, velocity, expected_motion in (
            (570, 0, "falling"),
            (10, -350, "rising"),
        ):
            with self.subTest(y=y):
                self.state.bird.y = y
                self.state.bird.velocity_y = velocity
                decision = self.decision(GameAction.FALL)
                labels = self.render(DecisionView(completed=decision, failure_recorded=True))
                self.assertIn("bird.position", labels)
                self.assertIn("bird.motion", labels)
                self.assertIn(expected_motion, labels)
                self.assertIn("next_pipe", labels)
                self.assertGreaterEqual(labels.count("null"), 2)
                self.assertIn(f"Predicted y: {decision.snapshot.bird.predicted_y:.2f}", labels)
                self.assertGreater(self.color_count(WARNING, pygame.Rect(16, 128, 280, 410)), 0)

    def test_renders_every_nested_payload_field(self):
        labels = self.render(
            DecisionView(completed=self.decision(GameAction.JUMP), failure_recorded=True)
        )

        for label in (
            "bird.position",
            "bird.motion",
            "next_pipe.distance_x",
            "next_pipe.gap_top_y",
            "next_pipe.gap_bottom_y",
            "bird_jump_height",
            "y_axis",
            "length_unit",
        ):
            self.assertIn(label, labels)
        self.assertIn("Roughly third of pipe gap", labels)
        self.assertIn("pixel", labels)

    def test_pipe_beyond_gameplay_screen_is_still_highlighted(self):
        self.state.pipes[0].x = 450
        self.render(DecisionView(completed=self.decision(GameAction.JUMP), failure_recorded=True))
        self.assertGreater(self.color_count(GAP, pygame.Rect(16, 128, 280, 410)), 0)


if __name__ == "__main__":
    unittest.main()
