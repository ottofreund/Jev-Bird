import random
import unittest

from jev_bird.game import (
    BIRD_START_Y,
    BIRD_X,
    FLAP_VELOCITY,
    GRAVITY,
    JUMP_HEIGHT,
    PIPE_GAP,
    PIPE_MARGIN,
    PIPE_SPEED,
    PIPE_SPAWN_INTERVAL,
    PIPE_START_X,
    PIPE_WIDTH,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    Bird,
    GameState,
    PipePair,
)


class JumpHeightTests(unittest.TestCase):
    def test_finds_height_gained_from_jump_velocity_and_gravity(self):
        self.assertAlmostEqual(JUMP_HEIGHT, 61.25)


class BirdTests(unittest.TestCase):
    def test_flap_sets_upward_velocity(self):
        bird = Bird()

        bird.flap()

        self.assertEqual(bird.velocity_y, FLAP_VELOCITY)
        self.assertLess(bird.velocity_y, 0)

    def test_update_applies_gravity_then_moves_bird(self):
        bird = Bird(y=250.0, velocity_y=-100.0)

        bird.update(0.1)

        expected_velocity = -100.0 + GRAVITY * 0.1
        self.assertAlmostEqual(bird.velocity_y, expected_velocity)
        self.assertAlmostEqual(bird.y, 250.0 + expected_velocity * 0.1)


class PipeTests(unittest.TestCase):
    def test_gets_bottom_pipes_top_edge_y_coordinate(self):
        pipe = PipePair(x=200.0, gap_top=180)

        self.assertEqual(pipe.bottom_pipe_top_edge_y(), 180 + PIPE_GAP)

    def test_gets_top_pipes_bottom_edge_y_coordinate(self):
        pipe = PipePair(x=200.0, gap_top=180)

        self.assertEqual(pipe.top_pipe_bottom_edge_y(), 180)

    def test_pipe_moves_left_using_elapsed_time(self):
        pipe = PipePair(x=200.0, gap_top=180)

        pipe.update(0.5)

        self.assertAlmostEqual(pipe.x, 200.0 - PIPE_SPEED * 0.5)

    def test_random_pipe_gap_stays_inside_playfield(self):
        state = GameState(random.Random(1234))

        pipes = [state.create_pipe(500.0) for _ in range(100)]

        for pipe in pipes:
            self.assertGreaterEqual(pipe.gap_top, PIPE_MARGIN)
            self.assertLessEqual(
                pipe.gap_top, SCREEN_HEIGHT - PIPE_MARGIN - PIPE_GAP
            )


class GameStateTests(unittest.TestCase):
    def setUp(self):
        self.state = GameState(random.Random(7))

    def test_zero_delay_state_has_nested_semantic_payload(self):
        self.state.bird.y = 250.0
        self.state.bird.velocity_y = -350.0
        self.state.pipes = [PipePair(x=200.0, gap_top=180)]
        expected = {
            "bird": {
                "position": "inside the gap, upper half",
                "motion": "rising",
            },
            "next_pipe": {
                "distance_x": "86",
                "gap_top_y": "180",
                "gap_bottom_y": "350",
            },
            "bird_jump_height": "Roughly third of pipe gap",
            "y_axis": "y grows downward; smaller y is higher up",
            "length_unit": "pixel",
        }

        self.assertEqual(self.state.to_state_dict(), expected)
        self.assertEqual(self.state.to_state_dict(0.0), expected)

    def test_position_uses_predicted_bird_center_and_inclusive_gap_edges(self):
        self.state.pipes = [PipePair(x=200.0, gap_top=180)]
        for center_y, expected in (
            (179.99, "above the gap"),
            (180, "inside the gap, upper half"),
            (265, "inside the gap, upper half"),
            (265.01, "inside the gap, lower half"),
            (350, "inside the gap, lower half"),
            (350.01, "below the gap"),
        ):
            with self.subTest(center_y=center_y):
                self.state.bird.y = center_y - self.state.bird.height / 2
                self.assertEqual(
                    self.state.to_state_dict()["bird"]["position"], expected
                )

    def test_motion_uses_latency_predicted_velocity_at_all_thresholds(self):
        self.state.pipes = [PipePair(x=200.0, gap_top=180)]
        delay = 0.25
        for predicted_velocity, expected in (
            (-50.01, "rising"),
            (-50, "level"),
            (-49.99, "level"),
            (50, "level"),
            (50.01, "falling"),
            (349.99, "falling"),
            (350, "falling fast"),
            (350.01, "falling fast"),
        ):
            with self.subTest(predicted_velocity=predicted_velocity):
                self.state.bird.velocity_y = predicted_velocity - GRAVITY * delay
                self.assertEqual(
                    self.state.to_state_dict(delay)["bird"]["motion"], expected
                )

    def test_pipe_values_are_signed_integer_strings_truncated_toward_zero(self):
        self.state.bird.x = 80.6
        self.state.pipes = [PipePair(x=110.1, gap_top=180)]

        payload = self.state.to_state_dict()

        self.assertEqual(payload["next_pipe"]["distance_x"], "-4")
        self.assertEqual(payload["next_pipe"]["gap_top_y"], "180")
        self.assertEqual(payload["next_pipe"]["gap_bottom_y"], "350")

    def test_prediction_does_not_mutate_world_or_clamp_unsafe_distances(self):
        self.state.bird.y = 570.0
        self.state.pipes.clear()
        bird_snapshot = vars(self.state.bird).copy()
        state_snapshot = (self.state.spawn_elapsed, self.state.score, self.state.game_over)

        predicted = self.state.to_state_dict(0.25)

        self.assertIsNone(predicted["bird"]["position"])
        self.assertEqual(predicted["bird"]["motion"], "falling")
        self.assertIsNone(predicted["next_pipe"])
        self.assertEqual(vars(self.state.bird), bird_snapshot)
        self.assertEqual(self.state.pipes, [])
        self.assertEqual(
            (self.state.spawn_elapsed, self.state.score, self.state.game_over),
            state_snapshot,
        )

    def test_next_pipe_switches_when_birds_front_reaches_current_pipe_end(self):
        current_pipe = PipePair(
            x=BIRD_X + self.state.bird.width - PIPE_WIDTH + 0.01,
            gap_top=100,
        )
        next_pipe = PipePair(x=200.0, gap_top=240)
        self.state.pipes = [current_pipe, next_pipe]

        before_end = self.state.capture_decision_snapshot(0.0)

        self.assertIsNotNone(before_end.pipe)
        self.assertEqual(before_end.pipe.x, current_pipe.x)

        current_pipe.x = BIRD_X + self.state.bird.width - PIPE_WIDTH
        snapshot = self.state.capture_decision_snapshot(0.0)

        self.assertIsNotNone(snapshot.pipe)
        self.assertEqual(snapshot.pipe.x, next_pipe.x)
        self.assertFalse(current_pipe.scored)
        self.assertEqual(self.state.score, 0)

    def test_spawn_timer_retains_overflow(self):
        self.state.pipes.clear()
        self.state.spawn_elapsed = PIPE_SPAWN_INTERVAL - 0.01

        self.state.update(0.005)
        self.assertEqual(self.state.pipes, [])

        self.state.update(0.006)
        self.assertEqual(len(self.state.pipes), 1)
        self.assertAlmostEqual(self.state.spawn_elapsed, 0.001)

    def test_offscreen_pipe_is_removed(self):
        self.state.pipes = [
            PipePair(x=-PIPE_WIDTH - 1.0, gap_top=200),
            PipePair(x=-PIPE_WIDTH + 1.0, gap_top=200),
        ]

        self.state.update(0.0)

        self.assertEqual(len(self.state.pipes), 1)
        self.assertAlmostEqual(self.state.pipes[0].x, -PIPE_WIDTH + 1.0)

    def test_pipe_scores_only_once_after_fully_passing_bird(self):
        pipe = PipePair(x=BIRD_X - PIPE_WIDTH - 1.0, gap_top=200)
        self.state.pipes = [pipe]

        self.state.update(0.0)
        self.assertEqual(self.state.score, 1)
        self.assertTrue(pipe.scored)

        self.state.update(0.0)

        self.assertEqual(self.state.score, 1)

    def test_pipe_does_not_score_while_level_with_bird(self):
        pipe = PipePair(x=BIRD_X - PIPE_WIDTH, gap_top=200)
        self.state.pipes = [pipe]

        self.state.update(0.0)

        self.assertEqual(self.state.score, 0)

    def test_detects_top_pipe_collision(self):
        self.state.pipes = [PipePair(x=BIRD_X, gap_top=400)]

        self.assertTrue(self.state.has_collision())

    def test_detects_bottom_pipe_collision(self):
        self.state.pipes = [PipePair(x=BIRD_X, gap_top=50)]

        self.assertTrue(self.state.has_collision())

    def test_bird_fully_inside_gap_is_safe(self):
        gap_top = int(BIRD_START_Y - PIPE_GAP / 2)
        self.state.pipes = [PipePair(x=BIRD_X, gap_top=gap_top)]

        self.assertFalse(self.state.has_collision())

    def test_pipe_touching_birds_horizontal_edge_is_safe(self):
        self.state.pipes = [
            PipePair(x=BIRD_X + self.state.bird.width, gap_top=400)
        ]

        self.assertFalse(self.state.has_collision())

    def test_bird_center_in_gap_still_collides_when_body_overlaps_pipe(self):
        bird_center_y = self.state.bird.y + self.state.bird.height / 2
        self.state.pipes = [PipePair(x=BIRD_X, gap_top=int(bird_center_y - 5))]

        self.assertTrue(self.state.has_collision())

    def test_detects_ceiling_and_floor_boundaries(self):
        self.state.bird.y = 0.0
        self.assertTrue(self.state.has_collision())

        self.state.bird.y = SCREEN_HEIGHT - self.state.bird.height
        self.assertTrue(self.state.has_collision())

    def test_game_over_freezes_world(self):
        self.state.game_over = True
        bird_snapshot = (self.state.bird.y, self.state.bird.velocity_y)
        pipe_snapshot = [(pipe.x, pipe.gap_top) for pipe in self.state.pipes]
        timer_snapshot = self.state.spawn_elapsed

        self.state.update(1.0)

        self.assertEqual(
            (self.state.bird.y, self.state.bird.velocity_y), bird_snapshot
        )
        self.assertEqual(
            [(pipe.x, pipe.gap_top) for pipe in self.state.pipes], pipe_snapshot
        )
        self.assertEqual(self.state.spawn_elapsed, timer_snapshot)
        self.assertEqual(self.state.score, 0)

    def test_update_enters_game_over_on_collision(self):
        self.state.pipes = [PipePair(x=BIRD_X, gap_top=400)]

        self.state.update(0.0)

        self.assertTrue(self.state.game_over)

    def test_flap_is_ignored_after_game_over(self):
        self.state.flap()
        self.assertEqual(self.state.bird.velocity_y, FLAP_VELOCITY)

        self.state.game_over = True
        self.state.bird.velocity_y = 25.0
        self.state.flap()
        self.assertEqual(self.state.bird.velocity_y, 25.0)

    def test_reset_restores_a_new_run(self):
        self.state.score = 9
        self.state.game_over = True
        self.state.spawn_elapsed = 1.2
        self.state.bird.y = 42.0
        self.state.bird.velocity_y = 123.0
        old_pipe = self.state.pipes[0]
        old_pipe.x = 10.0
        old_pipe.scored = True
        self.state.pipes.append(PipePair(x=20.0, gap_top=100, scored=True))

        self.state.reset()

        self.assertEqual(self.state.score, 0)
        self.assertFalse(self.state.game_over)
        self.assertEqual(self.state.spawn_elapsed, 0.0)
        self.assertEqual(self.state.bird.x, BIRD_X)
        self.assertEqual(self.state.bird.y, BIRD_START_Y)
        self.assertEqual(self.state.bird.velocity_y, 0.0)
        self.assertEqual(len(self.state.pipes), 1)
        self.assertIsNot(self.state.pipes[0], old_pipe)
        self.assertEqual(self.state.pipes[0].x, PIPE_START_X)
        self.assertFalse(self.state.pipes[0].scored)


if __name__ == "__main__":
    unittest.main()
