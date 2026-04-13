from __future__ import annotations
# parser.py — Parse PGN text into structured game records.
#
# Public API
# ----------
# parse_pgn(pgn_text, username) -> pd.DataFrame
#
# Each row in the DataFrame represents one game and contains:
#   game_id, date, white, black, white_elo, black_elo, result,
#   time_control, category, opening_name, eco, player_color,
#   moves (list[chess.Move]), board_states (list[chess.Board]),
#   clocks (list[float|None])  — remaining seconds per move, or None

import io
import re
import uuid
import logging

import chess
import chess.pgn
import pandas as pd

from fetcher import classify_time_control

logger = logging.getLogger(__name__)


# ── Clock comment parsing ─────────────────────────────────────────────────────

_CLK_RE = re.compile(r"\[%clk\s+(\d+):(\d+):(\d+(?:\.\d+)?)\]")


# ── Opening name extraction ───────────────────────────────────────────────────

def _extract_opening_name(headers: chess.pgn.Headers) -> str:
    """
    Extract a human-readable opening name from PGN headers.

    Priority:
    1. 'Opening' header (standard PGN, rarely present in Chess.com exports)
    2. 'ECOUrl' header (Chess.com specific) — e.g.
       https://www.chess.com/openings/Modern-Defense-with-1-d4-2.Bf4-Bg7-3.e3
       → "Modern Defense"
    3. Fall back to "Unknown opening"
    """
    # Standard Opening header
    opening = headers.get("Opening", "")
    if opening and opening not in ("?", "-"):
        return opening

    # Chess.com ECOUrl: extract the opening name before the move notation
    eco_url = headers.get("ECOUrl", "")
    if eco_url:
        # Grab path component after last slash
        slug = eco_url.rstrip("/").split("/")[-1]   # e.g. "Modern-Defense-with-1-d4-2.Bf4-Bg7-3.e3"
        # Split on '-', collect words until we hit a move token.
        # A move token looks like:  1  2  Nf3  Bg7  d4  exd5  Bxf7  O-O
        # We require piece moves to end with a rank digit (e.g. "Nf3", not "Kann").
        # Pawn moves must be exactly 2 chars: file + rank (e.g. "d4", "e5").
        _move_token = re.compile(
            r"^\d"                   # move number
            r"|^[KQRBN][a-h][1-8]"  # piece move: Nf3, Bg5, Ka1 (NOT "Kann")
            r"|^[KQRBN]x"           # capture: Nxd5
            r"|^[a-h][1-8]$"        # pawn move exactly 2 chars: d4
            r"|^[a-h]x"             # pawn capture: exd5
            r"|^O-O"                # castling
        )
        parts = slug.split("-")
        name_parts = []
        for part in parts:
            if part.lower() == "with":
                break   # "with" signals the start of move notation
            if _move_token.match(part):
                break
            name_parts.append(part)
        if name_parts:
            return " ".join(name_parts)

    return "Unknown opening"


def _parse_termination(headers: chess.pgn.Headers, result: str) -> str:
    """Normalise PGN Termination header → checkmate / resignation / timeout / draw / unknown."""
    term = headers.get("Termination", "").lower()
    if "checkmate" in term:
        return "checkmate"
    if "resignation" in term or "resigned" in term:
        return "resignation"
    if "time" in term:
        return "timeout"
    if any(w in term for w in ("draw", "stalemate", "repetition", "insufficient", "agreement")):
        return "draw"
    if result == "1/2-1/2":
        return "draw"
    return "unknown"


def _parse_clock_comment(comment: str) -> float | None:
    """Extract remaining seconds from a '%clk H:MM:SS' comment, or None."""
    m = _CLK_RE.search(comment)
    if not m:
        return None
    h, mins, secs = m.group(1), m.group(2), m.group(3)
    return int(h) * 3600 + int(mins) * 60 + float(secs)


# ── Per-game extraction ───────────────────────────────────────────────────────

def _extract_game(game: chess.pgn.Game, username: str) -> dict | None:
    """
    Convert a chess.pgn.Game object into a flat dict suitable for a DataFrame row.
    Returns None if the game is malformed.
    """
    headers = game.headers

    white = headers.get("White", "?")
    black = headers.get("Black", "?")

    # Determine which side the target player is on
    uname_lower = username.lower()
    if white.lower() == uname_lower:
        player_color = "white"
    elif black.lower() == uname_lower:
        player_color = "black"
    else:
        # Include the game anyway; mark as 'unknown'
        player_color = "unknown"

    # Walk the mainline collecting moves, boards, and clock comments
    board  = game.board()
    moves: list[chess.Move]  = []
    boards: list[chess.Board] = []
    clocks: list[float | None] = []
    has_clock_data = False

    try:
        node = game
        while node.variations:
            next_node = node.variations[0]
            move      = next_node.move

            # Record board BEFORE the move (position the engine will evaluate)
            boards.append(board.copy())

            clock_val = _parse_clock_comment(next_node.comment)
            if clock_val is not None:
                has_clock_data = True
            clocks.append(clock_val)

            board.push(move)
            moves.append(move)
            node = next_node
    except Exception as exc:
        logger.warning("Error walking game moves: %s", exc)
        return None

    if not moves:
        return None

    # Parse Elo ratings
    def _elo(s: str) -> int | None:
        try:
            return int(s)
        except (ValueError, TypeError):
            return None

    tc_str   = headers.get("TimeControl", "")
    category = classify_time_control(tc_str)

    # Stable game ID: prefer chess.com numeric ID from [Link] header,
    # fall back to a content-based hash so the cache survives re-parses.
    link = headers.get("Link", "") or headers.get("Site", "")
    import re as _re, hashlib as _hl
    _m = _re.search(r"/game/(?:live|daily)/(\d+)", link)
    if _m:
        _game_id = _m.group(1)[:12]
    else:
        _seed = f"{headers.get('Date','')}{white}{black}{headers.get('Result','')}{tc_str}"
        _game_id = _hl.md5(_seed.encode()).hexdigest()[:8]

    return {
        # Unique identifier for this game (used as filename key + cache key)
        "game_id":       _game_id,
        "date":          headers.get("Date", "?"),
        "white":         white,
        "black":         black,
        "white_elo":     _elo(headers.get("WhiteElo")),
        "black_elo":     _elo(headers.get("BlackElo")),
        "result":        headers.get("Result", "?"),
        "time_control":  tc_str,
        "category":      category,
        # Opening info will be filled in by openings.py
        "opening_name":  _extract_opening_name(headers),
        "eco":           headers.get("ECO", "?"),
        "eco_url":       headers.get("ECOUrl", ""),
        "player_color":  player_color,
        # Move-level data (lists)
        "moves":         moves,
        "board_states":  boards,
        "clocks":        clocks if has_clock_data else [None] * len(moves),
        "has_clock_data": has_clock_data,
        # Keep raw game object in case reporter needs it for move text
        "_game_obj":     game,
        "termination":   _parse_termination(headers, headers.get("Result", "?")),
    }


# ── Public entry point ────────────────────────────────────────────────────────

def parse_pgn(pgn_text: str, username: str) -> pd.DataFrame:
    """
    Parse a multi-game PGN string and return a DataFrame with one row per game.

    Parameters
    ----------
    pgn_text : str     — raw PGN content (may contain multiple games)
    username : str     — the Chess.com username being analysed

    Returns
    -------
    pd.DataFrame
    """
    reader     = io.StringIO(pgn_text)
    records    = []
    skipped    = 0
    game_index = 0

    while True:
        try:
            game = chess.pgn.read_game(reader)
        except Exception as exc:
            logger.warning("Skipping malformed PGN entry: %s", exc)
            skipped += 1
            continue

        if game is None:
            break   # end of stream

        game_index += 1
        record = _extract_game(game, username)
        if record is None:
            logger.warning("Skipping game %d (no valid moves).", game_index)
            skipped += 1
            continue

        # Give each game a stable sequential ID
        record["game_index"] = game_index
        records.append(record)

    if skipped:
        logger.warning("Skipped %d malformed/empty game(s).", skipped)

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)
    print(f"[parser] Parsed {len(df)} game(s) ({skipped} skipped).")
    return df
