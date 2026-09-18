from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Literal

Direction = Literal["up", "down", "left", "right"]
DIRECTIONS: tuple[Direction, ...] = ("up", "down", "left", "right")

Board = list[list[int]]


def empty_board() -> Board:
    return [[0, 0, 0, 0] for _ in range(4)]


def copy_board(board: Board) -> Board:
    return [row[:] for row in board]


def _slide_left(row: list[int]) -> tuple[list[int], int]:
    tiles = [value for value in row if value]
    merged: list[int] = []
    score = 0
    i = 0
    while i < len(tiles):
        if i + 1 < len(tiles) and tiles[i] == tiles[i + 1]:
            value = tiles[i] * 2
            merged.append(value)
            score += value
            i += 2
        else:
            merged.append(tiles[i])
            i += 1
    merged.extend([0] * (4 - len(merged)))
    return merged, score


def _rotate_cw(board: Board) -> Board:
    return [list(row) for row in zip(*board[::-1])]


def _rotate_ccw(board: Board) -> Board:
    return [list(row) for row in zip(*board)][::-1]


def apply_move(board: Board, direction: Direction) -> tuple[Board, int, bool]:
    """Slide and merge. Returns (new_board, score_gained, changed)."""
    if direction == "left":
        oriented = copy_board(board)
        restore = lambda b: b
    elif direction == "right":
        oriented = [row[::-1] for row in board]
        restore = lambda b: [row[::-1] for row in b]
    elif direction == "up":
        oriented = _rotate_ccw(board)
        restore = _rotate_cw
    else:
        oriented = _rotate_cw(board)
        restore = _rotate_ccw

    moved: Board = []
    gained = 0
    for row in oriented:
        new_row, score = _slide_left(row)
        moved.append(new_row)
        gained += score

    result = restore(moved)
    changed = result != board
    return result, gained, changed


def empty_cells(board: Board) -> list[tuple[int, int]]:
    return [(r, c) for r in range(4) for c in range(4) if board[r][c] == 0]


def spawn(board: Board, rng: random.Random) -> None:
    cells = empty_cells(board)
    if not cells:
        return
    r, c = rng.choice(cells)
    board[r][c] = 4 if rng.random() < 0.1 else 2


def legal_moves(board: Board) -> list[Direction]:
    moves: list[Direction] = []
    for direction in DIRECTIONS:
        _, _, changed = apply_move(board, direction)
        if changed:
            moves.append(direction)
    return moves


def format_board(board: Board) -> str:
    def cell(value: int) -> str:
        return f"{value:4d}" if value else "   ."

    lines = [" ".join(cell(value) for value in row) for row in board]
    return "\n".join(lines)


@dataclass
class Game:
    rng: random.Random = field(default_factory=random.Random)
    board: Board = field(default_factory=empty_board)
    score: int = 0
    moves: int = 0
    last_move: Direction | None = None
    last_gain: int = 0
    won: bool = False

    def start(self) -> None:
        self.board = empty_board()
        self.score = 0
        self.moves = 0
        self.last_move = None
        self.last_gain = 0
        self.won = False
        spawn(self.board, self.rng)
        spawn(self.board, self.rng)

    def hydrate(self, board: Board, score: int, won: bool = False) -> None:
        """Mirror an external board (web 2048). Does not spawn tiles."""
        self.last_gain = max(0, score - self.score)
        self.board = copy_board(board)
        self.score = score
        if won or self.highest >= 2048:
            self.won = True

    @property
    def highest(self) -> int:
        return max(max(row) for row in self.board)

    @property
    def empty(self) -> int:
        return len(empty_cells(self.board))

    def step(self, direction: Direction) -> bool:
        new_board, gained, changed = apply_move(self.board, direction)
        if not changed:
            return False
        self.board = new_board
        self.score += gained
        self.last_gain = gained
        self.last_move = direction
        self.moves += 1
        if self.highest >= 2048:
            self.won = True
        spawn(self.board, self.rng)
        return True

    def over(self) -> bool:
        return not legal_moves(self.board)

    def state_blob(self) -> dict:
        return {
            "board": format_board(self.board),
            "grid": self.board,
            "score": self.score,
            "moves": self.moves,
            "highest_tile": self.highest,
            "empty_cells": self.empty,
            "last_move": self.last_move,
            "last_merge_score": self.last_gain,
            "legal_moves": legal_moves(self.board),
        }
