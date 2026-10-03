"""Pygame rendering for the live gameplay panel."""

from __future__ import annotations

import pygame

from .game import SCREEN_HEIGHT, SCREEN_WIDTH, GameState


SKY_BLUE = (112, 197, 255)
PIPE_GREEN = (65, 190, 80)
PIPE_DARK_GREEN = (35, 130, 55)
BIRD_YELLOW = (255, 220, 45)
BIRD_ORANGE = (245, 135, 35)
WHITE = (255, 255, 255)
BLACK = (25, 25, 25)

def _draw_centered_text(
    surface: pygame.Surface,
    text: str,
    font: pygame.font.Font,
    color: tuple[int, int, int],
    center_y: int,
) -> None:
    rendered = font.render(text, True, color)
    rect = rendered.get_rect(center=(SCREEN_WIDTH // 2, center_y))
    surface.blit(rendered, rect)


def draw_game(
    surface: pygame.Surface,
    state: GameState,
    score_font: pygame.font.Font,
    message_font: pygame.font.Font,
    *,
    paused: bool = False,
) -> None:
    """Draw one complete frame without changing game state."""

    surface.fill(SKY_BLUE)

    for pipe in state.pipes:
        pygame.draw.rect(surface, PIPE_GREEN, pipe.top_rect)
        pygame.draw.rect(surface, PIPE_GREEN, pipe.bottom_rect)
        pygame.draw.rect(surface, PIPE_DARK_GREEN, pipe.top_rect, width=3)
        pygame.draw.rect(surface, PIPE_DARK_GREEN, pipe.bottom_rect, width=3)

    bird_rect = state.bird.rect
    pygame.draw.rect(surface, BIRD_YELLOW, bird_rect, border_radius=8)
    pygame.draw.ellipse(
        surface,
        BIRD_ORANGE,
        pygame.Rect(bird_rect.left - 3, bird_rect.centery, 14, 9),
    )
    pygame.draw.circle(surface, WHITE, (bird_rect.right - 8, bird_rect.top + 7), 5)
    pygame.draw.circle(surface, BLACK, (bird_rect.right - 7, bird_rect.top + 7), 2)

    score_shadow = score_font.render(str(state.score), True, BLACK)
    score_text = score_font.render(str(state.score), True, WHITE)
    score_rect = score_text.get_rect(midtop=(SCREEN_WIDTH // 2, 20))
    surface.blit(score_shadow, score_rect.move(2, 2))
    surface.blit(score_text, score_rect)

    if state.game_over:
        overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 90))
        surface.blit(overlay, (0, 0))
        _draw_centered_text(
            surface, "Game over", score_font, WHITE, SCREEN_HEIGHT // 2 - 20
        )
        _draw_centered_text(
            surface,
            "Restarting...",
            message_font,
            WHITE,
            SCREEN_HEIGHT // 2 + 28,
        )

    if paused:
        overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 110))
        surface.blit(overlay, (0, 0))
        _draw_centered_text(surface, "Paused", score_font, WHITE, SCREEN_HEIGHT // 2 - 20)
        _draw_centered_text(
            surface,
            "Press Space to resume",
            message_font,
            WHITE,
            SCREEN_HEIGHT // 2 + 28,
        )
