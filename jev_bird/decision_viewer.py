"""Pygame rendering of JEV's last applied action before failure."""

from __future__ import annotations

import pygame

from .decisions import CompletedDecision, DecisionView, GameAction


PANEL_WIDTH = 500
SCENE_BOUNDS = (16, 158, 250, 360)
CONFIDENCE_BAR_BOUNDS = (164, 103, 320, 24)
VALUES_X = 280

BACKGROUND = (20, 27, 39)
PLAYFIELD = (30, 43, 58)
TEXT = (235, 241, 248)
MUTED = (156, 173, 194)
ORIGINAL = (166, 188, 217)
PREDICTED = (255, 220, 80)
OBSTACLE = (49, 120, 97)
GAP = (86, 226, 167)
WARNING = (255, 139, 126)


class DecisionViewer:
    """Draw frozen decision geometry; never read or modify the live world."""

    def __init__(self, world_width: int, world_height: int) -> None:
        self.world_width = world_width
        self.world_height = world_height
        self.title_font = pygame.font.Font(None, 32)
        self.action_font = pygame.font.Font(None, 28)
        self.font = pygame.font.Font(None, 22)
        self.small_font = pygame.font.Font(None, 19)

    def _text(
        self,
        surface: pygame.Surface,
        text: str,
        position: tuple[int, int],
        color: tuple[int, int, int] = TEXT,
        font: pygame.font.Font | None = None,
    ) -> None:
        surface.blit((font or self.font).render(text, True, color), position)

    def draw(self, surface: pygame.Surface, view: DecisionView) -> None:
        surface.fill(BACKGROUND)
        self._text(surface, "JEV failure review", (16, 16), font=self.title_font)
        status = (
            "Last action before failure / frozen state"
            if view.failure_recorded else "Waiting for first failure..."
        )
        self._text(surface, status, (16, 51), MUTED)

        if view.completed is None:
            if view.failure_recorded:
                self._text(surface, "No JEV action was applied before this failure.", (16, 130))
            else:
                self._text(surface, "The final action and its supplied state appear", (16, 130))
                self._text(surface, "here after the game fails.", (16, 156), MUTED)
            return

        decision = view.completed
        action_label = "Jump" if decision.action == GameAction.JUMP else "Fall"
        self._text(surface, action_label, (16, 79), PREDICTED, self.action_font)
        self._draw_confidence(surface, decision.confidence)
        self._text(surface, "State supplied to JEV", (16, 136), MUTED, self.small_font)
        self._draw_scene(surface, decision)
        self._draw_values(surface, decision)

        pygame.draw.rect(surface, ORIGINAL, (16, 553, 18, 12), width=2)
        self._text(surface, "At request", (42, 550), MUTED, self.small_font)
        pygame.draw.rect(surface, PREDICTED, (152, 553, 18, 12))
        self._text(surface, "Latency-adjusted", (178, 550), MUTED, self.small_font)
        self._text(
            surface, "Pipe positions are captured at request time.",
            (16, 576), MUTED, self.small_font,
        )

    def _draw_confidence(
        self, surface: pygame.Surface, confidence: float | None
    ) -> None:
        confidence_label = (
            f"Confidence: {confidence:.1%}"
            if confidence is not None
            else "Confidence: unavailable"
        )
        self._text(surface, confidence_label, (16, 107), PREDICTED, self.small_font)

        meter = pygame.Rect(CONFIDENCE_BAR_BOUNDS)
        pygame.draw.rect(surface, PLAYFIELD, meter)
        inner = meter.inflate(-4, -4)
        if confidence is not None:
            bounded_confidence = max(0.0, min(1.0, confidence))
            fill_width = round(inner.width * bounded_confidence)
            if fill_width:
                pygame.draw.rect(
                    surface,
                    PREDICTED,
                    (inner.x, inner.y, fill_width, inner.height),
                )
        pygame.draw.rect(surface, MUTED, meter, width=2)

    def _draw_scene(self, surface: pygame.Surface, decision: CompletedDecision) -> None:
        snapshot = decision.snapshot
        bird, pipe = snapshot.bird, snapshot.pipe
        scene = surface.subsurface(SCENE_BOUNDS)
        scene.fill(PLAYFIELD)
        # Include pipes beyond the live screen, including the initial spawn at x=450.
        world_width = max(
            self.world_width, pipe.x + pipe.width + 20 if pipe is not None else 0
        )
        scale = min(scene.get_width() / world_width, scene.get_height() / self.world_height)
        left = (scene.get_width() - world_width * scale) / 2
        top = (scene.get_height() - self.world_height * scale) / 2
        floor = top + self.world_height * scale
        scene.set_clip(pygame.Rect(0, round(top), scene.get_width(), round(floor - top)))

        def rect(x: float, y: float, width: float, height: float) -> pygame.Rect:
            return pygame.Rect(
                round(left + x * scale), round(top + y * scale),
                max(1, round(width * scale)), max(1, round(height * scale)),
            )

        right = scene.get_width() - 1
        pygame.draw.line(scene, MUTED, (0, round(top)), (right, round(top)))
        pygame.draw.line(scene, MUTED, (0, round(floor) - 1), (right, round(floor) - 1))
        if pipe is not None:
            pygame.draw.rect(scene, OBSTACLE, rect(pipe.x, 0, pipe.width, pipe.gap_top))
            pygame.draw.rect(
                scene, OBSTACLE,
                rect(pipe.x, pipe.gap_bottom, pipe.width, self.world_height - pipe.gap_bottom),
            )
            pygame.draw.rect(
                scene, GAP,
                rect(pipe.x, pipe.gap_top, pipe.width, pipe.gap_bottom - pipe.gap_top),
                width=2,
            )

        original_rect = rect(bird.x, bird.y, bird.width, bird.height)
        predicted_rect = rect(bird.x, bird.predicted_y, bird.width, bird.height)
        pygame.draw.line(scene, ORIGINAL, original_rect.center, predicted_rect.center, width=1)
        pygame.draw.rect(scene, PREDICTED, predicted_rect, border_radius=3)
        pygame.draw.rect(scene, ORIGINAL, original_rect, width=2, border_radius=3)

        outside = bird.predicted_y < 0 or bird.predicted_y + bird.height > self.world_height
        if outside:
            edge_y = round(top) + 7 if bird.predicted_y < 0 else round(floor) - 8
            marker_x = predicted_rect.centerx
            pygame.draw.polygon(
                scene, WARNING,
                [(marker_x - 6, edge_y), (marker_x + 6, edge_y),
                 (marker_x, edge_y - 6 if bird.predicted_y < 0 else edge_y + 6)],
            )

        # Keep the action arrow visible even when the prediction is beyond a boundary.
        arrow_x = predicted_rect.right + 12
        arrow_y = round(max(top + 32, min(floor - 32, predicted_rect.centery)))
        direction = -1 if decision.action == GameAction.JUMP else 1
        tip_y = arrow_y + direction * 22
        pygame.draw.line(scene, PREDICTED, (arrow_x, arrow_y), (arrow_x, tip_y), width=3)
        pygame.draw.polygon(
            scene, PREDICTED,
            [(arrow_x, tip_y), (arrow_x - 6, tip_y - direction * 8),
             (arrow_x + 6, tip_y - direction * 8)],
        )

    def _draw_values(self, surface: pygame.Surface, decision: CompletedDecision) -> None:
        snapshot = decision.snapshot
        x = VALUES_X
        values = snapshot.to_state_dict()
        bird = values["bird"]
        pipe = values["next_pipe"]
        self._text(surface, "Exact state supplied", (x, 158), GAP, self.small_font)
        y = 180
        y = self._field(surface, x, y, "bird.position", bird["position"])
        y = self._field(surface, x, y, "bird.motion", bird["motion"])
        if pipe is None:
            y = self._field(surface, x, y, "next_pipe", None)
        else:
            y = self._field(surface, x, y, "next_pipe.distance_x", pipe["distance_x"])
            y = self._field(surface, x, y, "next_pipe.gap_top_y", pipe["gap_top_y"])
            y = self._field(surface, x, y, "next_pipe.gap_bottom_y", pipe["gap_bottom_y"])
        y = self._field(surface, x, y, "bird_jump_height", values["bird_jump_height"])
        y = self._field(surface, x, y, "y_axis", values["y_axis"])
        self._field(surface, x, y, "length_unit", values["length_unit"])

        self._text(surface, f"Prediction: {snapshot.prediction_seconds * 1000:.0f} ms",
                   (16, 522), font=self.small_font)
        self._text(surface, f"Response: {decision.response_seconds * 1000:.0f} ms",
                   (174, 522), font=self.small_font)
        self._text(surface, f"Predicted y: {snapshot.bird.predicted_y:.2f}",
                   (326, 522), font=self.small_font)

    def _field(
        self,
        surface: pygame.Surface,
        x: int,
        y: int,
        label: str,
        value: str | None,
    ) -> int:
        """Draw one payload leaf, wrapping values within the narrow detail column."""
        self._text(surface, label, (x, y), MUTED, self.small_font)
        y += 15
        text = "null" if value is None else value
        words = text.split()
        lines: list[str] = []
        line = ""
        for word in words:
            candidate = f"{line} {word}".strip()
            if line and self.small_font.size(candidate)[0] > PANEL_WIDTH - x - 8:
                lines.append(line)
                line = word
            else:
                line = candidate
        lines.append(line)
        for line in lines:
            self._text(surface, line, (x, y), TEXT, self.small_font)
            y += 15
        return y + 3
