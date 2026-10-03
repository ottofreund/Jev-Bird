"""Shared action and immutable decision data, independent of UI and API clients."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal, TypedDict


BirdPosition = Literal[
    "above the gap",
    "below the gap",
    "inside the gap, upper half",
    "inside the gap, lower half",
]
BirdMotion = Literal["rising", "level", "falling", "falling fast"]


class JevBirdState(TypedDict):
    position: BirdPosition | None
    motion: BirdMotion


class JevNextPipe(TypedDict):
    distance_x: str
    gap_top_y: str
    gap_bottom_y: str


class JevState(TypedDict):
    bird: JevBirdState
    next_pipe: JevNextPipe | None
    bird_jump_height: Literal["Roughly third of pipe gap"]
    y_axis: Literal["y grows downward; smaller y is higher up"]
    length_unit: Literal["pixel"]


class GameAction(Enum):
    JUMP = "jump"
    FALL = "fall"


@dataclass(frozen=True)
class ActionDecision:
    """An action selected by JEV and its reported certainty."""

    action: GameAction
    confidence: float


@dataclass(frozen=True)
class BirdSnapshot:
    """Original and predicted bird geometry captured at submission."""

    x: float
    y: float
    predicted_y: float
    width: int
    height: int


@dataclass(frozen=True)
class PipeSnapshot:
    """The upcoming pipe geometry captured with a request."""

    x: float
    width: int
    gap_top: float
    gap_bottom: float


@dataclass(frozen=True)
class DecisionSnapshot:
    """Immutable geometry paired with the exact semantic request values."""

    bird: BirdSnapshot
    pipe: PipeSnapshot | None
    prediction_seconds: float
    bird_position: BirdPosition | None
    bird_motion: BirdMotion
    next_pipe_values: tuple[str, str, str] | None

    def to_state_dict(self) -> JevState:
        """Return a fresh nested copy of the exact request values."""
        next_pipe: JevNextPipe | None = None
        if self.next_pipe_values is not None:
            distance_x, gap_top_y, gap_bottom_y = self.next_pipe_values
            next_pipe = {
                "distance_x": distance_x,
                "gap_top_y": gap_top_y,
                "gap_bottom_y": gap_bottom_y,
            }
        return {
            "bird": {
                "position": self.bird_position,
                "motion": self.bird_motion,
            },
            "next_pipe": next_pipe,
            "bird_jump_height": "Roughly third of pipe gap",
            "y_axis": "y grows downward; smaller y is higher up",
            "length_unit": "pixel",
        }


@dataclass(frozen=True)
class CompletedDecision:
    """An action consumed by the controller, with its original request context."""

    snapshot: DecisionSnapshot
    action: GameAction
    response_seconds: float
    confidence: float | None = None


@dataclass(frozen=True)
class DecisionView:
    """Failure review: empty initially or when a run failed before an action."""

    completed: CompletedDecision | None = None
    failure_recorded: bool = False
