from __future__ import annotations
# analyzer.py — Stockfish-powered game analysis.
#
# Public API
# ----------
# check_stockfish()          -> bool
# enrich_analysis(df, username) -> pd.DataFrame
#
# For each game row, adds:
#   evaluations      list[int]        centipawn eval after every move (from White's POV)
#   errors           list[dict]       one dict per classified error
#   accuracy         float            0-100 accuracy score for the player
#   first_error_move int | None       move number of first blunder/mistake
#   sharp_drops      list[dict]       positions with sudden eval collapse
#   winning_positions list[dict]      positions where player was winning (+1 or more)
#   conversion       str              "converted" | "drawn" | "lost" | "N/A"
#
# Error dict keys
# ---------------
#   move_number      int
#   phase            "opening" | "middlegame" | "endgame"
#   move_played_uci  str
#   move_played_san  str
#   best_move_uci    str
#   best_move_san    str
#   cp_loss          int     (always positive)
#   classification   "blunder" | "mistake" | "inaccuracy" | "good"
#   tactic_type      str     (for blunders only)
#   clock_remaining  float | None
#   time_pressure    bool
#   king_unsafe      bool

import os
import sys
import pickle
import logging

import chess
import chess.engine
import pandas as pd

import config

logger = logging.getLogger(__name__)


# ── Analysis cache ────────────────────────────────────────────────────────────
# Keyed by (CACHE_VERSION, game_id) so a version bump auto-invalidates old data.

_CACHE_SAVE_INTERVAL = 10   # flush to disk every N newly-analysed games

def _load_cache() -> dict:
    try:
        with open(config.CACHE_PATH, "rb") as f:
            return pickle.load(f)
    except Exception:
        return {}


def _save_cache(cache: dict) -> None:
    try:
        os.makedirs(os.path.dirname(config.CACHE_PATH), exist_ok=True)
        with open(config.CACHE_PATH, "wb") as f:
            pickle.dump(cache, f, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception as exc:
        logger.warning("Could not save analysis cache: %s", exc)


def _cache_key(game_id: str) -> tuple:
    return (config.CACHE_VERSION, game_id)


# ── Stockfish bootstrap ───────────────────────────────────────────────────────

def check_stockfish() -> bool:
    """Return True if Stockfish is accessible at config.STOCKFISH_PATH."""
    path = config.STOCKFISH_PATH
    if not os.path.isfile(path):
        print(f"Stockfish not found. Run: brew install stockfish")
        return False
    return True


def _open_engine() -> chess.engine.SimpleEngine:
    return chess.engine.SimpleEngine.popen_uci(config.STOCKFISH_PATH)


# ── Game-phase detection ──────────────────────────────────────────────────────

def _detect_phase(board: chess.Board, move_number: int) -> str:
    """
    Classify a position's game phase.
      Opening   : moves 1-15
      Endgame   : queens off board, or total pieces (excl. kings+pawns) <= 6
      Middlegame: everything else
    """
    if move_number <= 15:
        return "opening"

    queens      = board.pieces(chess.QUEEN, chess.WHITE) | board.pieces(chess.QUEEN, chess.BLACK)
    minor_heavy = (
        len(board.pieces(chess.ROOK,   chess.WHITE)) +
        len(board.pieces(chess.ROOK,   chess.BLACK)) +
        len(board.pieces(chess.BISHOP, chess.WHITE)) +
        len(board.pieces(chess.BISHOP, chess.BLACK)) +
        len(board.pieces(chess.KNIGHT, chess.WHITE)) +
        len(board.pieces(chess.KNIGHT, chess.BLACK))
    )

    if not queens or minor_heavy <= 2:
        return "endgame"

    return "middlegame"


# ── King-safety heuristic ─────────────────────────────────────────────────────

def _king_is_unsafe(board: chess.Board, color: chess.Color) -> bool:
    """
    Rough heuristic: king is 'unsafe' if it has not castled (still on e-file)
    and is not in the endgame.  We approximate by checking the king's file.
    """
    king_sq   = board.king(color)
    king_file = chess.square_file(king_sq)

    # e-file = file 4 (files are 0-indexed)
    uncastled = king_file == 4

    # Also flag if the king's file has no own pawns (open file)
    own_pawns_on_file = any(
        chess.square_file(sq) == king_file
        for sq in board.pieces(chess.PAWN, color)
    )

    return uncastled or not own_pawns_on_file


# ── Tactic classification ─────────────────────────────────────────────────────
#
# How it works (2-engine-call approach):
#
#   Call 1 (already done in the main loop):
#       Stockfish evaluates board_before → gives best_move (what you SHOULD play)
#
#   Call 2 (new — only on blunders):
#       After your blunder is played, Stockfish evaluates that new position
#       → gives opp_best_reply (what the opponent WILL play to punish you)
#
#   We classify the tactic in two passes, in order of priority:
#
#   Pass A — "What did you miss?" (analyse best_move on board_before)
#       Did Stockfish's best move for you deliver mate, capture a hanging piece,
#       create a fork, pin, or skewer? That's what you overlooked.
#
#   Pass B — "What did you allow?" (analyse opp_best_reply on board_after_blunder)
#       After your bad move, did you leave a piece hanging? Did you allow a fork?
#       This is what the opponent can now do to punish you.
#
#   "Other" means neither A nor B detected a simple pattern — the error is
#   positional or involves a longer combination.

_SLIDING  = (chess.BISHOP, chess.ROOK, chess.QUEEN)
_VALUABLE = (chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT, chess.KING)


def _is_free_capture(board: chess.Board, move: chess.Move) -> bool:
    """True if *move* captures a completely undefended piece."""
    if not board.is_capture(move):
        return False
    return not board.attackers(not board.turn, move.to_square)


def _attacks_two_valuable(board: chess.Board, sq: int, target_color: chess.Color) -> bool:
    """True if the piece on *sq* attacks 2+ valuable target_color pieces."""
    hits = [
        s for s in board.attacks(sq)
        if board.piece_at(s) is not None
        and board.color_at(s) == target_color
        and board.piece_type_at(s) in _VALUABLE
    ]
    return len(hits) >= 2


def _detect_pin_skewer(board: chess.Board, slider_sq: int,
                       victim_color: chess.Color) -> str | None:
    """
    After a sliding piece has landed on *slider_sq*, check if it creates a
    pin or skewer against *victim_color*'s king.
    Returns "Pin", "Skewer", or None.
    """
    if board.piece_type_at(slider_sq) not in _SLIDING:
        return None
    king_sq = board.king(victim_color)
    if king_sq is None or king_sq not in board.attacks(slider_sq):
        return None
    between = list(chess.SquareSet(chess.between(slider_sq, king_sq)))
    victim_pieces = [
        s for s in between
        if board.piece_at(s) and board.color_at(s) == victim_color
    ]
    if not victim_pieces:
        return None  # direct check, not a pin
    # Skewer: there's something valuable behind the first victim
    behind = [
        s for s in between
        if s not in victim_pieces and board.piece_at(s) and board.color_at(s) == victim_color
    ]
    return "Skewer" if behind else "Pin"


def _detect_discovered_attack(board_before: chess.Board, move: chess.Move,
                               victim_color: chess.Color) -> bool:
    """
    True if moving *move* uncovers a sliding-piece attack on a valuable enemy.
    The moved piece's origin square (from_sq) must be on the ray between
    the friendly slider and the target it now threatens.
    """
    mover_color = board_before.turn
    from_sq     = move.from_square
    board_after = board_before.copy()
    board_after.push(move)

    for pt in (chess.BISHOP, chess.ROOK, chess.QUEEN):
        for slider_sq in board_after.pieces(pt, mover_color):
            if slider_sq == move.to_square:
                continue  # the moved piece itself — not discovered
            for target_sq in board_after.attacks(slider_sq):
                piece = board_after.piece_at(target_sq)
                if not piece or piece.color != victim_color:
                    continue
                if piece.piece_type not in _VALUABLE:
                    continue
                # Was from_sq blocking this ray before the move?
                between = list(chess.SquareSet(chess.between(slider_sq, target_sq)))
                if from_sq in between:
                    return True
    return False


def _classify_one_move(board_before: chess.Board, move: chess.Move,
                        victim_color: chess.Color) -> str | None:
    """
    Classify what a single move achieves against *victim_color*.
    Returns a tactic name or None if nothing specific detected.
    This is the core classifier, used for BOTH passes.
    """
    if move not in board_before.legal_moves:
        return None

    board_after = board_before.copy()
    board_after.push(move)

    # 1. Checkmate
    if board_after.is_checkmate():
        return "Checkmate threat"

    # 2. Hanging piece capture (takes a completely undefended piece)
    if _is_free_capture(board_before, move):
        return "Hanging piece"

    # 3. Promotion
    if move.promotion:
        return "Promotion"

    # 4. Fork (the moved piece now attacks 2+ valuable opponent pieces)
    if _attacks_two_valuable(board_after, move.to_square, victim_color):
        return "Fork"

    # 5. Pin or Skewer (sliding piece aligns with opponent's king)
    ps = _detect_pin_skewer(board_after, move.to_square, victim_color)
    if ps:
        return ps

    # 6. Discovered attack (moving reveals a slider's attack on a valuable piece)
    if _detect_discovered_attack(board_before, move, victim_color):
        return "Discovered attack"

    # 7. Forcing check (gives check but not mate — gains tempo/initiative)
    if board_after.is_check():
        return "Forcing check"

    return None


def _classify_tactic(
    board_before: chess.Board,
    best_move: chess.Move,       # Stockfish call 1: best move from board_before
    move_played: chess.Move,     # The actual blunder played
    opp_best_reply: chess.Move | None = None,  # Stockfish call 2: best reply after blunder
) -> str:
    """
    Classify the tactical pattern behind a blunder using two Stockfish calls.

    Pass A: Analyse best_move on board_before (what the player missed).
    Pass B: Analyse opp_best_reply on board_after_blunder (what they allowed).
    """
    try:
        mover_color    = board_before.turn
        opponent_color = not mover_color

        # ── Pass A: What move should the player have played? ─────────────────
        result = _classify_one_move(board_before, best_move, opponent_color)
        if result:
            return result

        # ── Pass B (static): Did the player leave a piece hanging? ───────────
        # This is a fast check that doesn't need the 2nd engine call.
        board_after_blunder = board_before.copy()
        board_after_blunder.push(move_played)

        for sq in (board_after_blunder.pieces(chess.PAWN,   mover_color) |
                   board_after_blunder.pieces(chess.KNIGHT, mover_color) |
                   board_after_blunder.pieces(chess.BISHOP, mover_color) |
                   board_after_blunder.pieces(chess.ROOK,   mover_color) |
                   board_after_blunder.pieces(chess.QUEEN,  mover_color)):
            if (board_after_blunder.attackers(opponent_color, sq) and
                    not board_after_blunder.attackers(mover_color, sq)):
                return "Hanging piece"

        # ── Pass B (engine): Classify the opponent's actual best reply ────────
        # opp_best_reply comes from Stockfish call 2 on board_after_blunder.
        # This is much more precise than scanning all legal moves.
        if opp_best_reply is not None:
            result = _classify_one_move(board_after_blunder, opp_best_reply, mover_color)
            if result:
                return result

        return "Positional"

    except Exception:
        return "Positional"


# ── Centipawn → accuracy conversion (Lichess formula) ────────────────────────

def _cp_to_win_prob(cp: int) -> float:
    """Convert a centipawn evaluation to a win probability [0, 1]."""
    import math
    return 1 / (1 + math.exp(-0.00368208 * cp))


def _accuracy_from_evals(
    evals_before: list[int],
    evals_after:  list[int],
    color:        chess.Color,
) -> float:
    """
    Compute move accuracy (0-100) for one player using the Lichess formula.
    evals_before[i] and evals_after[i] are from White's POV.
    color determines whose moves to include.
    """
    import math
    total_diff = 0.0
    count      = 0

    for i, (before, after) in enumerate(zip(evals_before, evals_after)):
        is_white_move = (i % 2 == 0)
        if (color == chess.WHITE) != is_white_move:
            continue

        # Flip perspective for Black
        if color == chess.BLACK:
            before, after = -before, -after

        wp_before = _cp_to_win_prob(before)
        wp_after  = _cp_to_win_prob(after)

        diff       = max(0.0, wp_before - wp_after)
        total_diff += diff
        count      += 1

    if count == 0:
        return 100.0

    avg_diff = total_diff / count
    # Lichess accuracy: 103.1668 * exp(-0.04354 * avg_diff_in_percent * 100) - 3.1669
    raw = 103.1668 * math.exp(-0.04354 * avg_diff * 100) - 3.1669
    return max(0.0, min(100.0, raw))


# ── Per-game analysis ─────────────────────────────────────────────────────────

def _analyse_game(
    row: pd.Series,
    engine: chess.engine.SimpleEngine,
    username: str,
) -> dict:
    """
    Run Stockfish over every position in the game and return a dict of
    enriched columns to add to the DataFrame row.
    """
    moves        = row["moves"]
    board_states = row["board_states"]
    clocks       = row["clocks"]
    player_color_str = row.get("player_color", "white")
    player_color = chess.WHITE if player_color_str == "white" else chess.BLACK

    n = len(moves)
    if n == 0:
        return _empty_result()

    # ── Step 1: Evaluate every position ──────────────────────────────────────
    # We evaluate the position BEFORE each move, plus the final position.

    evaluations: list[int] = []   # from White's POV, capped at ±2000

    current_board = chess.Board()
    positions_to_eval = [current_board.copy()]
    for move in moves:
        current_board.push(move)
        positions_to_eval.append(current_board.copy())

    # Also get best moves for every position (for error classification)
    best_moves_uci: list[str] = []

    for board_pos in positions_to_eval:
        try:
            info = engine.analyse(
                board_pos,
                chess.engine.Limit(depth=config.ANALYSIS_DEPTH),
            )
            score = info["score"].white()

            if score.is_mate():
                mate_in = score.mate()
                # Convert mate to large cp value
                cp = 10000 if mate_in > 0 else -10000
            else:
                cp = score.score(mate_score=10000)

            evaluations.append(max(-2000, min(2000, cp)))

            # Best move from this position
            bm = info.get("pv", [None])[0]
            best_moves_uci.append(bm.uci() if bm else "")
        except Exception as exc:
            logger.debug("Engine error on position: %s", exc)
            evaluations.append(evaluations[-1] if evaluations else 0)
            best_moves_uci.append("")

    # evaluations[i]    = eval before move i
    # evaluations[n]    = eval after last move
    # best_moves_uci[i] = best move from position before move i

    # ── Step 2: Classify every move (both player and opponent) ───────────────
    errors:          list[dict] = []   # player's own moves only
    opponent_errors: list[dict] = []   # opponent's moves only
    sharp_drops:     list[dict] = []
    first_error_move: int | None = None

    for i, move in enumerate(moves):
        is_white_move  = (i % 2 == 0)
        is_player_move = (player_color == chess.WHITE) == is_white_move

        eval_before = evaluations[i]
        eval_after  = evaluations[i + 1]

        # cp loss is always from the perspective of whoever just moved
        if is_white_move:
            cp_loss = eval_before - eval_after   # positive = White lost cp
        else:
            cp_loss = eval_after - eval_before   # positive = Black lost cp

        cp_loss = max(0, cp_loss)

        move_number  = (i // 2) + 1
        board_before = board_states[i]
        phase        = _detect_phase(board_before, move_number)

        # Skip checkmate move — no meaningful classification after game-ending move
        if board_before.is_checkmate() or not board_before.legal_moves:
            continue

        # Sharp-drop detection (regardless of who moved)
        if cp_loss >= config.SHARP_DROP_THRESHOLD:
            sharp_drops.append({
                "move_number":  move_number,
                "eval_before":  eval_before,
                "eval_after":   eval_after,
                "move_played":  move.uci(),
                "is_player":    is_player_move,
            })

        # ── Classify the move ──────────────────────────────────────────────────
        if cp_loss >= config.BLUNDER_THRESHOLD:
            classification = "blunder"
        elif cp_loss >= config.MISTAKE_THRESHOLD:
            classification = "mistake"
        elif cp_loss >= config.INACCURACY_THRESHOLD:
            classification = "inaccuracy"
        else:
            classification = "good"

        # Tactic type (blunders only)
        tactic_type   = "N/A"
        best_move_uci = best_moves_uci[i]
        best_move_obj = None
        if best_move_uci:
            try:
                best_move_obj = chess.Move.from_uci(best_move_uci)
            except ValueError:
                pass

        if classification == "blunder" and best_move_obj:
            # ── Stockfish call 2: get opponent's best reply after the blunder ──
            # We analyse the position AFTER the player's blunder move to find
            # exactly what the opponent can do — much more precise than scanning
            # all legal moves ourselves.
            opp_best_reply: chess.Move | None = None
            try:
                board_after_blunder = board_before.copy()
                board_after_blunder.push(move)
                info2 = engine.analyse(
                    board_after_blunder,
                    chess.engine.Limit(depth=config.ANALYSIS_DEPTH),
                )
                opp_pv = info2.get("pv", [None])[0]
                if opp_pv:
                    opp_best_reply = opp_pv
            except Exception as exc:
                logger.debug("2nd engine call failed: %s", exc)

            tactic_type = _classify_tactic(
                board_before, best_move_obj, move, opp_best_reply
            )

        # SAN notation
        try:
            move_san = board_before.san(move)
        except Exception:
            move_san = move.uci()
        try:
            best_san = (
                board_before.san(best_move_obj)
                if best_move_obj and best_move_obj in board_before.legal_moves
                else best_move_uci
            )
        except Exception:
            best_san = best_move_uci

        # Clock data
        clock_val     = clocks[i] if clocks else None
        time_pressure = clock_val is not None and clock_val < config.TIME_PRESSURE_SECONDS

        # King safety (only meaningful for the player being analysed)
        king_unsafe = _king_is_unsafe(board_before, player_color) if is_player_move else False

        record = {
            "move_number":     move_number,
            "phase":           phase,
            "move_played_uci": move.uci(),
            "move_played_san": move_san,
            "best_move_uci":   best_move_uci,
            "best_move_san":   best_san,
            "cp_loss":         cp_loss,
            "classification":  classification,
            "tactic_type":     tactic_type,
            "clock_remaining": clock_val,
            "time_pressure":   time_pressure,
            "king_unsafe":     king_unsafe,
        }

        # Route to player or opponent error list
        if is_player_move:
            errors.append(record)
            if classification in ("blunder", "mistake") and first_error_move is None:
                first_error_move = move_number
        else:
            opponent_errors.append(record)

    # ── Step 3: Accuracy ──────────────────────────────────────────────────────
    accuracy = _accuracy_from_evals(
        evaluations[:-1],
        evaluations[1:],
        player_color,
    )

    # ── Step 4: Winning-position conversion ───────────────────────────────────
    # Find all positions where the player's eval was >= WINNING_ADVANTAGE_THRESHOLD
    winning_positions: list[dict] = []
    result = row.get("result", "?")

    for i in range(n):
        is_white_move = (i % 2 == 0)
        # Eval from player's POV
        eval_player = evaluations[i] if player_color == chess.WHITE else -evaluations[i]

        if eval_player >= config.WINNING_ADVANTAGE_THRESHOLD:
            winning_positions.append({
                "move_number": (i // 2) + 1,
                "eval_cp":     eval_player,
            })

    # Determine conversion outcome
    if not winning_positions:
        conversion = "N/A"
    else:
        if player_color == chess.WHITE:
            won = result == "1-0"
            drew = result == "1/2-1/2"
        else:
            won  = result == "0-1"
            drew = result == "1/2-1/2"

        if won:
            conversion = "converted"
        elif drew:
            conversion = "drawn"
        else:
            conversion = "lost"

    return {
        "evaluations":       evaluations,
        "errors":            errors,            # player's moves only
        "opponent_errors":   opponent_errors,   # opponent's moves only
        "accuracy":          round(accuracy, 1),
        "first_error_move":  first_error_move,
        "sharp_drops":       sharp_drops,
        "winning_positions": winning_positions,
        "conversion":        conversion,
    }


def _empty_result() -> dict:
    return {
        "evaluations":       [],
        "errors":            [],
        "opponent_errors":   [],
        "accuracy":          None,
        "first_error_move":  None,
        "sharp_drops":       [],
        "winning_positions": [],
        "conversion":        "N/A",
    }


# ── Public entry point ────────────────────────────────────────────────────────

def enrich_analysis(
    df: pd.DataFrame,
    username: str,
    no_cache: bool = False,
) -> pd.DataFrame:
    """
    Run Stockfish analysis on every game in *df* and return an enriched
    DataFrame with analysis columns added.

    Parameters
    ----------
    no_cache : bool
        If True, ignore any cached results and re-analyse every game.
    """
    if df.empty:
        return df

    if not check_stockfish():
        sys.exit(1)

    cache         = {} if no_cache else _load_cache()
    results       = []
    total         = len(df)
    newly_done    = 0
    cache_hits    = 0

    # Count how many need Stockfish before printing the header
    need_engine = sum(
        1 for _, row in df.iterrows()
        if _cache_key(str(row.get("game_id", ""))) not in cache
    )

    if need_engine == 0:
        print(f"[analyzer] All {total} game(s) loaded from cache (depth {config.ANALYSIS_DEPTH}).")
    elif need_engine < total:
        print(f"[analyzer] {total - need_engine} game(s) from cache, "
              f"{need_engine} new game(s) to analyse at depth {config.ANALYSIS_DEPTH} …")
    else:
        print(f"[analyzer] Analysing {total} game(s) at depth {config.ANALYSIS_DEPTH} …")

    engine = None
    try:
        for idx, (_, row) in enumerate(df.iterrows(), 1):
            game_id = str(row.get("game_id", idx))
            key     = _cache_key(game_id)

            if key in cache:
                results.append(cache[key])
                cache_hits += 1
                continue

            # Start engine lazily — only when we actually need it
            if engine is None:
                try:
                    engine = _open_engine()
                    engine.configure({"Threads": 1, "Hash": 128})
                except Exception as exc:
                    print(f"[analyzer] Failed to start Stockfish: {exc}")
                    sys.exit(1)

            done_so_far = cache_hits + newly_done + 1
            print(f"  [{done_so_far}/{total}] game {game_id} …", end=" ", flush=True)
            try:
                result = _analyse_game(row, engine, username)
                acc_str = f"{result['accuracy']:.1f}%" if result["accuracy"] is not None else "N/A"
                print(f"acc={acc_str}  errors={len(result['errors'])}")
            except Exception as exc:
                logger.warning("Analysis failed for game %s: %s", game_id, exc)
                result = _empty_result()
                print("SKIPPED")

            cache[key] = result
            results.append(result)
            newly_done += 1

            # Flush cache to disk periodically so progress is not lost
            if newly_done % _CACHE_SAVE_INTERVAL == 0:
                _save_cache(cache)

    finally:
        if engine is not None:
            engine.quit()

    # Final cache save
    if newly_done > 0:
        _save_cache(cache)
        print(f"[analyzer] Done. ({newly_done} new, {cache_hits} cached)")
    else:
        print(f"[analyzer] Done. (all {cache_hits} from cache)")

    # Merge results back into the DataFrame
    df = df.copy()
    for col in ("evaluations", "errors", "opponent_errors", "accuracy", "first_error_move",
                "sharp_drops", "winning_positions", "conversion"):
        df[col] = [r[col] for r in results]

    return df
