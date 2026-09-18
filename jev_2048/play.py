from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from jev_2048.agent import JevBlockedError, decide_heuristic, decide_jev
from jev_2048.game import Game
from jev_2048.render import RESET, hud_text, render


def _load_env() -> None:
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env")


def _decide(game: Game, use_jev: bool) -> tuple[object, bool]:
    if not use_jev:
        return decide_heuristic(game), False
    try:
        return decide_jev(game), True
    except JevBlockedError as exc:
        print(f"\nJev is not available: {exc}", flush=True)
        print(
            "Falling back to local heuristic. "
            "Re-run without --demo once TYPESAFE_API_KEY is set.\n",
            flush=True,
        )
        return decide_heuristic(game), False


def _finish(game: Game, decision, total_tokens: int, *, no_clear: bool) -> None:
    if not no_clear:
        sys.stdout.write("\033[H\033[2J")
    sys.stdout.write(render(game, decision, total_tokens) + "\n")
    if game.won:
        print(f"Reached 2048. score={game.score} moves={game.moves}")
    elif game.over():
        print(f"Game over. score={game.score} highest={game.highest} moves={game.moves}")
    else:
        print(f"Stopped at {game.moves} moves. score={game.score} highest={game.highest}")
    print(f"Jev input tokens this run: {total_tokens}  (~${total_tokens * 0.042 / 1_000_000:.6f})")
    print(RESET, end="")


def play_terminal(args) -> int:
    import random

    game = Game(rng=random.Random(args.seed))
    game.start()
    total_tokens = 0
    decision = None
    use_jev = not args.demo
    print("Starting in-process 2048. Ctrl+C to stop.\n", flush=True)
    print("Driver: TypeSafe Jev" if use_jev else "Driver: local heuristic (--demo)", flush=True)
    try:
        while game.moves < args.max_moves and not game.over():
            decision, use_jev = _decide(game, use_jev)
            total_tokens += decision.usage_input
            if not args.no_clear:
                sys.stdout.write("\033[H\033[2J")
            sys.stdout.write(render(game, decision, total_tokens) + "\n")
            sys.stdout.flush()
            time.sleep(max(args.delay, 0))
            if not game.step(decision.move):
                fallback = decide_heuristic(game)
                if not game.step(fallback.move):
                    break
    except KeyboardInterrupt:
        print("\nStopped.")
    _finish(game, decision, total_tokens, no_clear=args.no_clear)
    return 0


def play_web(args) -> int:
    from jev_2048.web import CLASSIC_URL, Web2048

    shots = Path(__file__).resolve().parents[1] / "shots"
    shots.mkdir(exist_ok=True)
    w, h = (int(x) for x in args.window_size.split(","))
    video_dir = str(shots) if args.record else None

    print("Opening official classic 2048 in a browser.", flush=True)
    print(f"URL: {CLASSIC_URL}", flush=True)

    playwright, browser, context, web = Web2048.launch(
        headless=args.headless,
        url=CLASSIC_URL,
        video_dir=video_dir,
        viewport={"width": w, "height": h},
        window_position=args.window_position,
        window_size=args.window_size,
    )
    game = Game()
    total_tokens = 0
    decision = None
    use_jev = not args.demo
    stalled = 0
    attempt = 1
    started = time.time()
    try:
        if not args.no_hud:
            web.install_hud()
        board, score, over, won = web.snapshot()
        game.hydrate(board, score, won)
        print("Driver: TypeSafe Jev" if use_jev else "Driver: local heuristic (--demo)", flush=True)
        print("Watch the browser + this terminal. Ctrl+C to stop.\n", flush=True)

        while game.moves < args.max_moves:
            if args.seconds and (time.time() - started) >= args.seconds:
                break
            if won or game.highest >= 2048:
                game.won = True
                if not args.no_hud:
                    web.update_hud(hud_text(game, decision, total_tokens) + "\n\nREACHED 2048")
                web.screenshot(str(shots / "jev-2048-win.png"))
                break
            if over or game.over():
                web.screenshot(str(shots / f"attempt-{attempt}-over.png"))
                if attempt >= args.retries:
                    break
                attempt += 1
                print(f"\nGame over at {game.highest}. Restarting attempt {attempt}…\n", flush=True)
                try:
                    web.page.locator(".retry-button").first.click(timeout=2000)
                except Exception:
                    web.page.locator(".restart-button").first.click(timeout=2000)
                web.page.wait_for_timeout(400)
                game = Game()
                stalled = 0
                board, score, over, won = web.snapshot()
                game.hydrate(board, score, won)
                if not args.no_hud:
                    web.install_hud()
                continue

            decision, use_jev = _decide(game, use_jev)
            total_tokens += decision.usage_input
            if not args.no_clear:
                sys.stdout.write("\033[H\033[2J")
            sys.stdout.write(render(game, decision, total_tokens) + "\n")
            sys.stdout.flush()
            if not args.no_hud:
                web.update_hud(hud_text(game, decision, total_tokens))
            time.sleep(max(args.delay, 0))

            before = [row[:] for row in game.board]
            web.swipe(decision.move)
            board, score, over, won = web.snapshot()
            if board == before:
                stalled += 1
                fallback = decide_heuristic(game)
                if fallback.move != decision.move:
                    web.swipe(fallback.move)
                    board, score, over, won = web.snapshot()
                if board == before:
                    if stalled >= 3:
                        over = True
                        continue
                    continue
            stalled = 0
            game.hydrate(board, score, won)
            game.moves += 1
            game.last_move = decision.move
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        try:
            web.screenshot(str(shots / "jev-2048-final.png"))
        except Exception:
            pass
        video_path = None
        try:
            video_path = web.page.video.path() if web.page.video else None
        except Exception:
            video_path = None
        _finish(game, decision, total_tokens, no_clear=True)
        for closer in (web.page.close, context.close, browser.close, playwright.stop):
            try:
                closer()
            except Exception:
                pass
        if args.record:
            _export_mp4(shots, video_path)
    return 0


def _export_mp4(shots: Path, video_path: str | None) -> None:
    if not video_path:
        raw = sorted(shots.glob("*.webm"), key=lambda p: p.stat().st_mtime)
        video_path = str(raw[-1]) if raw else None
    if not video_path:
        print("No video file was written.", flush=True)
        return
    dest_mp4 = shots / "jev-2048.mp4"
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(dest_mp4),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        print(f"Video: {dest_mp4}", flush=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(f"Could not convert video ({exc}). Raw file: {video_path}", flush=True)


def main(argv: list[str] | None = None) -> int:
    _load_env()
    parser = argparse.ArgumentParser(description="Watch TypeSafe Jev play 2048 in a real browser")
    parser.add_argument("--delay", type=float, default=0.08, help="seconds to show a pick before swiping")
    parser.add_argument("--max-moves", type=int, default=5000, help="safety cap per attempt")
    parser.add_argument("--retries", type=int, default=12, help="restart after game over")
    parser.add_argument("--seed", type=int, default=None, help="only used with --terminal")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="play with a local heuristic instead of Jev (no API key needed)",
    )
    parser.add_argument("--no-clear", action="store_true", help="do not clear the terminal")
    parser.add_argument(
        "--terminal",
        action="store_true",
        help="play an in-process board instead of classic.play2048.co",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="run Chromium headless (default is a visible window)",
    )
    parser.add_argument("--seconds", type=float, default=0, help="stop after N seconds (0 = only max-moves)")
    parser.add_argument("--no-hud", action="store_true", help="do not overlay the decision HUD on the game")
    parser.add_argument("--record", action="store_true", help="record a Playwright video into shots/")
    parser.add_argument("--window-position", default="40,40", help="browser x,y")
    parser.add_argument("--window-size", default="1440,900", help="browser width,height")
    args = parser.parse_args(argv)
    if args.terminal:
        return play_terminal(args)
    return play_web(args)


if __name__ == "__main__":
    raise SystemExit(main())
