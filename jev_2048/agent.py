from __future__ import annotations

import os
from dataclasses import dataclass

from jev_2048.game import DIRECTIONS, Direction, Game, legal_moves

MOVE_CRITERIA: dict[str, str] = {
    "up": "Swipe up. Prefer this when it slides the max tile toward the top or merges a stack without opening the top-left/bottom-left corner you are using as home.",
    "down": "Swipe down. Prefer this when it parks the largest tile in a bottom corner or merges downward along a monotonic column.",
    "left": "Swipe left. Prefer this when it builds a sorted row toward the left, especially the edge that holds the high tile.",
    "right": "Swipe right. Prefer this when it builds a sorted row toward the right or is the only way to merge without trapping the high tile.",
}

SYSTEM_INSTRUCTIONS = """You are playing 2048.

Goal: reach a 2048 tile, then keep going for score.
Strategy:
- Keep the highest tile in one corner and do not move it out.
- Build a monotonic snake (descending along an edge).
- Never swipe in a way that pulls the high tile out of its corner unless every other move is worse.
- Prefer merges that free empty cells.
- Avoid filling the last empty cells if a merge exists.
- If a move is not listed in legal_moves it is illegal; do not pick it.
"""


@dataclass
class Decision:
    move: Direction
    probabilities: dict[str, float]
    confidence: float
    source: str
    usage_input: int = 0
    latency_note: str = ""


class JevBlockedError(RuntimeError):
    pass


def _legal_criteria(game: Game) -> dict[str, str]:
    allowed = legal_moves(game.board)
    return {name: MOVE_CRITERIA[name] for name in allowed}


def decide_heuristic(game: Game) -> Decision:
    """Corner-snake fallback so a missing API key still plays."""
    allowed = legal_moves(game.board)
    if not allowed:
        raise JevBlockedError("no legal moves")

    def score_move(direction: Direction) -> float:
        from jev_2048.game import apply_move

        board, gained, _ = apply_move(game.board, direction)
        empty = sum(1 for row in board for value in row if value == 0)
        max_tile = max(max(row) for row in board)
        corner_bonus = 0.0
        if board[3][0] == max_tile or board[3][3] == max_tile:
            corner_bonus = 8.0
        elif board[0][0] == max_tile or board[0][3] == max_tile:
            corner_bonus = 4.0
        # Prefer down/left to settle toward bottom-left.
        dir_bias = {"down": 1.5, "left": 1.2, "right": 0.4, "up": 0.1}[direction]
        return gained * 1.2 + empty * 3.0 + corner_bonus + dir_bias

    ranked = sorted(allowed, key=score_move, reverse=True)
    best = ranked[0]
    raw = {d: score_move(d) for d in allowed}
    total = sum(raw.values()) or 1.0
    probs = {d: (raw.get(d, 0) / total) for d in DIRECTIONS}
    return Decision(
        move=best,
        probabilities=probs,
        confidence=probs[best],
        source="heuristic",
    )


def decide_jev(game: Game) -> Decision:
    try:
        from typesafe_sdk import Choice, TypeSafeClient
    except ImportError as exc:
        raise JevBlockedError(
            "typesafe-sdk is not installed. Run: uv sync"
        ) from exc

    api_key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not api_key or api_key.startswith("sk-your-") or api_key.startswith("sk-your"):
        raise JevBlockedError(
            "TYPESAFE_API_KEY is missing. Copy .env.example to .env and paste a key from https://console.typesafe.ai/settings/keys"
        )

    criteria = _legal_criteria(game)
    if not criteria:
        raise JevBlockedError("no legal moves")
    if len(criteria) == 1:
        only = next(iter(criteria))
        return Decision(
            move=only,  # type: ignore[arg-type]
            probabilities={d: 1.0 if d == only else 0.0 for d in DIRECTIONS},
            confidence=1.0,
            source="forced",
            latency_note="skipped Jev (only one legal move)",
        )

    client = TypeSafeClient(api_key=api_key)
    kwargs = {}
    model = os.environ.get("JEV_MODEL")
    if model:
        kwargs["model"] = model

    response = client.system_one(
        state={
            "game": "2048",
            "rules": SYSTEM_INSTRUCTIONS,
            **game.state_blob(),
        },
        questions={
            "move": Choice(
                instructions=(
                    "Pick the next swipe. Only consider legal_moves. "
                    "Keep the highest tile in a corner. Maximize empty cells and merges."
                ),
                criteria=criteria,
            ),
        },
        **kwargs,
    )
    answer = response.answers["move"]
    choice = answer.choice
    if choice not in criteria:
        # Should be impossible (typed Choice), but never apply an illegal swipe.
        return decide_heuristic(game)

    probs = {d: 0.0 for d in DIRECTIONS}
    for name, value in (answer.probabilities or {}).items():
        probs[name] = float(value)

    usage = getattr(response, "usage", None)
    input_tokens = getattr(usage, "input_tokens", 0) if usage else 0

    return Decision(
        move=choice,
        probabilities=probs,
        confidence=float(getattr(answer, "confidence", probs.get(choice, 0.0))),
        source="jev",
        usage_input=int(input_tokens or 0),
    )
