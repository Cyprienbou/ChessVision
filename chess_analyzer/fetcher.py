from __future__ import annotations
# fetcher.py — Fetch games from Chess.com API or a local PGN file.
#
# Public API
# ----------
# fetch_from_chesscom(username, limit=None, category=None) -> str   (PGN text)
# fetch_from_pgn(path)                                              -> str   (PGN text)
# save_pgn(pgn_text, path)
# classify_time_control(time_control_str)                           -> str

import re
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import config

# Max concurrent HTTP requests to Chess.com archives.
# 4 threads = ~4x speedup on the fetch phase without overloading the API.
_FETCH_WORKERS = 4


# ── Time-control classification ──────────────────────────────────────────────

_TC_LABELS = {
    "bullet":    ("Bullet",    lambda secs: secs < 180),
    "blitz":     ("Blitz",     lambda secs: 180 <= secs < 600),
    "rapid":     ("Rapid",     lambda secs: 600 <= secs < 1800),
    "classical": ("Classical", lambda secs: secs >= 1800),
}


def classify_time_control(tc_str: str) -> str:
    """
    Convert a PGN TimeControl tag (e.g. '300+0', '600+5', '1/40') to one of
    Bullet / Blitz / Rapid / Classical.  Returns 'Unknown' if unparseable.
    """
    if not tc_str or tc_str == "-":
        return "Unknown"

    # Handle 'X+Y' format (base seconds + increment)
    m = re.match(r"^(\d+)(?:\+(\d+))?$", tc_str.strip())
    if m:
        base = int(m.group(1))
        inc  = int(m.group(2) or 0)
        # Approximate total time for 40 moves as a rough classifier
        effective = base + inc * 40
        if effective < 180:
            return "Bullet"
        elif effective < 600:
            return "Blitz"
        elif effective < 1800:
            return "Rapid"
        else:
            return "Classical"

    # Handle '1/40' daily-chess style
    if "/" in tc_str:
        return "Classical"

    return "Unknown"


# ── Chess.com fetcher ────────────────────────────────────────────────────────

_HEADERS = {
    "User-Agent": "ChessVision/1.0 (github.com/chessvision; educational project)"
}


def _get_archive_urls(username: str) -> list[str]:
    """Return all monthly archive URLs for the given username."""
    url = f"https://api.chess.com/pub/player/{username}/games/archives"
    resp = requests.get(url, headers=_HEADERS, timeout=15)
    resp.raise_for_status()
    return resp.json().get("archives", [])


def _fetch_month(url: str) -> list[dict]:
    """Fetch a single monthly archive and return its list of game dicts."""
    resp = requests.get(url, headers=_HEADERS, timeout=15)
    resp.raise_for_status()
    return resp.json().get("games", [])


def fetch_from_chesscom(
    username: str,
    limit: int | None = None,
    category: str | None = None,
) -> str:
    """
    Download games for *username* from Chess.com.

    Parameters
    ----------
    username : str
    limit    : int | None   – keep only the N most recent games (after filtering)
    category : str | None   – filter to 'bullet'|'blitz'|'rapid'|'classical'

    Returns
    -------
    str  Combined PGN text of all matched games (newest-first order).
    """
    print(f"[fetcher] Fetching archive list for '{username}' …")
    archive_urls = _get_archive_urls(username)

    if not archive_urls:
        raise ValueError(f"No archives found for user '{username}'.")

    # Work newest-first
    archive_urls = list(reversed(archive_urls))
    category_filter = category.lower() if category else None

    # Estimate how many months we need to cover `limit` games.
    # We fetch in batches of _FETCH_WORKERS months concurrently, then check
    # if we have enough games. This avoids fetching the entire history.
    collected_pgns: list[str] = []
    month_idx  = 0
    n_archives = len(archive_urls)

    while month_idx < n_archives:
        batch_urls = archive_urls[month_idx : month_idx + _FETCH_WORKERS]
        month_idx += len(batch_urls)

        print(f"  Fetching {len(batch_urls)} month(s) in parallel "
              f"[{month_idx}/{n_archives}] …")

        # Fetch concurrently; preserve original order (newest first = batch order)
        batch_results: dict[str, list] = {}
        with ThreadPoolExecutor(max_workers=_FETCH_WORKERS) as pool:
            futures = {pool.submit(_fetch_month, url): url for url in batch_urls}
            for future in as_completed(futures):
                url = futures[future]
                try:
                    batch_results[url] = future.result()
                except Exception as exc:
                    print(f"    Warning: could not fetch {url} — {exc}")
                    batch_results[url] = []

        # Merge in newest-first order (batch_urls preserves that order)
        for url in batch_urls:
            games = batch_results.get(url, [])
            for game in reversed(games):   # newest in month first
                tc_str = game.get("time_control", "")
                tc     = classify_time_control(tc_str)

                if category_filter and tc.lower() != category_filter:
                    continue

                pgn = game.get("pgn", "").strip()
                if pgn:
                    collected_pgns.append(pgn)

                if limit and len(collected_pgns) >= limit:
                    break

            if limit and len(collected_pgns) >= limit:
                break

        if limit and len(collected_pgns) >= limit:
            break

    print(f"[fetcher] Collected {len(collected_pgns)} game(s).")
    return "\n\n".join(collected_pgns)


# ── Local PGN fetcher ────────────────────────────────────────────────────────

def fetch_from_pgn(path: str, limit: int | None = None, category: str | None = None) -> str:
    """
    Read a local .pgn file and return its text, optionally filtered by
    time control category and limited to N games.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"PGN file not found: {path}")

    raw = p.read_text(encoding="utf-8", errors="replace")

    if limit is None and category is None:
        return raw

    # Split individual games (each starts with '[Event ')
    import chess.pgn, io
    games_pgn: list[str] = []
    reader = io.StringIO(raw)
    category_filter = category.lower() if category else None

    while True:
        game = chess.pgn.read_game(reader)
        if game is None:
            break

        tc_str = game.headers.get("TimeControl", "")
        tc     = classify_time_control(tc_str)

        if category_filter and tc.lower() != category_filter:
            continue

        games_pgn.append(str(game))

        if limit and len(games_pgn) >= limit:
            break

    print(f"[fetcher] Loaded {len(games_pgn)} game(s) from {path}.")
    return "\n\n".join(games_pgn)


# ── PGN persistence ──────────────────────────────────────────────────────────

def save_pgn(pgn_text: str, path: str = config.PGN_OUTPUT_PATH) -> None:
    """Write PGN text to disk."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(pgn_text, encoding="utf-8")
    print(f"[fetcher] Saved PGN to {p}.")
