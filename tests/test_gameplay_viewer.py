"""Headless rendering checks for the live gameplay panel."""

import os
import random
import unittest

os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"

import pygame

from jev_bird.game import SCREEN_HEIGHT, SCREEN_WIDTH, GameState
from jev_bird.gameplay_viewer import BIRD_YELLOW, SKY_BLUE, draw_game


class RenderingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        cls.screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
        cls.score_font = pygame.font.Font(None, 48)
        cls.message_font = pygame.font.Font(None, 32)

    @classmethod
    def tearDownClass(cls):
        pygame.quit()

    def test_draws_playing_and_game_over_frames(self):
        state = GameState(random.Random(5))

        draw_game(self.screen, state, self.score_font, self.message_font)
        bird_center = state.bird.rect.center
        self.assertEqual(self.screen.get_at((0, 0))[:3], SKY_BLUE)
        self.assertEqual(self.screen.get_at(bird_center)[:3], BIRD_YELLOW)

        state.game_over = True
        draw_game(self.screen, state, self.score_font, self.message_font)
        pygame.display.flip()

        self.assertEqual(self.screen.get_size(), (SCREEN_WIDTH, SCREEN_HEIGHT))


if __name__ == "__main__":
    unittest.main()
