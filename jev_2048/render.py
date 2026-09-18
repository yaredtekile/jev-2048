from __future__ import annotations

from jev_2048.agent import Decision
from jev_2048.game import DIRECTIONS, Game

PALETTE = {
    0: "\033[2m",
    2: "\033[97m",
    4: "\033[93m",
    8: "\033[33m",
    16: "\033[91m",
    32: "\033[31m",
    64: "\033[95m",
    128: "\033[35m",
    256: "\033[94m",
    512: "\033[36m",
    1024: "\033[92m",
    2048: "\033[42;30;1m",
}
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"


def _cell(value: int) -> str:
    color = PALETTE.get(value, "\033[97;1m")
    label = f"{value:^6}" if value else "      "
    return f"{color}{label}{RESET}"


def render(game: Game, decision: Decision | None, total_tokens: int) -> str:
    lines = [
        f"{BOLD}Jev 2048{RESET}  {DIM}TypeSafe System One{RESET}",
        "",
        f"  score {BOLD}{game.score}{RESET}   moves {game.moves}   highest {game.highest}   empty {game.empty}",
    ]
    if decision:
        bars = []
        for direction in DIRECTIONS:
            p = decision.probabilities.get(direction, 0.0)
            filled = round(p * 10)
            bar = "█" * filled + "░" * (10 - filled)
            marker = "◄" if direction == decision.move else " "
            bars.append(f"  {marker} {direction:<5} {bar} {p:5.0%}")
        lines.append("")
        lines.extend(bars)
        lines.append(
            f"  {DIM}source={decision.source}  confidence={decision.confidence:.2f}  "
            f"tokens={total_tokens}{RESET}"
        )
        if decision.latency_note:
            lines.append(f"  {DIM}{decision.latency_note}{RESET}")
    lines.append("")
    for row in game.board:
        lines.append("  ┌──────┬──────┬──────┬──────┐" if row is game.board[0] else "  ├──────┼──────┼──────┼──────┤")
        lines.append("  │" + "│".join(_cell(v) for v in row) + "│")
    lines.append("  └──────┴──────┴──────┴──────┘")
    return "\n".join(lines)


def hud_text(game: Game, decision: Decision | None, total_tokens: int) -> str:
    lines = [
        f"score {game.score}   moves {game.moves}",
        f"highest {game.highest}   empty {game.empty}",
        "",
    ]
    if decision:
        for direction in DIRECTIONS:
            p = decision.probabilities.get(direction, 0.0)
            filled = round(max(0.0, min(1.0, p)) * 10)
            bar = "█" * filled + "░" * (10 - filled)
            mark = "►" if direction == decision.move else " "
            lines.append(f"{mark} {direction:<5} {bar} {p:5.0%}")
        lines.append("")
        lines.append(
            f"source={decision.source}  conf={decision.confidence:.2f}"
        )
        lines.append(f"tokens={total_tokens}")
        if decision.latency_note:
            lines.append(decision.latency_note)
    return "\n".join(lines)

