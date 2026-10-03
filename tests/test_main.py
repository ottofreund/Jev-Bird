"""Headless application lifecycle and side-by-side panel integration tests."""

import os
import runpy
import unittest
from unittest.mock import Mock, call, patch

os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"

import pygame

from jev_bird.decision_viewer import DecisionViewer
from jev_bird.gameplay_viewer import draw_game
from jev_bird.main import main
from tests.fakes import FakeJev


class GameLoopTests(unittest.TestCase):
    def test_module_entrypoint_calls_main(self):
        with patch("jev_bird.main.main") as main_mock:
            runpy.run_module("jev_bird", run_name="__main__")

        main_mock.assert_called_once_with()

    def test_pygame_is_cleaned_up_when_window_setup_fails(self):
        with (
            patch("jev_bird.main.pygame.display.set_mode", side_effect=RuntimeError("window unavailable")),
            patch("jev_bird.main.pygame.quit", wraps=pygame.quit) as quit_mock,
        ):
            with self.assertRaisesRegex(RuntimeError, "window unavailable"):
                main()
        quit_mock.assert_called_once()

    def test_headless_loop_restarts_repeatedly_and_closes_pending_request_on_quit(self):
        jev = FakeJev()
        clock = Mock()
        clock.tick.return_value = 50
        frames = [
            [pygame.event.Event(pygame.USEREVENT)] if frame % 8 == 0 else []
            for frame in range(60)
        ]
        frames.append([pygame.event.Event(pygame.QUIT)])
        draw_decision_frame = DecisionViewer.draw
        with (
            patch("jev_bird.main.Jev", return_value=jev),
            patch("jev_bird.main.pygame.time.Clock", return_value=clock),
            patch("jev_bird.main.pygame.event.get", side_effect=frames),
            patch("jev_bird.main.pygame.time.set_timer", wraps=pygame.time.set_timer) as set_timer,
            patch("jev_bird.main.pygame.display.set_mode", wraps=pygame.display.set_mode) as set_mode,
            patch("jev_bird.main.draw_game", wraps=draw_game) as draw_live,
            patch(
                "jev_bird.main.DecisionViewer.draw", autospec=True, side_effect=draw_decision_frame
            ) as draw_decision,
            patch("jev_bird.main.pygame.quit", wraps=pygame.quit) as quit_mock,
        ):
            main()

        self.assertGreaterEqual(len(jev.requests), 3)
        self.assertTrue(jev.closed)
        self.assertTrue(all(future.cancelled() for future in jev.futures))
        self.assertEqual(
            set_timer.call_args_list,
            [call(pygame.USEREVENT, 50), call(pygame.USEREVENT, 0)],
        )
        quit_mock.assert_called_once()
        set_mode.assert_called_once_with((900, 600))
        self.assertEqual(draw_live.call_count, 60)
        self.assertEqual(draw_live.call_args.args[0].get_size(), (400, 600))
        self.assertEqual(draw_decision.call_count, 60)
        self.assertEqual(draw_decision.call_args.args[1].get_size(), (500, 600))

    def test_space_pauses_updates_until_space_is_pressed_again(self):
        jev = FakeJev()
        clock = Mock()
        clock.tick.return_value = 16
        frames = [
            [pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE)],
            [pygame.event.Event(pygame.USEREVENT)],
            [pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE)],
            [pygame.event.Event(pygame.QUIT)],
        ]

        with (
            patch("jev_bird.main.Jev", return_value=jev),
            patch("jev_bird.main.pygame.time.Clock", return_value=clock),
            patch("jev_bird.main.pygame.event.get", side_effect=frames),
            patch("jev_bird.main.GameController") as controller_type,
            patch("jev_bird.main.draw_game") as draw_game_mock,
            patch("jev_bird.main.DecisionViewer.draw"),
            patch("jev_bird.main.pygame.quit", wraps=pygame.quit),
        ):
            controller = controller_type.return_value
            main()

        controller.update.assert_called_once_with(0.016, request_due=False)
        controller.pause.assert_called_once_with()
        controller.resume.assert_called_once_with()
        controller.close.assert_called_once_with()
        self.assertEqual(
            [call.kwargs["paused"] for call in draw_game_mock.call_args_list],
            [True, True, False],
        )

    def test_each_queued_timer_event_submits_one_request(self):
        clock = Mock()
        clock.tick.return_value = 16
        timer_event = pygame.event.Event(pygame.USEREVENT)
        frames = [[timer_event, timer_event], [pygame.event.Event(pygame.QUIT)]]

        with (
            patch("jev_bird.main.Jev"),
            patch("jev_bird.main.pygame.time.Clock", return_value=clock),
            patch("jev_bird.main.pygame.event.get", side_effect=frames),
            patch("jev_bird.main.GameController") as controller_type,
            patch("jev_bird.main.draw_game"),
            patch("jev_bird.main.DecisionViewer.draw"),
            patch("jev_bird.main.pygame.quit", wraps=pygame.quit),
        ):
            controller = controller_type.return_value
            main()

        self.assertEqual(
            controller.update.call_args_list,
            [
                call(0.016, request_due=True),
                call(0.0, request_due=True),
            ],
        )


if __name__ == "__main__":
    unittest.main()
