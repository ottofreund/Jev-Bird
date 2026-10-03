import random
import unittest
from unittest.mock import Mock, call, patch

from jev_bird.controller import GameController
from jev_bird.decisions import GameAction
from jev_bird.game import BIRD_START_Y, FLAP_VELOCITY, SCREEN_HEIGHT, GameState
from tests.fakes import FakeJev


class GameControllerTests(unittest.TestCase):
    def setUp(self):
        self.state = GameState(random.Random(7))
        self.jev = FakeJev()
        self.now = Mock(return_value=10.0)
        self.controller = GameController(self.state, self.jev, now=self.now)
        logger = patch("jev_bird.controller.LOGGER")
        self.logger = logger.start()
        self.addCleanup(logger.stop)

    def request(self):
        self.controller.update(0.0, request_due=True)
        return self.jev.futures[-1]

    def crash(self):
        self.state.bird.y = SCREEN_HEIGHT - self.state.bird.height
        self.controller.update(0.0)

    def test_first_request_uses_250_ms_estimate(self):
        self.controller.update(0.0)
        self.assertEqual(self.jev.requests, [])
        self.request()

        self.assertEqual(len(self.jev.requests), 1)
        self.assertEqual(self.jev.requests[0], self.state.to_state_dict(0.25))
        self.assertEqual(self.controller.average_response_seconds, 0.25)

    def test_buffer_accepts_twelve_requests_and_rejects_a_thirteenth(self):
        for _ in range(13):
            self.controller.update(0.0, request_due=True)

        self.assertEqual(len(self.jev.requests), 12)

        self.jev.futures[0].set_exception(RuntimeError("request failed"))
        self.controller.update(0.0, request_due=True)

        self.assertEqual(len(self.jev.requests), 13)
        self.assertEqual(self.controller.average_response_seconds, 0.25)

    def test_failures_and_cancellations_free_capacity_behind_pending_work(self):
        for _ in range(12):
            self.controller.update(0.0, request_due=True)
        self.jev.futures[5].set_exception(RuntimeError("request failed"))
        self.jev.futures[8].cancel()

        self.controller.update(0.0, request_due=True)
        self.controller.update(0.0, request_due=True)

        self.assertEqual(len(self.jev.requests), 14)
        self.assertEqual(self.controller.average_response_seconds, 0.25)

    def test_out_of_order_completions_are_applied_in_submission_order(self):
        first = self.request()
        second = self.request()
        third = self.request()
        self.now.return_value = 10.1
        second.set_result(GameAction.FALL)
        self.now.return_value = 10.15
        third.set_result(GameAction.JUMP)
        self.now.return_value = 10.3

        self.controller.update(0.0)

        self.assertEqual(self.state.bird.velocity_y, 0.0)
        self.assertEqual(self.controller.average_response_seconds, 0.25)

        first.set_result(GameAction.FALL)
        self.controller.update(0.0)

        action_logs = [
            entry
            for entry in self.logger.info.call_args_list
            if entry.args and entry.args[0] == "JEV action: %s"
        ]
        self.assertEqual(
            action_logs,
            [
                call("JEV action: %s", "FALL"),
                call("JEV action: %s", "FALL"),
                call("JEV action: %s", "JUMP"),
            ],
        )
        self.assertEqual(self.state.bird.velocity_y, FLAP_VELOCITY)
        self.assertAlmostEqual(
            self.controller.average_response_seconds, (0.3 + 0.1 + 0.15) / 3
        )

    def test_each_early_response_waits_for_its_own_predicted_moment(self):
        first = self.request()
        self.now.return_value = 10.05
        second = self.request()
        self.now.return_value = 10.1
        first.set_result(GameAction.FALL)
        second.set_result(GameAction.FALL)

        self.now.return_value = 10.25
        self.controller.update(0.0)
        self.assertEqual(
            self.logger.info.call_args_list.count(call("JEV action: %s", "FALL")),
            1,
        )

        self.now.return_value = 10.299
        self.controller.update(0.0)
        self.assertEqual(
            self.logger.info.call_args_list.count(call("JEV action: %s", "FALL")),
            1,
        )

        self.now.return_value = 10.3
        self.controller.update(0.0)
        self.assertEqual(
            self.logger.info.call_args_list.count(call("JEV action: %s", "FALL")),
            2,
        )

    def test_jump_discards_all_other_work_and_ignores_late_results(self):
        jump = self.request()
        pending = self.request()
        completed_waiting = self.request()
        uncancellable = self.request()
        uncancellable.set_running_or_notify_cancel()
        self.now.return_value = 10.1
        jump.set_result(GameAction.JUMP)
        completed_waiting.set_result(GameAction.FALL)

        self.now.return_value = 10.25
        self.controller.update(0.0)

        self.assertTrue(pending.cancelled())
        self.assertFalse(completed_waiting.cancelled())
        self.assertFalse(uncancellable.cancelled())
        self.assertEqual(len(self.jev.requests), 5)
        self.assertAlmostEqual(self.controller.average_response_seconds, 0.1)
        self.assertEqual(self.state.bird.velocity_y, FLAP_VELOCITY)

        uncancellable.set_result(GameAction.JUMP)
        self.now.return_value = 11.0
        self.controller.update(0.0)

        self.assertAlmostEqual(self.controller.average_response_seconds, 0.1)
        self.assertEqual(self.state.bird.velocity_y, FLAP_VELOCITY)
        action_logs = [
            entry
            for entry in self.logger.info.call_args_list
            if entry.args and entry.args[0] == "JEV action: %s"
        ]
        self.assertEqual(action_logs, [call("JEV action: %s", "JUMP")])

    def test_immediate_post_jump_request_uses_flapped_state_and_new_average(self):
        jump = self.request()
        self.now.return_value = 10.1
        jump.set_result(GameAction.JUMP)
        self.now.return_value = 10.25

        self.controller.update(0.0)

        self.assertEqual(len(self.jev.requests), 2)
        self.assertAlmostEqual(self.controller.average_response_seconds, 0.1)
        self.assertEqual(self.state.bird.velocity_y, FLAP_VELOCITY)
        self.assertEqual(self.jev.requests[-1], self.state.to_state_dict(0.1))

    def test_early_response_waits_for_predicted_moment_and_records_arrival(self):
        future = self.request()
        self.now.return_value = 10.1
        future.set_result(GameAction.JUMP)

        self.controller.update(0.0, request_due=True)
        self.assertEqual(self.state.bird.velocity_y, 0.0)
        self.assertEqual(len(self.jev.requests), 2)
        self.assertEqual(self.controller.average_response_seconds, 0.25)

        self.now.return_value = 10.249
        self.controller.update(0.0)
        self.assertEqual(self.state.bird.velocity_y, 0.0)

        self.now.return_value = 10.25
        self.controller.update(0.0)
        self.assertEqual(self.state.bird.velocity_y, FLAP_VELOCITY)
        self.assertAlmostEqual(self.controller.average_response_seconds, 0.1)
        latency_log = next(
            entry
            for entry in self.logger.info.call_args_list
            if entry.args
            and entry.args[0]
            == "JEV action latency: %.3f seconds (average: %.3f seconds)"
        )
        self.assertAlmostEqual(latency_log.args[1], 0.1)
        self.assertAlmostEqual(latency_log.args[2], 0.1)

    def test_averages_successful_submission_to_arrival_times(self):
        first = self.request()
        self.now.return_value = 10.125
        first.set_result(GameAction.FALL)
        self.controller.update(0.0)

        self.assertEqual(self.controller.average_response_seconds, 0.25)
        self.now.return_value = 10.25
        self.controller.update(0.0, request_due=True)

        self.assertAlmostEqual(self.controller.average_response_seconds, 0.125)
        self.controller.update(0.0, request_due=True)
        self.assertEqual(self.jev.requests[1], self.state.to_state_dict(0.125))
        self.logger.info.assert_any_call(
            "JEV action latency: %.3f seconds (average: %.3f seconds)",
            0.125,
            0.125,
        )

        self.now.return_value = 10.625
        self.jev.futures[1].set_result(GameAction.JUMP)
        self.controller.update(0.0)

        self.assertAlmostEqual(self.controller.average_response_seconds, 0.25)
        self.assertEqual(self.state.bird.velocity_y, FLAP_VELOCITY)
        self.assertEqual(self.jev.requests[3], self.state.to_state_dict(0.25))

    def test_errors_and_cancelled_requests_do_not_change_average(self):
        for cancel in (False, True):
            with self.subTest(cancel=cancel):
                future = self.request()
                if cancel:
                    future.cancel()
                else:
                    future.set_exception(RuntimeError("request failed"))
                self.now.return_value += 0.5
                self.controller.update(0.0)
                self.assertEqual(self.controller.average_response_seconds, 0.25)

        future = self.request()
        self.now.return_value += 0.1
        future.set_result(GameAction.FALL)
        self.controller.update(0.0)
        self.now.return_value += 0.15
        self.controller.update(0.0)
        self.assertAlmostEqual(self.controller.average_response_seconds, 0.1)

    def test_early_error_clears_immediately_without_changing_average(self):
        failed = self.request()
        self.now.return_value = 10.05
        failed.set_exception(RuntimeError("request failed"))

        self.controller.update(0.0, request_due=True)

        self.assertEqual(len(self.jev.requests), 2)
        self.assertEqual(self.controller.average_response_seconds, 0.25)

    def test_early_cancellation_clears_immediately_without_changing_average(self):
        cancelled = self.request()
        self.now.return_value = 10.05
        cancelled.cancel()

        self.controller.update(0.0, request_due=True)

        self.assertEqual(len(self.jev.requests), 2)
        self.assertEqual(self.controller.average_response_seconds, 0.25)

    def test_submission_error_retries_with_fresh_state_on_next_due_frame(self):
        with patch.object(self.jev, "get_action", side_effect=RuntimeError("offline")):
            self.controller.update(0.0, request_due=True)
        self.assertEqual(self.controller.average_response_seconds, 0.25)
        self.controller.update(0.05)
        self.assertEqual(self.jev.requests, [])
        expected = self.state.to_state_dict(0.25)
        future = self.request()
        self.now.return_value = 10.1
        future.set_result(GameAction.JUMP)
        self.controller.update(0.0)
        self.now.return_value = 10.25
        self.controller.update(0.0)
        self.assertEqual(self.jev.requests[0], expected)
        self.assertEqual(self.state.bird.velocity_y, FLAP_VELOCITY)
        self.assertAlmostEqual(self.controller.average_response_seconds, 0.1)

    def test_restart_cancels_pending_request_and_requests_next_frame(self):
        first = self.request()
        self.now.return_value = 10.5
        first.set_result(GameAction.FALL)
        self.controller.update(0.0)
        pending = self.request()
        self.state.score = 9

        self.crash()

        self.assertTrue(pending.cancelled())
        self.assertFalse(self.state.game_over)
        self.assertEqual(self.state.score, 0)
        self.assertEqual(self.state.bird.y, BIRD_START_Y)
        self.assertEqual(self.state.bird.velocity_y, 0.0)
        self.assertAlmostEqual(self.controller.average_response_seconds, 0.5)
        self.assertEqual(len(self.jev.requests), 2)

        self.controller.update(0.0)
        self.assertEqual(len(self.jev.requests), 3)
        self.assertEqual(self.jev.requests[-1], self.state.to_state_dict(0.5))

    def test_restart_discards_old_response_even_if_cancellation_fails(self):
        stale = self.request()
        stale.set_running_or_notify_cancel()
        self.crash()
        self.controller.update(0.0)

        stale.set_result(GameAction.JUMP)
        self.now.return_value = 11.0
        self.controller.update(0.0)

        self.assertEqual(self.state.bird.velocity_y, 0.0)
        self.assertEqual(self.controller.average_response_seconds, 0.25)
        self.assertEqual(len(self.jev.requests), 2)

    def test_collision_discards_response_already_completed_in_old_run(self):
        self.request().set_result(GameAction.JUMP)

        self.crash()

        self.assertEqual(self.state.bird.velocity_y, 0.0)
        self.assertEqual(self.controller.average_response_seconds, 0.25)

    def test_collision_cancels_and_detaches_the_entire_buffer(self):
        pending = self.request()
        running = self.request()
        running.set_running_or_notify_cancel()
        completed = self.request()
        completed.set_result(GameAction.FALL)

        self.crash()

        self.assertTrue(pending.cancelled())
        self.assertFalse(running.cancelled())
        self.assertFalse(completed.cancelled())
        running.set_result(GameAction.JUMP)
        self.now.return_value = 11.0
        self.controller.update(0.0)
        self.assertEqual(self.state.bird.velocity_y, 0.0)
        self.assertEqual(self.controller.average_response_seconds, 0.25)

    def test_pause_discards_pending_request_and_resume_requests_fresh_state(self):
        stale = self.request()
        stale.set_running_or_notify_cancel()
        pending = self.request()

        self.controller.pause()
        self.assertTrue(pending.cancelled())
        self.now.return_value = 110.0
        stale.set_result(GameAction.JUMP)
        self.controller.resume()
        self.controller.update(0.0)

        self.assertEqual(len(self.jev.requests), 3)
        self.assertEqual(self.jev.requests[-1], self.state.to_state_dict(0.25))
        self.assertEqual(self.controller.average_response_seconds, 0.25)
        self.assertEqual(self.state.bird.velocity_y, 0.0)

    def test_close_cancels_and_detaches_the_entire_buffer(self):
        running = self.request()
        running.set_running_or_notify_cancel()
        pending = self.request()

        self.controller.close()

        self.assertTrue(pending.cancelled())
        running.set_result(GameAction.JUMP)
        self.now.return_value = 11.0
        self.controller.update(0.0)
        self.assertEqual(self.state.bird.velocity_y, 0.0)
        self.assertEqual(self.controller.average_response_seconds, 0.25)


if __name__ == "__main__":
    unittest.main()
