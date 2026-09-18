from __future__ import annotations

import json
import time
from typing import Any

from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

from jev_2048.game import Board, Direction, empty_board

CLASSIC_URL = "https://classic.play2048.co/"

KEYS: dict[Direction, str] = {
    "up": "ArrowUp",
    "down": "ArrowDown",
    "left": "ArrowLeft",
    "right": "ArrowRight",
}

READ_STATE_JS = """() => {
  const raw = localStorage.getItem('gameState');
  if (raw) {
    try { return JSON.parse(raw); } catch (e) {}
  }
  const board = Array.from({length: 4}, () => [0, 0, 0, 0]);
  for (const el of document.querySelectorAll('.tile')) {
    const cls = el.className || '';
    const pos = cls.match(/tile-position-(\\d)-(\\d)/);
    const val = cls.match(/tile-(\\d+)/);
    if (!pos || !val) continue;
    const x = Number(pos[1]) - 1;
    const y = Number(pos[2]) - 1;
    const n = Number(val[1]);
    if (n > board[y][x]) board[y][x] = n;
  }
  const scoreText = (document.querySelector('.score-container')?.innerText || '0').split('\\n')[0];
  const message = document.querySelector('.game-message');
  const cells = [0,1,2,3].map(x => [0,1,2,3].map(y => {
    const value = board[y][x];
    return value ? {position: {x, y}, value} : null;
  }));
  return {
    grid: { cells },
    score: parseInt(scoreText, 10) || 0,
    over: !!message?.classList.contains('game-over'),
    won: !!message?.classList.contains('game-won'),
  };
}"""


def board_from_state(state: dict[str, Any]) -> Board:
    board = empty_board()
    cells = (state.get("grid") or {}).get("cells") or []
    # Classic 2048 stores cells[x][y] (column-major).
    for x, column in enumerate(cells):
        if not isinstance(column, list):
            continue
        for y, cell in enumerate(column):
            if not cell:
                continue
            if isinstance(cell, dict):
                value = int(cell.get("value") or 0)
            else:
                value = int(cell)
            if 0 <= y < 4 and 0 <= x < 4 and value:
                board[y][x] = value
    return board


def _dismiss_overlays(page) -> None:
    selectors = [
        "#ez-cookie-dialog-wrapper button",
        "#ez-accept-all",
        "button:has-text('Accept')",
        "button:has-text('I Agree')",
        "button:has-text('Got it')",
        ".cookie-notice a",
        ".close",
    ]
    for selector in selectors:
        try:
            loc = page.locator(selector).first
            if loc.count() and loc.is_visible():
                loc.click(timeout=800)
                time.sleep(0.2)
        except Exception:
            continue


class Web2048:
    def __init__(self, page):
        self.page = page

    @classmethod
    def launch(
        cls,
        *,
        headless: bool = False,
        url: str = CLASSIC_URL,
        video_dir: str | None = None,
        viewport: dict[str, int] | None = None,
        window_position: str = "40,40",
        window_size: str = "1440,900",
    ) -> tuple[Any, Any, Any, "Web2048"]:
        viewport = viewport or {"width": 1440, "height": 900}
        playwright = sync_playwright().start()
        browser = playwright.chromium.launch(
            headless=headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                f"--window-position={window_position}",
                f"--window-size={window_size}",
            ],
        )
        context_kwargs: dict[str, Any] = {"viewport": viewport}
        if video_dir:
            context_kwargs["record_video_dir"] = video_dir
            context_kwargs["record_video_size"] = viewport
        context = browser.new_context(**context_kwargs)
        page = context.new_page()
        cls._open_game(page, url)
        return playwright, browser, context, cls(page)

    @staticmethod
    def _open_game(page, url: str) -> None:
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(800)
        _dismiss_overlays(page)
        if "play2048.co" in page.url and "classic" not in page.url:
            try:
                page.get_by_text("Go to the old 2048").click(timeout=3000)
                page.wait_for_timeout(1000)
            except PlaywrightTimeout:
                page.goto(CLASSIC_URL, wait_until="domcontentloaded")
        _dismiss_overlays(page)
        try:
            page.locator(".restart-button").first.click(timeout=2000)
        except Exception:
            pass
        page.wait_for_timeout(400)
        page.locator("body").click(position={"x": 10, "y": 10}, timeout=2000)

    def read(self) -> dict[str, Any]:
        state = self.page.evaluate(READ_STATE_JS)
        if isinstance(state, str):
            state = json.loads(state)
        return state

    def swipe(self, direction: Direction) -> None:
        self.page.keyboard.press(KEYS[direction])
        self.page.wait_for_timeout(320)

    def install_hud(self) -> None:
        self.page.evaluate(
            """() => {
              if (document.getElementById('jev-hud')) return;
              const css = document.createElement('style');
              css.textContent = `
                #jev-hud {
                  position: fixed; left: 18px; top: 72px; z-index: 99999;
                  width: 340px; padding: 18px 18px 16px;
                  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
                  font-size: 13px; line-height: 1.45; color: #e8e6e3;
                  background: #111; border: 1px solid #3a3a3a; border-radius: 12px;
                  box-shadow: 0 18px 50px rgba(0,0,0,.35);
                }
                #jev-hud h1 { font-size: 13px; letter-spacing: .12em; margin: 0 0 10px;
                  color: #9be7c4; text-transform: uppercase; }
                #jev-hud .meta { color: #b9b6b1; margin-bottom: 10px; }
                #jev-hud .row { white-space: pre; }
                #jev-hud .pick { color: #fff; font-weight: 700; }
                #jev-hud .dim { color: #8b8883; }
                .container { margin-left: 360px !important; }
              `;
              document.head.appendChild(css);
              const hud = document.createElement('div');
              hud.id = 'jev-hud';
              hud.innerHTML = '<h1>Jev · System One</h1><div id="jev-hud-body" class="dim">waiting…</div>';
              document.body.appendChild(hud);
            }"""
        )

    def update_hud(self, body: str) -> None:
        self.page.evaluate(
            """(text) => {
              const el = document.getElementById('jev-hud-body');
              if (el) el.textContent = text;
            }""",
            body,
        )

    def screenshot(self, path: str) -> None:
        self.page.screenshot(path=path, full_page=False)

    def snapshot(self) -> tuple[Board, int, bool, bool]:
        state = self.read()
        board = board_from_state(state)
        score = int(state.get("score") or 0)
        over = bool(state.get("over"))
        won = bool(state.get("won"))
        return board, score, over, won
