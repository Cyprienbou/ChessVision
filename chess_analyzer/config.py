# config.py — Central configuration for ChessVision analyzer

import os

# ── Stockfish ────────────────────────────────────────────────────────────────
def _find_stockfish() -> str:
    """Auto-detect Stockfish on Intel (/usr/local) and Apple Silicon (/opt/homebrew)."""
    import shutil
    env = os.environ.get("STOCKFISH_PATH")
    if env:
        return env
    for candidate in ("/opt/homebrew/bin/stockfish", "/usr/local/bin/stockfish"):
        if os.path.isfile(candidate):
            return candidate
    found = shutil.which("stockfish")
    return found or "/usr/local/bin/stockfish"

STOCKFISH_PATH = _find_stockfish()

# ── Chess.com username (can be overridden via CLI --username) ────────────────
USERNAME = ""

# ── Error classification thresholds (centipawns) ────────────────────────────
BLUNDER_THRESHOLD    = 150   # cp loss >= 150  → blunder
MISTAKE_THRESHOLD    = 80    # cp loss >= 80   → mistake
INACCURACY_THRESHOLD = 40    # cp loss >= 40   → inaccuracy

# ── Stockfish search depth ───────────────────────────────────────────────────
ANALYSIS_DEPTH = 15

# ── Winning / strong advantage thresholds (centipawns) ──────────────────────
WINNING_ADVANTAGE_THRESHOLD = 100   # ≈ +1 pawn
STRONG_ADVANTAGE_THRESHOLD  = 200   # ≈ +2 pawns

# ── Sharp evaluation drop (single-move drop that flags a position) ───────────
SHARP_DROP_THRESHOLD = 150   # same as BLUNDER_THRESHOLD

# ── Time pressure: blunders made with less than this many seconds left ───────
TIME_PRESSURE_SECONDS = 30

# ── Minimum games per opening to be included in opening report ───────────────
MIN_GAMES_PER_OPENING = 1

# ── Output paths ─────────────────────────────────────────────────────────────
OUTPUT_DIR       = os.path.join(os.path.dirname(__file__), "output")
GAMES_DIR        = os.path.join(OUTPUT_DIR, "games")
DASHBOARD_PATH   = os.path.join(OUTPUT_DIR, "dashboard.html")
PGN_OUTPUT_PATH  = os.path.join(OUTPUT_DIR, "mes_parties.pgn")

# ── Analysis cache ────────────────────────────────────────────────────────────
# Increment CACHE_VERSION whenever the analysis logic changes to auto-invalidate.
CACHE_PATH    = os.path.join(OUTPUT_DIR, "analysis_cache.pkl")
CACHE_VERSION = "v3"   # bump when tactic taxonomy or scoring logic changes
