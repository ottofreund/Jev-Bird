"""Game geometry, physics, collision rules, and request-state capture."""

from __future__ import annotations

import random
from dataclasses import dataclass

import pygame

from .decisions import (
    BirdMotion,
    BirdPosition,
    BirdSnapshot,
    DecisionSnapshot,
    JevState,
    PipeSnapshot,
)


SCREEN_WIDTH = 400
SCREEN_HEIGHT = 600

BIRD_WIDTH = 34
BIRD_HEIGHT = 24
BIRD_X = 80.0
BIRD_START_Y = (SCREEN_HEIGHT - BIRD_HEIGHT) / 2
GRAVITY = 1_000.0
FLAP_VELOCITY = -350.0

PIPE_WIDTH = 64
PIPE_GAP = 170
PIPE_SPEED = 160.0
PIPE_SPAWN_INTERVAL = 1.5
PIPE_START_X = SCREEN_WIDTH + 50.0
PIPE_MARGIN = 60

JUMP_HEIGHT = FLAP_VELOCITY**2 / (2 * GRAVITY)

RISING_VELOCITY_LIMIT = -50.0
LEVEL_VELOCITY_LIMIT = 50.0
FAST_FALL_VELOCITY = 350.0


def _classify_motion(velocity_y: float) -> BirdMotion:
    if velocity_y < RISING_VELOCITY_LIMIT:
        return "rising"
    if velocity_y <= LEVEL_VELOCITY_LIMIT:
        return "level"
    if velocity_y < FAST_FALL_VELOCITY:
        return "falling"
    return "falling fast"


def _classify_position(
    bird_center_y: float, gap_top: float, gap_bottom: float
) -> BirdPosition:
    if bird_center_y < gap_top:
        return "above the gap"
    if bird_center_y > gap_bottom:
        return "below the gap"
    if bird_center_y <= (gap_top + gap_bottom) / 2:
        return "inside the gap, upper half"
    return "inside the gap, lower half"


@dataclass
class Bird:
    """The player's position and vertical movement."""

    x: float = BIRD_X
    y: float = BIRD_START_Y
    velocity_y: float = 0.0
    width: int = BIRD_WIDTH
    height: int = BIRD_HEIGHT

    @property
    def rect(self) -> pygame.Rect:
        return pygame.Rect(round(self.x), round(self.y), self.width, self.height)

    def flap(self) -> None:
        self.velocity_y = FLAP_VELOCITY

    def update(self, elapsed_seconds: float) -> None:
        self.velocity_y += GRAVITY * elapsed_seconds
        self.y += self.velocity_y * elapsed_seconds

    def predicted_y(self, prediction_seconds: float) -> float:
        """Extrapolate the action-time position without advancing game physics."""
        return (
            self.y
            + self.velocity_y * prediction_seconds
            + 0.5 * GRAVITY * prediction_seconds**2
        )

    def bottom_edge_y(self) -> float:
        return self.y + self.height

    def top_edge_y(self) -> float:
        return self.y

    def front_edge_x(self) -> float:
        return self.x + self.width


@dataclass
class PipePair:
    """A top and bottom pipe that share one horizontal position."""

    x: float
    gap_top: int
    scored: bool = False

    @property
    def top_rect(self) -> pygame.Rect:
        return pygame.Rect(round(self.x), 0, PIPE_WIDTH, self.gap_top)

    @property
    def bottom_rect(self) -> pygame.Rect:
        bottom_top = self.gap_top + PIPE_GAP
        return pygame.Rect(
            round(self.x),
            bottom_top,
            PIPE_WIDTH,
            SCREEN_HEIGHT - bottom_top,
        )

    @property
    def right(self) -> float:
        return self.x + PIPE_WIDTH

    def bottom_pipe_top_edge_y(self) -> float:
        return self.gap_top + PIPE_GAP

    def top_pipe_bottom_edge_y(self) -> float:
        return self.gap_top

    def update(self, elapsed_seconds: float) -> None:
        self.x -= PIPE_SPEED * elapsed_seconds

    def is_offscreen(self) -> bool:
        return self.right < 0


class GameState:
    """Deterministic game rules kept separate from input and drawing."""

    def __init__(self, rng: random.Random | None = None) -> None:
        self.rng = rng if rng is not None else random.Random()
        self.bird = Bird()
        self.pipes: list[PipePair] = []
        self.score = 0
        self.game_over = False
        self.spawn_elapsed = 0.0
        self.reset()

    def create_pipe(self, x: float = PIPE_START_X) -> PipePair:
        largest_gap_top = SCREEN_HEIGHT - PIPE_MARGIN - PIPE_GAP
        gap_top = self.rng.randint(PIPE_MARGIN, largest_gap_top)
        return PipePair(x=x, gap_top=gap_top)

    def reset(self) -> None:
        self.bird = Bird()
        self.pipes = [self.create_pipe()]
        self.score = 0
        self.game_over = False
        self.spawn_elapsed = 0.0

    def flap(self) -> None:
        if not self.game_over:
            self.bird.flap()

    def has_collision(self) -> bool:
        bird_rect = self.bird.rect
        if bird_rect.top <= 0 or bird_rect.bottom >= SCREEN_HEIGHT:
            return True

        return any(
            bird_rect.colliderect(pipe.top_rect)
            or bird_rect.colliderect(pipe.bottom_rect)
            for pipe in self.pipes
        )

    def update(self, elapsed_seconds: float) -> None:
        if self.game_over:
            return

        self.bird.update(elapsed_seconds)
        for pipe in self.pipes:
            pipe.update(elapsed_seconds)

        self.spawn_elapsed += elapsed_seconds

        if self.has_collision():
            self.game_over = True
            return

        while self.spawn_elapsed >= PIPE_SPAWN_INTERVAL:
            self.spawn_elapsed -= PIPE_SPAWN_INTERVAL
            self.pipes.append(self.create_pipe())

        for pipe in self.pipes:
            if not pipe.scored and pipe.right < self.bird.x:
                pipe.scored = True
                self.score += 1

        self.pipes = [pipe for pipe in self.pipes if not pipe.is_offscreen()]

    def to_state_dict(self, prediction_seconds: float = 0.0) -> JevState:
        """Describe the bird at the predicted action time without moving the world."""
        return self.capture_decision_snapshot(prediction_seconds).to_state_dict()

    def capture_decision_snapshot(self, prediction_seconds: float) -> DecisionSnapshot:
        """Capture geometry and input values together before an asynchronous request."""
        bird_top = self.bird.predicted_y(prediction_seconds)
        bird_center = bird_top + self.bird.height / 2
        predicted_velocity = self.bird.velocity_y + GRAVITY * prediction_seconds
        bird_motion = _classify_motion(predicted_velocity)
        pipe = next(
            (
                pipe
                for pipe in self.pipes
                if pipe.right > self.bird.front_edge_x()
            ),
            None,
        )
        pipe_snapshot = None
        bird_position: BirdPosition | None = None
        next_pipe_values: tuple[str, str, str] | None = None
        if pipe is not None:
            pipe_snapshot = PipeSnapshot(
                x=pipe.x,
                width=PIPE_WIDTH,
                gap_top=pipe.top_pipe_bottom_edge_y(),
                gap_bottom=pipe.bottom_pipe_top_edge_y(),
            )
            bird_position = _classify_position(
                bird_center,
                pipe_snapshot.gap_top,
                pipe_snapshot.gap_bottom,
            )
            next_pipe_values = (
                str(int(pipe_snapshot.x - self.bird.front_edge_x())),
                str(int(pipe_snapshot.gap_top)),
                str(int(pipe_snapshot.gap_bottom)),
            )
        return DecisionSnapshot(
            bird=BirdSnapshot(
                x=self.bird.x,
                y=self.bird.y,
                predicted_y=bird_top,
                width=self.bird.width,
                height=self.bird.height,
            ),
            pipe=pipe_snapshot,
            prediction_seconds=prediction_seconds,
            bird_position=bird_position,
            bird_motion=bird_motion,
            next_pipe_values=next_pipe_values,
        )
