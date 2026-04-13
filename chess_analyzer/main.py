#!/usr/bin/env python3
# main.py — CLI entry point for ChessVision.
#
# Usage examples
# --------------
# Fetch from Chess.com and analyse all games:
#   python main.py --username magnuscarlsen
#
# Fetch last 20 blitz games:
#   python main.py --username magnuscarlsen --limit 20 --category blitz
#
# Analyse a local PGN file:
#   python main.py --pgn my_games.pgn
#
# Analyse a local PGN, only rapid, first 50 games:
#   python main.py --pgn my_games.pgn --limit 50 --category rapid

import argparse
import subprocess
import sys
import webbrowser
from pathlib import Path

import config
import fetcher
import pgn_parser as parser
import openings
import analyzer
import reporter


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="chessvision",
        description="Analyse Chess.com games and generate an interactive HTML dashboard.",
    )
    source = p.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--username", "-u",
        metavar="NAME",
        help="Chess.com username to fetch games for.",
    )
    source.add_argument(
        "--pgn", "-p",
        metavar="FILE",
        help="Path to a local .pgn file to analyse.",
    )
    p.add_argument(
        "--player",
        metavar="NAME",
        help="Player username for perspective when using --pgn (default: derived from filename).",
    )
    p.add_argument(
        "--limit", "-n",
        type=int,
        default=None,
        metavar="N",
        help="Analyse only the N most recent games (default: all).",
    )
    p.add_argument(
        "--category", "-c",
        choices=["bullet", "blitz", "rapid", "classical"],
        default=None,
        metavar="TC",
        help="Filter by time control: bullet | blitz | rapid | classical.",
    )
    p.add_argument(
        "--no-cache",
        action="store_true",
        default=False,
        help="Ignore cached Stockfish results and re-analyse every game from scratch.",
    )
    p.add_argument(
        "--depth",
        type=int,
        default=None,
        metavar="D",
        help=f"Stockfish analysis depth (default: {config.ANALYSIS_DEPTH}). "
             "Lower values (e.g. 12) are significantly faster for large datasets.",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()

    # ── Determine username ────────────────────────────────────────────────────
    username: str
    if args.username:
        username = args.username
    else:
        # For local PGN mode: prefer --player, then config.USERNAME, then filename stem.
        pgn_stem = Path(args.pgn).stem
        username = getattr(args, "player", None) or config.USERNAME or pgn_stem or "player"
        print(f"[main] PGN mode — using username '{username}' for perspective.")

    # ── Apply optional depth override ────────────────────────────────────────
    if args.depth:
        config.ANALYSIS_DEPTH = args.depth

    # ── Stockfish check ───────────────────────────────────────────────────────
    if not analyzer.check_stockfish():
        sys.exit(1)

    # ── Step 1: Fetch / load PGN ──────────────────────────────────────────────
    print("\n── Step 1/4: Fetching games ─────────────────────────────────────")
    if args.username:
        pgn_text = fetcher.fetch_from_chesscom(
            username=username,
            limit=args.limit,
            category=args.category,
        )
    else:
        pgn_text = fetcher.fetch_from_pgn(
            path=args.pgn,
            limit=args.limit,
            category=args.category,
        )

    if not pgn_text.strip():
        print("[main] No games fetched. Exiting.")
        sys.exit(1)

    # Save combined PGN to disk
    fetcher.save_pgn(pgn_text)

    # ── Step 2: Parse PGN ─────────────────────────────────────────────────────
    print("\n── Step 2/4: Parsing PGN ────────────────────────────────────────")
    df = parser.parse_pgn(pgn_text, username)

    if df.empty:
        print("[main] No valid games after parsing. Exiting.")
        sys.exit(1)

    # ── Step 3: Enrich with opening data ──────────────────────────────────────
    print("\n── Step 3/4: Recognising openings ───────────────────────────────")
    df = openings.enrich_openings(df)

    # ── Step 4: Stockfish analysis ────────────────────────────────────────────
    print("\n── Step 4/4: Running Stockfish analysis ─────────────────────────")
    df = analyzer.enrich_analysis(df, username, no_cache=args.no_cache)

    # ── Aggregate opening statistics ──────────────────────────────────────────
    opening_df = openings.opening_stats(df)
    print(
        f"[main] Opening stats computed for "
        f"{len(opening_df)} opening(s) with ≥{config.MIN_GAMES_PER_OPENING} games."
    )

    # ── Generate HTML reports ─────────────────────────────────────────────────
    reporter.generate_reports(df, opening_df, username)

    # ── Summary ───────────────────────────────────────────────────────────────
    total    = len(df)
    avg_acc  = df["accuracy"].mean() if "accuracy" in df.columns and df["accuracy"].notna().any() else None
    blunders = (
        df["errors"]
        .apply(lambda errs: sum(1 for e in (errs or []) if e["classification"] == "blunder"))
        .sum()
        if "errors" in df.columns else 0
    )

    print("\n" + "═" * 60)
    print(f"  ChessVision — Analysis complete for '{username}'")
    print(f"  Games analysed : {total}")
    print(f"  Avg accuracy   : {avg_acc:.1f}%" if avg_acc is not None else "  Avg accuracy   : N/A")
    print(f"  Total blunders : {blunders}")
    print(f"  Dashboard      : {config.DASHBOARD_PATH}")
    print("═" * 60 + "\n")

    # ── Open dashboard in default browser ─────────────────────────────────────
    dashboard_url = Path(config.DASHBOARD_PATH).resolve().as_uri()
    print(f"[main] Opening dashboard in browser: {dashboard_url}")
    webbrowser.open(dashboard_url)


if __name__ == "__main__":
    main()
