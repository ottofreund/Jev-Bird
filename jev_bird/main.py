"""Launch live gameplay and the review of the last action before failure."""

from __future__ import annotations

import logging

import pygame

from .controller import GameController
from .decision_viewer import PANEL_WIDTH, DecisionViewer
from .game import SCREEN_HEIGHT, SCREEN_WIDTH, GameState
from .gameplay_viewer import draw_game
from .jev import Jev


FPS = 60
MAX_FRAME_TIME = 0.05
JEV_REQUEST_INTERVAL_MS = 50


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    pygame.init()
    try:
        screen = pygame.display.set_mode((SCREEN_WIDTH + PANEL_WIDTH, SCREEN_HEIGHT))
        pygame.display.set_caption("JEV Flappy Bird - gameplay and decisions")
        gameplay_surface = screen.subsurface((0, 0, SCREEN_WIDTH, SCREEN_HEIGHT))
        decision_surface = screen.subsurface((SCREEN_WIDTH, 0, PANEL_WIDTH, SCREEN_HEIGHT))
        decision_viewer = DecisionViewer(SCREEN_WIDTH, SCREEN_HEIGHT)
        clock = pygame.time.Clock()
        score_font = pygame.font.Font(None, 48)
        message_font = pygame.font.Font(None, 32)
        state = GameState()
        running = True
        paused = False

        with Jev() as jev:
            controller = GameController(state, jev)
            pygame.time.set_timer(pygame.USEREVENT, JEV_REQUEST_INTERVAL_MS)
            try:
                while running:
                    elapsed_seconds = min(clock.tick(FPS) / 1_000.0, MAX_FRAME_TIME)
                    request_count = 0
                    for event in pygame.event.get():
                        if event.type == pygame.QUIT:
                            running = False
                        elif event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
                            paused = not paused
                            if paused:
                                controller.pause()
                            else:
                                controller.resume()
                        elif event.type == pygame.USEREVENT:
                            request_count += 1

                    if not running:
                        break

                    if not paused:
                        controller.update(elapsed_seconds, request_due=request_count > 0)
                        for _ in range(1, request_count):
                            controller.update(0.0, request_due=True)
                    draw_game(
                        gameplay_surface,
                        state,
                        score_font,
                        message_font,
                        paused=paused,
                    )
                    decision_viewer.draw(decision_surface, controller.decision_view)
                    pygame.display.flip()
            finally:
                pygame.time.set_timer(pygame.USEREVENT, 0)
                controller.close()
    finally:
        pygame.quit()


if __name__ == "__main__":
    main()
