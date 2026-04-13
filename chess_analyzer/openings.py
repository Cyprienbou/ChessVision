# openings.py — ECO opening recognition and theory-depth tracking.
#
# Public API
# ----------
# enrich_openings(df, username) -> pd.DataFrame
#   Adds columns: eco, opening_name, opening_variation, theory_depth
#   (theory_depth = move number where player first left book)
#
# opening_stats(df) -> pd.DataFrame
#   Aggregate per-opening statistics (min MIN_GAMES_PER_OPENING games).

import chess
import chess.pgn
import chess.polyglot   # used for Zobrist hashing, not actually polyglot here
import pandas as pd

import config

# python-chess ships a built-in ECO database accessible via chess.pgn
# We use the opening names embedded in PGN headers as primary source, and
# supplement with a lightweight prefix-match against the standard ECO lines
# that python-chess exposes through chess.polyglot or the ECO CSV included
# in some builds.  For maximum portability we use a curated ECO dict below.

# ── Minimal ECO prefix table ──────────────────────────────────────────────────
# Format: { move_sequence_uci_space_separated: (eco, name, variation) }
# This covers the most common openings at the 1200-1600 level.
# Extended automatically from PGN headers when available.

_ECO_TABLE: dict[str, tuple[str, str, str]] = {
    # King's Pawn
    "e2e4":                                          ("B00", "King's Pawn Game", ""),
    "e2e4 e7e5":                                     ("C20", "Open Game", ""),
    "e2e4 e7e5 g1f3":                                ("C40", "King's Knight Opening", ""),
    "e2e4 e7e5 g1f3 b8c6":                           ("C44", "King's Pawn Game", ""),
    "e2e4 e7e5 g1f3 b8c6 f1b5":                      ("C60", "Ruy Lopez", ""),
    "e2e4 e7e5 g1f3 b8c6 f1b5 a7a6":                 ("C65", "Ruy Lopez", "Morphy Defence"),
    "e2e4 e7e5 g1f3 b8c6 f1c4":                      ("C50", "Italian Game", ""),
    "e2e4 e7e5 g1f3 b8c6 f1c4 f8c5":                 ("C50", "Italian Game", "Giuoco Piano"),
    "e2e4 e7e5 g1f3 b8c6 f1c4 g8f6":                 ("C55", "Italian Game", "Two Knights"),
    "e2e4 e7e5 g1f3 b8c6 d2d4":                      ("C44", "Scotch Game", ""),
    "e2e4 e7e5 g1f3 b8c6 d2d4 e5d4":                 ("C44", "Scotch Game", ""),
    "e2e4 e7e5 f2f4":                                ("C30", "King's Gambit", ""),
    "e2e4 e7e5 f2f4 e5f4":                           ("C33", "King's Gambit Accepted", ""),
    "e2e4 c7c5":                                     ("B20", "Sicilian Defence", ""),
    "e2e4 c7c5 g1f3":                                ("B40", "Sicilian Defence", ""),
    "e2e4 c7c5 g1f3 d7d6":                           ("B50", "Sicilian Defence", ""),
    "e2e4 c7c5 g1f3 d7d6 d2d4 c5d4 f3d4 g8f6 b1c3": ("B54", "Sicilian Defence", "Dragon"),
    "e2e4 c7c5 g1f3 b8c6":                           ("B40", "Sicilian Defence", ""),
    "e2e4 c7c5 g1f3 e7e6":                           ("B40", "Sicilian Defence", ""),
    "e2e4 e7e6":                                     ("C00", "French Defence", ""),
    "e2e4 e7e6 d2d4":                                ("C02", "French Defence", ""),
    "e2e4 e7e6 d2d4 d7d5":                           ("C05", "French Defence", ""),
    "e2e4 c7c6":                                     ("B10", "Caro-Kann Defence", ""),
    "e2e4 c7c6 d2d4 d7d5":                           ("B13", "Caro-Kann Defence", ""),
    "e2e4 d7d5":                                     ("B01", "Scandinavian Defence", ""),
    "e2e4 d7d5 e4d5":                                ("B01", "Scandinavian Defence", ""),
    "e2e4 g8f6":                                     ("B02", "Alekhine's Defence", ""),
    # Queen's Pawn
    "d2d4":                                          ("A40", "Queen's Pawn Game", ""),
    "d2d4 d7d5":                                     ("D00", "Queen's Pawn Game", ""),
    "d2d4 d7d5 c2c4":                                ("D06", "Queen's Gambit", ""),
    "d2d4 d7d5 c2c4 e7e6":                           ("D30", "Queen's Gambit Declined", ""),
    "d2d4 d7d5 c2c4 d5c4":                           ("D20", "Queen's Gambit Accepted", ""),
    "d2d4 d7d5 c2c4 c7c6":                           ("D10", "Slav Defence", ""),
    "d2d4 g8f6":                                     ("A45", "Indian Defence", ""),
    "d2d4 g8f6 c2c4":                                ("A50", "Indian Defence", ""),
    "d2d4 g8f6 c2c4 g7g6":                           ("E60", "King's Indian Defence", ""),
    "d2d4 g8f6 c2c4 e7e6":                           ("A13", "English Opening", ""),
    "d2d4 g8f6 c2c4 e7e6 b1c3 f8b4":                 ("E40", "Nimzo-Indian Defence", ""),
    "d2d4 g8f6 c2c4 c7c5":                           ("A50", "Benoni Defence", ""),
    # English / Flank
    "c2c4":                                          ("A10", "English Opening", ""),
    "c2c4 e7e5":                                     ("A20", "English Opening", "King's English"),
    "g1f3":                                          ("A04", "Zukertort Opening", ""),
    "g1f3 d7d5 g2g3":                                ("A07", "King's Indian Attack", ""),
}


def _moves_to_uci_key(moves: list[chess.Move]) -> str:
    """Return a space-joined UCI string for a move list."""
    return " ".join(m.uci() for m in moves)


def _lookup_eco(moves: list[chess.Move]) -> tuple[str, str, str]:
    """
    Find the longest ECO prefix that matches the game's opening moves.
    Returns (eco_code, opening_name, variation).
    """
    key = _moves_to_uci_key(moves)
    best: tuple[str, str, str] = ("?", "Unknown opening", "")

    # Walk from longest possible prefix down to 1 move
    for n in range(min(len(moves), 12), 0, -1):
        prefix = _moves_to_uci_key(moves[:n])
        if prefix in _ECO_TABLE:
            best = _ECO_TABLE[prefix]
            break

    return best


def _theory_depth_from_eco_url(eco_url: str) -> int:
    """
    Parse the Chess.com ECOUrl to extract the number of full moves of known
    opening theory encoded in the URL.

    Examples
    --------
    .../Modern-Defense-with-1-d4-2.Bf4-Bg7-3.e3
        → move numbers 1,2,3 → depth = 3

    .../Caro-Kann-Defense-Exchange-Variation-3...cxd5
        → ends with 3...cxd5 → depth = 3

    .../Anderssen-Opening-1...d5
        → ends with 1...d5 → depth = 1

    .../Caro-Kann-Defense   (no moves)
        → depth = 0
    """
    import re
    if not eco_url:
        return 0

    slug = eco_url.rstrip("/").split("/")[-1]

    # Case 1: contains "-with-" followed by move notation
    if "-with-" in slug:
        move_section = slug.split("-with-", 1)[1]
        # Find all move numbers (digits followed by "." or "-")
        numbers = re.findall(r'(?<![a-zA-Z])(\d+)(?=[.\-])', move_section)
        return max((int(n) for n in numbers), default=0)

    # Case 2: ends with "N...move" (black's response only)
    m = re.search(r'(\d+)\.{3}', slug)
    if m:
        return int(m.group(1))

    # Case 3: ends with "N.move" (white's move, no black response listed)
    m = re.search(r'(\d+)\.(?!\.)', slug)
    if m:
        return int(m.group(1))

    return 0


# ── Public API ────────────────────────────────────────────────────────────────

def enrich_openings(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add / overwrite ECO columns for each game in *df*.

    Added columns
    -------------
    eco               : str
    opening_name      : str
    opening_variation : str
    theory_depth      : int   (number of player moves in known theory)
    """
    ecos, names, variations, depths = [], [], [], []

    for _, row in df.iterrows():
        moves        = row["moves"]
        player_color = row.get("player_color", "white")

        # If the PGN already carried ECO+Opening header values, use them for
        # name/variation but still compute theory_depth ourselves.
        pgn_eco  = row.get("eco", "?")
        pgn_name = row.get("opening_name", "")

        eco_code, eco_name, eco_var = _lookup_eco(moves)

        # Prefer PGN header values for display (they're more precise)
        final_eco  = pgn_eco  if pgn_eco  not in ("?", "", None) else eco_code
        final_name = pgn_name if pgn_name not in ("?", "", None, "Unknown opening") else eco_name

        # Use Chess.com ECOUrl for accurate theory depth (much more reliable
        # than our small ECO prefix table which only knows a handful of lines)
        eco_url = row.get("eco_url", "")
        depth   = _theory_depth_from_eco_url(eco_url)

        ecos.append(final_eco)
        names.append(final_name)
        variations.append(eco_var)
        depths.append(depth)

    df = df.copy()
    df["eco"]               = ecos
    df["opening_name"]      = names
    df["opening_variation"] = variations
    df["theory_depth"]      = depths
    return df


def opening_stats(df: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate per-opening statistics for openings with at least
    config.MIN_GAMES_PER_OPENING games.

    Requires columns produced by enrich_openings + analyzer.enrich_analysis:
      eco, opening_name, player_color, result, accuracy,
      first_error_move, errors (list of error dicts)

    Returns a DataFrame with one row per opening.
    """
    if df.empty:
        return pd.DataFrame()

    def _win(result: str, color: str) -> bool:
        if color == "white":
            return result == "1-0"
        if color == "black":
            return result == "0-1"
        return False

    rows = []
    grouped = df.groupby(["eco", "opening_name"])

    for (eco, name), grp in grouped:
        if len(grp) < config.MIN_GAMES_PER_OPENING:
            continue

        wins     = sum(_win(r, c) for r, c in zip(grp["result"], grp["player_color"]))
        win_rate = wins / len(grp)

        avg_acc = (
            grp["accuracy"].mean()
            if "accuracy" in grp.columns and grp["accuracy"].notna().any()
            else None
        )

        avg_theory = grp["theory_depth"].mean() if "theory_depth" in grp.columns else None

        # First error move per game (from analyzer output)
        first_errors = grp["first_error_move"].dropna() if "first_error_move" in grp.columns else pd.Series(dtype=float)
        avg_first_error = first_errors.mean() if not first_errors.empty else None

        # Most common missed tactic across all blunders in this opening
        tactic_counts: dict[str, int] = {}
        if "errors" in grp.columns:
            for errors in grp["errors"]:
                for e in (errors or []):
                    if e.get("classification") == "blunder":
                        t = e.get("tactic_type", "Other")
                        tactic_counts[t] = tactic_counts.get(t, 0) + 1

        most_missed = max(tactic_counts, key=tactic_counts.get) if tactic_counts else "N/A"

        rows.append({
            "eco":              eco,
            "opening_name":     name,
            "games_played":     len(grp),
            "win_rate":         win_rate,
            "avg_accuracy":     avg_acc,
            "avg_theory_depth": avg_theory,
            "avg_first_error":  avg_first_error,
            "most_missed_tactic": most_missed,
        })

    return pd.DataFrame(rows)
