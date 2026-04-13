# reporter.py — Generate the interactive HTML dashboard and per-game pages.
#
# Public API
# ----------
# generate_reports(df, opening_df, username) -> None
#   Writes output/dashboard.html and output/games/game_{id}.html

import json
import os
import math
from pathlib import Path

import chess
import pandas as pd

import config


# ── Helpers ───────────────────────────────────────────────────────────────────

def _pct(num, denom):
    return round(100 * num / denom, 1) if denom else 0


def _fmt_pct(v):
    return f"{v:.1f}%" if v is not None else "N/A"


def _na(v, fmt=".1f"):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "N/A"
    return format(v, fmt)


def _player_result(result: str, color: str) -> str:
    if color == "white":
        if result == "1-0":   return "win"
        if result == "0-1":   return "loss"
        return "draw"
    if color == "black":
        if result == "0-1":   return "win"
        if result == "1-0":   return "loss"
        return "draw"
    return "unknown"


# ── CSS / shared style ────────────────────────────────────────────────────────

_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: #1a1a2e; color: #e0e0e0; font-family: 'Segoe UI', Arial, sans-serif; font-size: 14px; }
h1, h2, h3 { color: #ffffff; margin-bottom: 12px; }
h1 { font-size: 1.8rem; }
h2 { font-size: 1.3rem; border-bottom: 2px solid #00b894; padding-bottom: 6px; margin-top: 32px; }
h3 { font-size: 1.1rem; margin-top: 16px; }
a { color: #00b894; text-decoration: none; }
a:hover { text-decoration: underline; }
.container { max-width: 1300px; margin: 0 auto; padding: 24px; }
.header { background: #16213e; padding: 20px 24px; border-bottom: 3px solid #00b894; margin-bottom: 32px; display: flex; align-items: center; gap: 20px; flex-wrap: wrap; }
.header h1 { margin: 0; }
.nav-links { margin-left: auto; display: flex; gap: 12px; align-items: center; }

/* Stat cards */
.cards { display: flex; flex-wrap: wrap; gap: 16px; margin: 16px 0; }
.card { background: #16213e; border-radius: 10px; padding: 18px 22px; min-width: 160px; flex: 1; border: 1px solid #0f3460; }
.card .value { font-size: 2rem; font-weight: 700; color: #00b894; line-height: 1.1; }
.card .label { font-size: 0.82rem; color: #a0a0c0; margin-top: 4px; }
.card.red .value { color: #d63031; }
.card.orange .value { color: #e17055; }
.card.yellow .value { color: #fdcb6e; }
.card.blue .value { color: #74b9ff; }

/* Tabs */
.tabs { display: flex; gap: 4px; margin: 16px 0 0; flex-wrap: wrap; }
.tab-btn { background: #0f3460; border: none; color: #a0a0c0; padding: 8px 18px; border-radius: 6px 6px 0 0; cursor: pointer; font-size: 0.9rem; }
.tab-btn.active { background: #00b894; color: #1a1a2e; font-weight: 700; }
.tab-content { display: none; background: #16213e; border-radius: 0 6px 6px 6px; padding: 20px; border: 1px solid #0f3460; }
.tab-content.active { display: block; }

/* Charts */
.chart-row { display: flex; gap: 24px; flex-wrap: wrap; margin: 16px 0; }
.chart-box { background: #16213e; border-radius: 10px; padding: 16px; border: 1px solid #0f3460; flex: 1; min-width: 280px; }
.chart-box canvas { max-height: 280px; }

/* Tables */
table { width: 100%; border-collapse: collapse; margin: 12px 0; }
th { background: #0f3460; color: #ffffff; padding: 10px 12px; text-align: left; cursor: pointer; user-select: none; white-space: nowrap; }
th:hover { background: #1a4a8a; }
th.sort-asc::after  { content: " ▲"; font-size: 0.75em; }
th.sort-desc::after { content: " ▼"; font-size: 0.75em; }
td { padding: 9px 12px; border-bottom: 1px solid #0f3460; }
tr:hover td { background: #1e2d5a; }
.blunder  { color: #d63031; }
.mistake  { color: #e17055; }
.inaccuracy { color: #fdcb6e; }
.good     { color: #00b894; }

/* Insights */
.insights { background: #16213e; border-radius: 10px; padding: 16px 20px; margin: 12px 0; border-left: 4px solid #00b894; }
.insights p { margin: 6px 0; line-height: 1.6; }

/* Dropdowns */
.filter-row { display: flex; align-items: center; gap: 10px; margin: 10px 0; }
select { background: #0f3460; color: #e0e0e0; border: 1px solid #00b894; border-radius: 5px; padding: 6px 10px; font-size: 0.9rem; }

/* Global filter bar */
.filter-bar { background: #16213e; border: 1px solid #00b894; border-radius: 10px; padding: 14px 20px; margin-bottom: 28px; display: flex; align-items: flex-end; gap: 20px; flex-wrap: wrap; }
.filter-bar label { display: block; color: #a0a0c0; font-size: 0.78rem; margin-bottom: 4px; text-transform: uppercase; letter-spacing: 0.05em; }
.filter-bar .filter-count { margin-left: auto; color: #a0a0c0; font-size: 0.88rem; align-self: center; }

/* Eval chart */
.eval-chart-wrap { background: #16213e; border-radius: 10px; padding: 16px; border: 1px solid #0f3460; margin: 16px 0; }
.eval-chart-wrap canvas { max-height: 320px; }

/* ── Opening chess board ──────────────────────────────────────────────────── */
.cb-wrap { background: #0d1b38; border-radius: 12px; padding: 20px 24px; border: 1px solid #00b894;
           margin: 14px 0 20px; display: none; gap: 28px; flex-wrap: wrap; align-items: flex-start; }
.cb-wrap.active { display: flex; }
.cb-close-btn { background: #d63031; border: none; color: #fff; border-radius: 5px;
                padding: 4px 10px; cursor: pointer; margin-left: auto; font-size: 0.82rem; }
.cb-close-btn:hover { background: #ff4444; }
.cb-board-area { display: flex; }
.cb-labels { display: flex; flex-direction: column; justify-content: space-around;
             height: 384px; font-size: 0.7rem; color: #a0a0c0; margin-right: 4px; user-select: none; }
.cb-board { display: grid; grid-template-columns: repeat(8, 48px);
            border: 2px solid #0f3460; border-radius: 3px; overflow: hidden; }
.cb-sq { width: 48px; height: 48px; display: flex; align-items: center;
         justify-content: center; font-size: 32px; line-height: 1; }
.cb-light { background: #f0d9b5; }
.cb-dark  { background: #b58863; }
.cb-hl    { outline: 4px solid rgba(255,220,0,0.9); outline-offset: -4px; }
.cb-files { display: flex; justify-content: space-around; width: 384px;
            font-size: 0.7rem; color: #a0a0c0; margin-top: 4px; user-select: none; }
.cb-wp { color: #fff; text-shadow: -1px -1px 0 #222, 1px -1px 0 #222, -1px 1px 0 #222, 1px 1px 0 #222; }
.cb-bp { color: #1a1a1a; text-shadow: -1px -1px 0 #bbb, 1px -1px 0 #bbb, -1px 1px 0 #bbb, 1px 1px 0 #bbb; }
.cb-nav { display: flex; gap: 8px; margin-top: 10px; align-items: center; flex-wrap: wrap; }
.cb-nav button { background: #0f3460; border: 1px solid #00b894; color: #e0e0e0;
                 border-radius: 5px; padding: 5px 13px; cursor: pointer; font-size: 0.85rem; }
.cb-nav button:hover { background: #00b894; color: #1a1a2e; }
.cb-step { color: #a0a0c0; font-size: 0.82rem; }
.cb-right { display: flex; flex-direction: column; }
.cb-move-list { font-family: 'Segoe UI', monospace; font-size: 0.9rem; line-height: 1.8;
                max-height: 420px; overflow-y: auto; min-width: 200px; padding: 4px 2px; }
.cb-pair { display: flex; gap: 6px; align-items: baseline; }
.cb-mn { color: #a0a0c0; min-width: 28px; font-size: 0.8rem; }
.cb-mv { padding: 2px 7px; border-radius: 4px; cursor: pointer; }
.cb-mv:hover { background: #1a3060; }
.cb-mv.cur { background: #00b894; color: #1a1a2e; font-weight: 700; border-radius: 4px; }
.cb-mv.theory { color: #74b9ff; }
.cb-mv.game-only { color: #fdcb6e; }
.cb-mv.cur.theory { background: #74b9ff; color: #1a1a2e; }
.cb-mv.cur.game-only { background: #fdcb6e; color: #1a1a2e; }
.cb-section-label { font-size: 0.7rem; color: #a0a0c0; text-transform: uppercase;
                    letter-spacing: 0.06em; margin: 6px 0 2px; padding: 2px 0;
                    border-top: 1px solid #0f3460; }
.cb-section-label.theory-lbl { color: #74b9ff; border-color: #74b9ff44; }
.cb-section-label.game-lbl   { color: #fdcb6e; border-color: #fdcb6e44; }
.cb-legend { display: flex; gap: 14px; margin: 8px 0 4px; font-size: 0.75rem; flex-wrap: wrap; }
.cb-legend span { display: flex; align-items: center; gap: 5px; }
.cb-legend .dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
.view-btn { background: transparent; border: 1px solid #00b894; color: #00b894;
            border-radius: 4px; padding: 3px 9px; cursor: pointer; font-size: 0.78rem; }
.view-btn:hover { background: #00b894; color: #1a1a2e; }

/* ── Pattern Analysis tab ───────────────────────────────────────────────────── */
.pat-grid { display: flex; flex-direction: column; gap: 36px; }
.pat-opening-group { margin-bottom: 4px; }
.pat-opening-name, .pat-opening-title {
  font-size: 1rem; font-weight: 700; color: #ffffff;
  background: #0d1b38; border-left: 4px solid #00b894;
  padding: 8px 16px; border-radius: 0 6px 6px 0; margin: 0 0 14px 0;
  display: inline-flex; align-items: center; }
.pat-cards-row, .pat-cards { display: flex; flex-wrap: wrap; gap: 16px; }
.pat-card { background: #16213e; border: 1px solid #0f3460; border-radius: 12px;
  padding: 16px; display: flex; flex-direction: column; gap: 12px;
  width: 340px; flex-shrink: 0;
  transition: border-color .15s; }
.pat-card:hover { border-color: #00b894; }
.pat-header { display: flex; align-items: center; justify-content: space-between; }
.pat-chip { padding: 4px 12px; border-radius: 12px; font-size: 0.82rem; font-weight: 700;
  background: #e1705522; color: #e17055; border: 1px solid #e1705555; }
.pat-cp-loss { font-size: 0.82rem; font-weight: 600; color: #ff6b6b;
  background: #d6303118; border: 1px solid #d6303140; border-radius: 8px; padding: 3px 10px; }
.pat-board-wrap { position: relative; width: 320px; height: 320px; }
.pat-board { display: grid; grid-template-columns: repeat(8, 40px);
  border: 2px solid #0f3460; border-radius: 3px; overflow: hidden; width: 320px; height: 320px; }
.pat-sq { width: 40px; height: 40px; display: flex; align-items: center;
  justify-content: center; font-size: 26px; line-height: 1; }
.pat-arrows { position: absolute; top: 2px; left: 2px; width: 316px; height: 316px;
  pointer-events: none; overflow: visible; }
.pat-moves { display: flex; flex-direction: column; gap: 7px; }
.pat-move { display: flex; align-items: center; gap: 10px; padding: 8px 12px;
  border-radius: 7px; font-size: 0.88rem; font-weight: 600; }
.pat-move.bad  { background: #d6303120; border: 1px solid #d6303150; color: #ff6b6b; }
.pat-move.good { background: #00b89420; border: 1px solid #00b89450; color: #00b894; }
.pat-empty { color: #a0a0c0; text-align: center; padding: 60px 20px;
  font-size: 0.95rem; background: #16213e; border-radius: 10px; border: 1px solid #0f3460; }

/* ── Documentation tab ──────────────────────────────────────────────────────── */
.doc-toc { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 36px; }
.doc-toc a { padding: 7px 16px; border-radius: 20px; font-size: 0.82rem; font-weight: 600;
  background: #16213e; border: 1px solid #0f3460; color: #74b9ff;
  text-decoration: none; transition: all .15s; }
.doc-toc a:hover { background: #0f3460; border-color: #74b9ff; }
.doc-section { margin-bottom: 44px; }
.doc-section-title { font-size: 1.1rem; font-weight: 800; color: #ffffff;
  border-left: 4px solid #00b894; padding: 10px 16px;
  background: #0d1b38; border-radius: 0 8px 8px 0; margin-bottom: 20px;
  display: flex; align-items: center; gap: 10px; }
.doc-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(380px, 1fr)); gap: 16px; }
.doc-card { background: #16213e; border: 1px solid #0f3460; border-radius: 12px; padding: 20px 22px; }
.doc-card-name { font-size: 1rem; font-weight: 700; color: #ffffff; margin-bottom: 6px; }
.doc-card-def { font-size: 0.88rem; color: #cdd6f4; line-height: 1.6; margin-bottom: 10px; }
.doc-formula { background: #0a1628; border-left: 3px solid #74b9ff; border-radius: 0 6px 6px 0;
  padding: 8px 12px; font-size: 0.82rem; color: #74b9ff; margin-bottom: 10px;
  font-family: monospace; line-height: 1.5; }
.doc-example { background: #0a2818; border-left: 3px solid #00b894; border-radius: 0 6px 6px 0;
  padding: 8px 12px; font-size: 0.82rem; color: #00b894; margin-bottom: 10px;
  line-height: 1.5; }
.doc-example::before { content: "Example: "; font-weight: 700; }
.doc-source { font-size: 0.75rem; color: #6c7a9c; margin-top: 6px; }
.doc-source span { display: inline-block; padding: 2px 8px; border-radius: 10px;
  background: #0f3460; color: #a0a0c0; font-size: 0.72rem; margin-right: 4px; }
.doc-threshold-table { width: 100%; border-collapse: collapse; margin-top: 8px; font-size: 0.84rem; }
.doc-threshold-table th { color: #a0a0c0; font-weight: 600; text-align: left;
  padding: 6px 10px; border-bottom: 1px solid #0f3460; }
.doc-threshold-table td { color: #cdd6f4; padding: 6px 10px; border-bottom: 1px solid #0d1b38; }
.doc-threshold-table tr:last-child td { border-bottom: none; }
.doc-tactic-badge { display: inline-block; padding: 2px 10px; border-radius: 10px;
  font-size: 0.78rem; font-weight: 600; margin: 2px; background: #0f346033; border: 1px solid #0f3460; color: #a0c4ff; }
.doc-intro { color: #a0a0c0; font-size: 0.92rem; line-height: 1.7;
  background: #16213e; border-radius: 10px; padding: 18px 22px;
  border: 1px solid #0f3460; margin-bottom: 32px; }
.doc-intro strong { color: #ffffff; }
"""

# ── Chart.js CDN ──────────────────────────────────────────────────────────────

_CHARTJS = '<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>'

# ── Color palette ─────────────────────────────────────────────────────────────
C_WIN   = "#00b894"
C_LOSS  = "#d63031"
C_DRAW  = "#74b9ff"
C_MIST  = "#e17055"
C_INACC = "#fdcb6e"
C_BG    = "#16213e"
C_GRID  = "#2d3561"


# ══════════════════════════════════════════════════════════════════════════════
#  PER-GAME PAGE
# ══════════════════════════════════════════════════════════════════════════════

def _game_insights(row: pd.Series) -> list[str]:
    """Generate plain-English insight sentences for one game."""
    insights = []
    errors   = row.get("errors", []) or []
    color    = row.get("player_color", "white")
    result   = row.get("result", "?")
    outcome  = _player_result(result, color)

    # Winning position conversion
    winning = row.get("winning_positions", []) or []
    conv    = row.get("conversion", "N/A")
    if winning:
        best_adv = max(w["eval_cp"] for w in winning)
        best_move = min(winning, key=lambda w: abs(w["eval_cp"] - best_adv))["move_number"]
        if conv == "lost":
            insights.append(
                f"You had a winning advantage (+{best_adv/100:.1f}) on move "
                f"{best_move} but lost — conversion issue detected."
            )
        elif conv == "drawn":
            insights.append(
                f"You were winning (+{best_adv/100:.1f}) on move {best_move} "
                "but only drew — a missed conversion."
            )

    # First error timing
    first_err = row.get("first_error_move")
    if first_err is not None:
        insights.append(f"Your first critical error came on move {first_err}.")

    # Blunder details
    blunders = [e for e in errors if e["classification"] == "blunder"]
    for b in blunders[:3]:    # cap at 3 to avoid noise
        tactic = b.get("tactic_type", "Other")
        clock  = b.get("clock_remaining")
        parts  = [f"Blunder on move {b['move_number']}"]
        if tactic not in ("N/A", "Other"):
            parts.append(f"— missed {tactic}")
        if clock is not None:
            parts.append(f"with {int(clock)}s remaining")
        insights.append(". ".join(parts) + ".")

    # King safety
    unsafe_blunders = [e for e in errors if e.get("king_unsafe") and e["classification"] == "blunder"]
    if unsafe_blunders:
        insights.append(
            f"Your king was uncastled or exposed at the time of "
            f"{len(unsafe_blunders)} blunder(s) in this game."
        )

    # Time pressure
    tp_blunders = [e for e in errors if e.get("time_pressure") and e["classification"] == "blunder"]
    if tp_blunders:
        insights.append(
            f"{len(tp_blunders)} blunder(s) occurred with fewer than "
            f"{config.TIME_PRESSURE_SECONDS}s remaining."
        )

    return insights or ["No critical issues detected in this game — well played!"]


def _render_game_page(
    row: pd.Series,
    game_index: int,
    total_games: int,
    all_game_ids: list[str],
    username: str,
    opening_df: pd.DataFrame,
) -> str:
    """Return full HTML for a single game analysis page."""

    gid     = row["game_id"]
    date    = row.get("date", "?")
    white   = row.get("white", "?")
    black   = row.get("black", "?")
    result  = row.get("result", "?")
    tc      = row.get("time_control", "?")
    cat     = row.get("category", "?")
    opening = row.get("opening_name", "?")
    eco     = row.get("eco", "?")
    welo    = row.get("white_elo", "?")
    belo    = row.get("black_elo", "?")
    color   = row.get("player_color", "?")
    outcome = _player_result(result, color)
    acc     = row.get("accuracy")
    errors  = row.get("errors", []) or []
    evals   = row.get("evaluations", []) or []
    theory  = row.get("theory_depth", "?")
    has_clk = row.get("has_clock_data", False)

    # Nav links
    prev_link = next_link = ""
    if game_index > 1:
        prev_id = all_game_ids[game_index - 2]
        prev_link = f'<a href="game_{prev_id}.html">← Previous</a>'
    if game_index < total_games:
        next_id = all_game_ids[game_index]
        next_link = f'<a href="game_{next_id}.html">Next →</a>'

    outcome_color = {"win": C_WIN, "loss": C_LOSS, "draw": C_DRAW}.get(outcome, "#ffffff")

    # ── Error counts — player ─────────────────────────────────────────────────
    p_blunders     = sum(1 for e in errors if e["classification"] == "blunder")
    p_mistakes     = sum(1 for e in errors if e["classification"] == "mistake")
    p_inaccuracies = sum(1 for e in errors if e["classification"] == "inaccuracy")
    p_good         = sum(1 for e in errors if e["classification"] == "good")

    # ── Error counts — opponent ────────────────────────────────────────────────
    opp_errors     = row.get("opponent_errors", []) or []
    o_blunders     = sum(1 for e in opp_errors if e["classification"] == "blunder")
    o_mistakes     = sum(1 for e in opp_errors if e["classification"] == "mistake")
    o_inaccuracies = sum(1 for e in opp_errors if e["classification"] == "inaccuracy")
    o_good         = sum(1 for e in opp_errors if e["classification"] == "good")

    opponent_name  = black if color == "white" else white

    # ── Game phase where game was decided (phase of first blunder/mistake) ────
    critical = [e for e in errors if e["classification"] in ("blunder", "mistake")]
    decided_phase = critical[0]["phase"].capitalize() if critical else "N/A"

    # ── Evaluation chart data ─────────────────────────────────────────────────
    # Cap at ±500 for display
    eval_capped = [max(-500, min(500, e)) for e in evals]

    # Build point-by-point background color arrays
    eval_colors = []
    for i, v in enumerate(eval_capped[:-1]):
        # Whose turn is it? Index i means move i was about to be played
        if color == "white":
            eval_colors.append(C_WIN if v > 0 else C_LOSS)
        else:
            eval_colors.append(C_WIN if v < 0 else C_LOSS)

    # Phase boundary annotations
    moves_list = row.get("moves", [])
    boards     = row.get("board_states", [])
    phase_annots = []
    prev_phase = None
    for i, b in enumerate(boards):
        from analyzer import _detect_phase
        ph = _detect_phase(b, (i // 2) + 1)
        if ph != prev_phase and prev_phase is not None:
            phase_annots.append({"x": i, "label": ph.capitalize()})
        prev_phase = ph

    # Blunder/mistake/inaccuracy annotations on eval chart
    error_annots = []
    for e in errors:
        move_num = e["move_number"]
        ply      = (move_num - 1) * 2 + (0 if color == "white" else 1)
        cls      = e["classification"]
        clr      = {"blunder": C_LOSS, "mistake": C_MIST, "inaccuracy": C_INACC}.get(cls, C_WIN)
        error_annots.append({"x": ply + 1, "color": clr, "label": cls[0].upper()})

    eval_labels = list(range(len(eval_capped)))

    # ── Critical moves table rows ─────────────────────────────────────────────
    def _error_rows():
        rows_html = []
        for e in errors:
            if e["classification"] == "good":
                continue
            cls = e["classification"]
            cls_class = cls
            clock_str = (
                f"{int(e['clock_remaining'])}s" if e.get("clock_remaining") is not None else "N/A"
            )
            tp_marker = " ⚠" if e.get("time_pressure") else ""
            rows_html.append(f"""
            <tr class="{cls_class}">
              <td>{e['move_number']}</td>
              <td>{e['phase'].capitalize()}</td>
              <td>{e['move_played_san']}</td>
              <td class="{cls_class}">{cls.capitalize()}</td>
              <td>{e['best_move_san'] or e['best_move_uci']}</td>
              <td>{e['cp_loss']}</td>
              <td>{e['tactic_type']}</td>
              <td>{clock_str}{tp_marker}</td>
            </tr>""")
        return "\n".join(rows_html) if rows_html else '<tr><td colspan="8">No errors recorded.</td></tr>'

    # ── Opening stats from aggregated data ────────────────────────────────────
    opening_row = None
    if not opening_df.empty and "opening_name" in opening_df.columns:
        matches = opening_df[opening_df["opening_name"] == opening]
        if not matches.empty:
            opening_row = matches.iloc[0]

    opening_wr_str = (
        f"{opening_row['win_rate']*100:.1f}%" if opening_row is not None else "N/A"
    )

    # ── Insights ──────────────────────────────────────────────────────────────
    insights_html = "\n".join(f"<p>• {i}</p>" for i in _game_insights(row))

    # ── Chart.js eval chart script ────────────────────────────────────────────
    # We use a custom plugin to draw vertical lines for phase boundaries
    error_annots_json = json.dumps(error_annots)
    phase_annots_json = json.dumps(phase_annots)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Game {game_index}: {white} vs {black} | ChessVision</title>
{_CHARTJS}
<style>
{_CSS}
</style>
</head>
<body>
<div class="header">
  <div>
    <h1>Game {game_index} / {total_games}</h1>
    <div style="color:#a0a0c0; font-size:0.9rem;">
      {date} &nbsp;|&nbsp; {white} ({welo}) vs {black} ({belo})
      &nbsp;|&nbsp; {cat} ({tc})
      &nbsp;|&nbsp; <strong style="color:{outcome_color}">{outcome.upper()}</strong>
    </div>
    <div style="color:#a0a0c0; font-size:0.9rem; margin-top:4px;">
      {opening} ({eco}) &nbsp;|&nbsp; Decided in: <strong>{decided_phase}</strong>
    </div>
  </div>
  <div class="nav-links">
    {prev_link}
    <a href="../dashboard.html">Dashboard</a>
    {next_link}
  </div>
</div>
<div class="container">

<!-- Stat cards — two-row comparison table -->
<h2>Move Quality Comparison</h2>
<table style="max-width:680px;margin:12px 0">
  <thead>
    <tr>
      <th></th>
      <th style="color:{C_WIN}">You ({username})</th>
      <th style="color:{C_LOSS}">Opponent ({opponent_name})</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><strong>Accuracy</strong></td>
      <td style="color:{C_WIN}">{_na(acc)}%</td>
      <td style="color:#a0a0c0">—</td>
    </tr>
    <tr>
      <td><strong class="blunder">Blunders</strong> (&gt;150cp)</td>
      <td class="blunder">{p_blunders}</td>
      <td class="blunder">{o_blunders}</td>
    </tr>
    <tr>
      <td><strong class="mistake">Mistakes</strong> (&gt;80cp)</td>
      <td class="mistake">{p_mistakes}</td>
      <td class="mistake">{o_mistakes}</td>
    </tr>
    <tr>
      <td><strong class="inaccuracy">Inaccuracies</strong> (&gt;40cp)</td>
      <td class="inaccuracy">{p_inaccuracies}</td>
      <td class="inaccuracy">{o_inaccuracies}</td>
    </tr>
    <tr>
      <td><strong class="good">Good moves</strong></td>
      <td class="good">{p_good}</td>
      <td class="good">{o_good}</td>
    </tr>
  </tbody>
</table>

<!-- Evaluation chart -->
<h2>Evaluation Graph</h2>
<div class="eval-chart-wrap">
  <canvas id="evalChart"></canvas>
</div>

<!-- Key insights -->
<h2>Key Insights</h2>
<div class="insights">
  {insights_html}
</div>

<!-- Critical moves table -->
<h2>Critical Moves</h2>
<table id="movesTable">
  <thead>
    <tr>
      <th onclick="sortTable('movesTable',0)">Move #</th>
      <th onclick="sortTable('movesTable',1)">Phase</th>
      <th onclick="sortTable('movesTable',2)">Move Played</th>
      <th onclick="sortTable('movesTable',3)">Classification</th>
      <th onclick="sortTable('movesTable',4)">Best Move</th>
      <th onclick="sortTable('movesTable',5)">Cp Loss</th>
      <th onclick="sortTable('movesTable',6)">Tactic Type</th>
      <th onclick="sortTable('movesTable',7)">Time Remaining</th>
    </tr>
  </thead>
  <tbody>
    {_error_rows()}
  </tbody>
</table>

<!-- Opening info -->
<h2>Opening Info</h2>
<div class="cards">
  <div class="card">
    <div class="value" style="font-size:1.1rem">{eco}</div>
    <div class="label">{opening}</div>
  </div>
  <div class="card">
    <div class="value">{theory}</div>
    <div class="label">Moves in Theory</div>
  </div>
  <div class="card">
    <div class="value">{opening_wr_str}</div>
    <div class="label">Your Win Rate (this opening)</div>
  </div>
</div>

</div><!-- /container -->

<script>
// ── Eval chart ────────────────────────────────────────────────────────────────
(function() {{
  const labels      = {json.dumps(eval_labels)};
  const data        = {json.dumps(eval_capped)};
  const errorAnnots = {error_annots_json};
  const phaseAnnots = {phase_annots_json};

  const ctx = document.getElementById('evalChart').getContext('2d');

  // Gradient fill
  function makeGradient(ctx, yAxis) {{
    const grad = ctx.createLinearGradient(0, yAxis.getPixelForValue(500), 0, yAxis.getPixelForValue(-500));
    grad.addColorStop(0,   'rgba(0,184,148,0.4)');
    grad.addColorStop(0.5, 'rgba(26,26,46,0)');
    grad.addColorStop(1,   'rgba(214,48,49,0.4)');
    return grad;
  }}

  // Vertical line plugin
  const vertLinePlugin = {{
    id: 'vertLines',
    afterDraw(chart) {{
      const ctx2 = chart.ctx;
      const xAxis = chart.scales.x;
      const yAxis = chart.scales.y;

      // Phase boundaries (dashed)
      phaseAnnots.forEach(a => {{
        const x = xAxis.getPixelForValue(a.x);
        ctx2.save();
        ctx2.setLineDash([6,4]);
        ctx2.strokeStyle = 'rgba(116,185,255,0.6)';
        ctx2.lineWidth = 1.5;
        ctx2.beginPath();
        ctx2.moveTo(x, yAxis.top);
        ctx2.lineTo(x, yAxis.bottom);
        ctx2.stroke();
        ctx2.restore();

        ctx2.save();
        ctx2.fillStyle = 'rgba(116,185,255,0.9)';
        ctx2.font = '11px Segoe UI';
        ctx2.fillText(a.label, x + 3, yAxis.top + 14);
        ctx2.restore();
      }});

      // Error markers (solid)
      errorAnnots.forEach(a => {{
        const x = xAxis.getPixelForValue(a.x);
        ctx2.save();
        ctx2.strokeStyle = a.color;
        ctx2.lineWidth = 1.5;
        ctx2.setLineDash([]);
        ctx2.globalAlpha = 0.7;
        ctx2.beginPath();
        ctx2.moveTo(x, yAxis.top);
        ctx2.lineTo(x, yAxis.bottom);
        ctx2.stroke();
        ctx2.restore();
      }});
    }}
  }};

  new Chart(ctx, {{
    type: 'line',
    plugins: [vertLinePlugin],
    data: {{
      labels: labels,
      datasets: [{{
        label: 'Evaluation (cp)',
        data: data,
        borderColor: '{C_WIN}',
        borderWidth: 2,
        pointRadius: 0,
        tension: 0.3,
        fill: {{
          target: {{ value: 0 }},
          above: 'rgba(0,184,148,0.25)',
          below: 'rgba(214,48,49,0.25)',
        }},
      }}]
    }},
    options: {{
      responsive: true,
      animation: false,
      scales: {{
        x: {{ ticks: {{ color: '#a0a0c0' }}, grid: {{ color: '{C_GRID}' }} }},
        y: {{
          min: -500, max: 500,
          ticks: {{ color: '#a0a0c0' }},
          grid:  {{ color: '{C_GRID}' }},
        }}
      }},
      plugins: {{
        legend: {{ labels: {{ color: '#ffffff' }} }},
        tooltip: {{ callbacks: {{
          label: ctx => `Eval: ${{ctx.parsed.y > 0 ? '+' : ''}}${{ctx.parsed.y}}cp`
        }} }}
      }}
    }}
  }});
}})();

// ── Table sort ────────────────────────────────────────────────────────────────
function sortTable(tableId, colIdx) {{
  const table = document.getElementById(tableId);
  const tbody = table.tBodies[0];
  const th    = table.tHead.rows[0].cells[colIdx];
  const asc   = !th.classList.contains('sort-asc');
  Array.from(table.tHead.rows[0].cells).forEach(c => c.classList.remove('sort-asc','sort-desc'));
  th.classList.add(asc ? 'sort-asc' : 'sort-desc');
  const rows = Array.from(tbody.rows);
  rows.sort((a, b) => {{
    let av = a.cells[colIdx].textContent.trim();
    let bv = b.cells[colIdx].textContent.trim();
    const an = parseFloat(av), bn = parseFloat(bv);
    if (!isNaN(an) && !isNaN(bn)) return asc ? an-bn : bn-an;
    return asc ? av.localeCompare(bv) : bv.localeCompare(av);
  }});
  rows.forEach(r => tbody.appendChild(r));
}}
</script>
</body>
</html>"""


# ══════════════════════════════════════════════════════════════════════════════
#  DASHBOARD PAGE
# ══════════════════════════════════════════════════════════════════════════════

def _build_dashboard(df: pd.DataFrame, opening_df: pd.DataFrame, username: str) -> str:

    total = len(df)

    # ── Global stats ──────────────────────────────────────────────────────────
    def outcome_count(df, outcome):
        return sum(
            _player_result(r, c) == outcome
            for r, c in zip(df["result"], df["player_color"])
        )

    wins   = outcome_count(df, "win")
    losses = outcome_count(df, "loss")
    draws  = outcome_count(df, "draw")

    avg_acc = df["accuracy"].mean() if "accuracy" in df.columns else None

    def avg_per_game(df, cls, col="errors"):
        if col not in df.columns:
            return 0
        return (
            df[col]
            .apply(lambda errs: sum(1 for e in (errs or []) if e["classification"] == cls))
            .mean()
        )

    avg_blunders         = avg_per_game(df, "blunder")
    avg_mistakes         = avg_per_game(df, "mistake")
    avg_inaccuracies     = avg_per_game(df, "inaccuracy")
    avg_opp_blunders     = avg_per_game(df, "blunder",    "opponent_errors")
    avg_opp_mistakes     = avg_per_game(df, "mistake",    "opponent_errors")
    avg_opp_inaccuracies = avg_per_game(df, "inaccuracy", "opponent_errors")

    # ── By time control ───────────────────────────────────────────────────────
    categories = ["Bullet", "Blitz", "Rapid", "Classical"]

    def tc_stats(cat):
        sub = df[df["category"] == cat]
        if sub.empty:
            return None
        w = outcome_count(sub, "win")
        l = outcome_count(sub, "loss")
        d = outcome_count(sub, "draw")
        n = len(sub)
        a = sub["accuracy"].mean() if "accuracy" in sub.columns else None
        b = avg_per_game(sub, "blunder")
        return {
            "n": n, "wins": w, "losses": l, "draws": d,
            "acc": a, "blunders": b,
        }

    tc_data = {cat: tc_stats(cat) for cat in categories}

    def tc_tab_html(cat):
        d = tc_data.get(cat)
        if not d:
            return f"<div class='tab-content' id='tab-{cat.lower()}'><p>No {cat} games found.</p></div>"
        n = d["n"]
        return f"""
        <div class='tab-content' id='tab-{cat.lower()}'>
          <div class='cards'>
            <div class='card'><div class='value'>{n}</div><div class='label'>Games</div></div>
            <div class='card'><div class='value' style='color:{C_WIN}'>{d['wins']}</div><div class='label'>Wins ({_pct(d['wins'],n)}%)</div></div>
            <div class='card red'><div class='value'>{d['losses']}</div><div class='label'>Losses ({_pct(d['losses'],n)}%)</div></div>
            <div class='card blue'><div class='value'>{d['draws']}</div><div class='label'>Draws ({_pct(d['draws'],n)}%)</div></div>
            <div class='card blue'><div class='value'>{_na(d['acc'])}%</div><div class='label'>Avg Accuracy</div></div>
            <div class='card orange'><div class='value'>{d['blunders']:.2f}</div><div class='label'>Avg Blunders/Game</div></div>
          </div>
        </div>"""

    tc_tabs_html = "\n".join(tc_tab_html(cat) for cat in categories)

    # ── Error breakdown chart data ────────────────────────────────────────────
    total_blunders    = sum(avg_per_game(df, "blunder")     * total for _ in [1])
    total_mistakes    = sum(avg_per_game(df, "mistake")     * total for _ in [1])
    total_inaccuracies= sum(avg_per_game(df, "inaccuracy")  * total for _ in [1])

    # Errors per game
    def count_errors_by_phase_and_class(df, phase, cls):
        if "errors" not in df.columns:
            return 0
        return int(df["errors"].apply(
            lambda errs: sum(1 for e in (errs or []) if e["phase"] == phase and e["classification"] == cls)
        ).sum())

    blunders_opening   = count_errors_by_phase_and_class(df, "opening",    "blunder")
    blunders_middle    = count_errors_by_phase_and_class(df, "middlegame", "blunder")
    blunders_endgame   = count_errors_by_phase_and_class(df, "endgame",    "blunder")

    # Tactic counts
    tactic_counts: dict[str, int] = {}
    if "errors" in df.columns:
        for errs in df["errors"]:
            for e in (errs or []):
                if e["classification"] == "blunder":
                    t = e.get("tactic_type", "Other")
                    tactic_counts[t] = tactic_counts.get(t, 0) + 1
    tactic_labels = list(tactic_counts.keys()) or ["None"]
    tactic_values = list(tactic_counts.values()) or [0]

    # ── Critical pattern stats ────────────────────────────────────────────────

    # % games lost after exactly 1 blunder
    def lost_after_exactly_1_blunder(row):
        errs    = row.get("errors", []) or []
        blunders= [e for e in errs if e["classification"] == "blunder"]
        outcome = _player_result(row["result"], row["player_color"])
        return len(blunders) == 1 and outcome == "loss"

    games_1_blunder_lost = sum(lost_after_exactly_1_blunder(r) for _, r in df.iterrows())
    pct_1_blunder_lost   = _pct(games_1_blunder_lost, total)

    # Conversion stats
    has_winning = df["winning_positions"].apply(lambda x: bool(x)) if "winning_positions" in df.columns else pd.Series([False]*total)
    winning_games = df[has_winning]
    converted  = (winning_games["conversion"] == "converted").sum() if not winning_games.empty else 0
    not_conv   = (winning_games["conversion"].isin(["drawn","lost"])).sum() if not winning_games.empty else 0
    total_winning = len(winning_games)
    pct_converted = _pct(converted, total_winning)
    pct_not_conv  = _pct(not_conv,  total_winning)

    # Avg first error move
    first_errors = df["first_error_move"].dropna() if "first_error_move" in df.columns else pd.Series(dtype=float)
    avg_first_error = first_errors.mean() if not first_errors.empty else None

    # % king unsafe at blunder
    _errors_col = df["errors"] if "errors" in df.columns else pd.Series([[]]*total)
    all_blunders = [
        e for errs in _errors_col
        for e in (errs or [])
        if e["classification"] == "blunder"
    ]
    unsafe_blunders = [b for b in all_blunders if b.get("king_unsafe")]
    pct_king_unsafe = _pct(len(unsafe_blunders), len(all_blunders)) if all_blunders else 0

    # % time pressure blunders
    has_any_clock = df.get("has_clock_data", pd.Series([False]*total)).any()
    tp_blunders   = [b for b in all_blunders if b.get("time_pressure")]
    pct_tp        = _pct(len(tp_blunders), len(all_blunders)) if (all_blunders and has_any_clock) else None
    pct_tp_str    = f"{pct_tp:.1f}%" if pct_tp is not None else "N/A"

    # ── Opening table ─────────────────────────────────────────────────────────
    def opening_table_rows(color_filter="Both"):
        rows_html = []
        for _, o in opening_df.iterrows():
            # Filter by color if needed
            if color_filter in ("White", "Black"):
                sub = df[
                    (df["opening_name"] == o["opening_name"]) &
                    (df["player_color"] == color_filter.lower())
                ]
                if len(sub) < config.MIN_GAMES_PER_OPENING:
                    continue
                wins_sub = sum(_player_result(r, c) == "win" for r, c in zip(sub["result"], sub["player_color"]))
                wr = _pct(wins_sub, len(sub))
                n  = len(sub)
            else:
                wr = round(o["win_rate"] * 100, 1)
                n  = o["games_played"]

            acc_str  = _na(o.get("avg_accuracy"), ".1f") + "%" if o.get("avg_accuracy") is not None else "N/A"
            err_str  = _na(o.get("avg_first_error"), ".1f") if o.get("avg_first_error") is not None else "N/A"
            tact_str = o.get("most_missed_tactic", "N/A")

            safe_op = o['opening_name'].replace('"', '&quot;')
            rows_html.append(f"""
            <tr data-opname="{safe_op}" onclick="showOpeningBoard(this.dataset.opname)" style="cursor:pointer" title="Click to replay opening">
              <td><button class="view-btn" onclick="event.stopPropagation();showOpeningBoard(this.closest('tr').dataset.opname)">&#9654;</button></td>
              <td>{o['opening_name']}</td>
              <td>{o['eco']}</td>
              <td>{n}</td>
              <td>{wr}%</td>
              <td>{acc_str}</td>
              <td>{err_str}</td>
              <td>{tact_str}</td>
            </tr>""")
        return "\n".join(rows_html) if rows_html else '<tr><td colspan="8">No data yet (need 3+ games per opening).</td></tr>'

    # Opening bar chart data (top 8 by games played)
    top8_played = opening_df.nlargest(8, "games_played") if not opening_df.empty else pd.DataFrame()
    top8_wr     = opening_df.nlargest(8, "win_rate")     if not opening_df.empty else pd.DataFrame()

    def safe_trunc(name, n=22):
        return name[:n] + "…" if len(name) > n else name

    top8_played_labels = json.dumps([safe_trunc(n) for n in top8_played.get("opening_name", [])])
    top8_played_values = json.dumps(list(top8_played.get("games_played", [])))
    top8_wr_labels     = json.dumps([safe_trunc(n) for n in top8_wr.get("opening_name", [])])
    top8_wr_values     = json.dumps([round(v*100, 1) for v in top8_wr.get("win_rate", [])])

    # Theory depth bar chart (top 10 openings by games played)
    theory_df = opening_df.nlargest(10, "games_played") if not opening_df.empty else pd.DataFrame()
    theory_labels = json.dumps([safe_trunc(n) for n in theory_df.get("opening_name", [])])
    theory_values = json.dumps([round(v, 1) if v is not None else 0 for v in theory_df.get("avg_theory_depth", [])])

    # Pre-build tab buttons HTML (avoids backslash-in-f-string on Python < 3.12)
    tab_buttons_html = "".join(
        f'<button class="tab-btn" onclick="switchTab(\'{cat.lower()}\')">{cat}</button>'
        for cat in categories
    )

    # Pre-build JS opening data JSON (avoids complex expression inside f-string)
    opening_js_data = json.dumps([
        {
            "opening_name":      str(row.get("opening_name", "")),
            "eco":               str(row.get("eco", "")),
            "games_played":      int(row.get("games_played", 0)),
            "win_rate":          round(float(row.get("win_rate", 0)) * 100, 1),
            "avg_accuracy":      round(float(row.get("avg_accuracy", 0)), 1)
                                 if row.get("avg_accuracy") is not None else None,
            "avg_first_error":   round(float(row.get("avg_first_error", 0)), 1)
                                 if row.get("avg_first_error") is not None else None,
            "most_missed_tactic": str(row.get("most_missed_tactic", "N/A")),
        }
        for _, row in opening_df.iterrows()
    ] if not opening_df.empty else [])

    def _safe_int(v):
        try:
            return int(v) if v is not None and not (isinstance(v, float) and math.isnan(v)) else None
        except Exception:
            return None

    def _opp_elo(row):
        if str(row.get("player_color")) == "white":
            v = row.get("black_elo")
        else:
            v = row.get("white_elo")
        try:
            return int(v) if v is not None else 0
        except Exception:
            return 0

    per_game_js_data = json.dumps([
        {
            "game_id":        str(row.get("game_id", "")),
            "opening_name":   str(row.get("opening_name", "")),
            "eco":            str(row.get("eco", "")),
            "player_color":   str(row.get("player_color", "")),
            "result":         str(row.get("result", "")),
            "accuracy":       float(row.get("accuracy") or 0),
            "blunders":       int(sum(1 for e in (row.get("errors") or []) if e["classification"] == "blunder")),
            "mistakes":       int(sum(1 for e in (row.get("errors") or []) if e["classification"] == "mistake")),
            "inaccuracies":   int(sum(1 for e in (row.get("errors") or []) if e["classification"] == "inaccuracy")),
            "opp_blunders":   int(sum(1 for e in (row.get("opponent_errors") or []) if e["classification"] == "blunder")),
            "opp_mistakes":   int(sum(1 for e in (row.get("opponent_errors") or []) if e["classification"] == "mistake")),
            "opp_inaccuracies": int(sum(1 for e in (row.get("opponent_errors") or []) if e["classification"] == "inaccuracy")),
            "category":       str(row.get("category", "")),
            "date":           str(row.get("date", "")),
            "opponent_elo":   _opp_elo(row),
            "first_error_move": _safe_int(row.get("first_error_move")),
            "num_moves":      int(len(row.get("moves", []))),
            "termination":    str(row.get("termination", "unknown")),
            "theory_depth":   int(row.get("theory_depth") or 0),
            "blunder_phases": [e["phase"] for e in (row.get("errors") or []) if e["classification"] == "blunder"],
            "tactic_types":   [e.get("tactic_type", "Other") for e in (row.get("errors") or []) if e["classification"] == "blunder"],
        }
        for _, row in df.iterrows()
    ])

    # Unique opening names for the filter dropdown
    opening_options_html = "".join(
        f'<option value="{o}">{o}</option>'
        for o in sorted(df["opening_name"].dropna().unique())
    )

    min_games = config.MIN_GAMES_PER_OPENING

    # ── Opening move sequences (for chess board component) ────────────────────
    # For each unique opening, pick the game with the highest theory_depth and
    # extract its first N plies as FEN positions + SAN move labels.
    opening_moves_map: dict = {}
    for op_name in df["opening_name"].dropna().unique():
        sub = df[df["opening_name"] == op_name].copy()
        if "theory_depth" in sub.columns:
            sub = sub.sort_values("theory_depth", ascending=False)
        row0 = sub.iloc[0]
        depth          = int(row0.get("theory_depth") or 0)
        has_real_theory = depth > 0
        raw_mvs        = row0.get("moves", []) or []
        if not has_real_theory:
            depth = min(6, len(raw_mvs) // 2)
        theory_plies = depth * 2
        # Show theory line + up to 20 more plies of the actual game
        total_plies  = min(theory_plies + 20, len(raw_mvs))
        steps        = []
        brd          = chess.Board()
        steps.append({"san": None, "fen": brd.fen(), "from": None, "to": None,
                       "in_theory": True})
        for i in range(total_plies):
            try:
                m   = raw_mvs[i]
                san = brd.san(m)
                frm = chess.square_name(m.from_square)
                to_ = chess.square_name(m.to_square)
                brd.push(m)
                steps.append({"san": san, "fen": brd.fen(), "from": frm, "to": to_,
                               "in_theory": has_real_theory and (i < theory_plies)})
            except Exception:
                break
        opening_moves_map[str(op_name)] = {
            "eco":          str(row0.get("eco", "?")),
            "theory_depth": depth if has_real_theory else 0,
            "steps":        steps,
        }
    opening_moves_js = json.dumps(opening_moves_map)

    # ── Recurring mistake pattern analysis ────────────────────────────────────
    # Groups blunders/mistakes by (opening, move_played_uci) across all games.
    # The same bad UCI move in the same opening = a recurring pattern.
    # Uses board_states from the DataFrame — no Stockfish re-analysis needed.
    from collections import defaultdict as _dd, Counter as _Ctr
    _MIN_PATTERN_OCC = 2

    _pat_groups: dict = _dd(list)
    for _, _row in df.iterrows():
        _opening   = str(_row.get("opening_name", "") or "Unknown Opening")
        _eco       = str(_row.get("eco", "?") or "?")
        _bstates   = _row.get("board_states", []) or []
        _pcolor    = str(_row.get("player_color", "white") or "white")
        _cat       = str(_row.get("category", "") or "")
        _date      = str(_row.get("date", "") or "")

        for _err in (_row.get("errors") or []):
            if _err.get("classification") not in ("blunder", "mistake"):
                continue
            _muci = _err.get("move_played_uci", "")
            if not _muci:
                continue
            # Recover board position for FEN snapshot
            _mn  = _err.get("move_number", 0)
            _ply = (_mn - 1) * 2 + (0 if _pcolor == "white" else 1)
            _fen_full = _bstates[_ply].fen() if (0 <= _ply < len(_bstates)) else ""
            _pat_groups[(_opening, _muci)].append({
                "eco":            _eco,
                "fen_full":       _fen_full,
                "best_uci":       _err.get("best_move_uci", ""),
                "move_bad_san":   _err.get("move_played_san", ""),
                "best_san":       _err.get("best_move_san", ""),
                "cp_loss":        int(_err.get("cp_loss", 0)),
                "phase":          _err.get("phase", "middlegame"),
                "tactic_type":    _err.get("tactic_type", "Positional"),
                "classification": _err.get("classification", "blunder"),
                "player_color":   _pcolor,
                "category":       _cat,
                "date":           _date,
            })

    _patterns_list: list[dict] = []
    for (_opening, _muci), _entries in _pat_groups.items():
        if len(_entries) < _MIN_PATTERN_OCC:
            continue
        _avg_cp   = round(sum(e["cp_loss"] for e in _entries) / len(_entries))
        _best_uci = _Ctr(e["best_uci"] for e in _entries).most_common(1)[0][0]
        _best_san = next((e["best_san"] for e in _entries if e["best_uci"] == _best_uci), _best_uci)
        _top_cls  = _Ctr(e["classification"] for e in _entries).most_common(1)[0][0]
        _top_ph   = _Ctr(e["phase"] for e in _entries).most_common(1)[0][0]
        _tactics_valid = [e["tactic_type"] for e in _entries if e["tactic_type"] not in ("N/A", "")]
        _top_tac  = _Ctr(_tactics_valid).most_common(1)[0][0] if _tactics_valid else "Positional"
        _top_color = _Ctr(e["player_color"] for e in _entries).most_common(1)[0][0]
        _top_cat   = _Ctr(e["category"] for e in _entries).most_common(1)[0][0]
        # Pick the representative FEN (first non-empty)
        _rep_fen  = next((e["fen_full"] for e in _entries if e["fen_full"]), "")
        _rep_bsan = next((e["move_bad_san"] for e in _entries if e["move_bad_san"]), _muci)
        _patterns_list.append({
            "opening":        _opening,
            "eco":            _entries[0]["eco"],
            "fen":            _rep_fen,
            "move_bad_uci":   _muci,
            "move_bad_san":   _rep_bsan,
            "move_good_uci":  _best_uci,
            "move_good_san":  _best_san,
            "count":          len(_entries),
            "avg_cp_loss":    _avg_cp,
            "classification": _top_cls,
            "phase":          _top_ph,
            "tactic_type":    _top_tac,
            "color":          _top_color,
            "category":       _top_cat,
            "occurrences": [
                {"color": e["player_color"], "category": e["category"], "date": e["date"]}
                for e in _entries
            ],
        })

    _patterns_list.sort(key=lambda p: (-p["count"], -p["avg_cp_loss"]))
    patterns_js = json.dumps({"patterns": _patterns_list[:80]})

    # ── Games list (links) ────────────────────────────────────────────────────
    game_rows = []
    for i, (_, row) in enumerate(df.iterrows(), 1):
        gid      = row["game_id"]
        date     = row.get("date", "?")
        white    = row.get("white", "?")
        black    = row.get("black", "?")
        result   = row.get("result", "?")
        color    = row.get("player_color", "?")
        outcome  = _player_result(result, color)
        acc      = _na(row.get("accuracy"), ".1f")
        cat      = row.get("category", "?")
        opening  = row.get("opening_name", "?")
        eco      = row.get("eco", "?")
        blunders = sum(1 for e in (row.get("errors") or []) if e["classification"] == "blunder")
        opp_name = row.get("black", "?") if color == "white" else row.get("white", "?")
        try:
            opp_elo_val = int(row.get("black_elo") if color == "white" else row.get("white_elo")) if (row.get("black_elo") if color == "white" else row.get("white_elo")) is not None else "?"
        except Exception:
            opp_elo_val = "?"

        oc = {"win": C_WIN, "loss": C_LOSS, "draw": C_DRAW}.get(outcome, "#fff")
        game_rows.append(f"""
        <tr data-color="{color}" data-opening="{opening}" data-category="{cat}">
          <td><a href="games/game_{gid}.html">{i}</a></td>
          <td>{date}</td>
          <td>{white} vs {black}</td>
          <td style="color:{oc}">{outcome.upper()}</td>
          <td>{cat}</td>
          <td>{eco} — {opening}</td>
          <td>{acc}%</td>
          <td>{blunders}</td>
          <td>{opp_elo_val}</td>
        </tr>""")

    games_table = "\n".join(game_rows)

    categories_js = json.dumps([c.lower() for c in categories])

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ChessVision \u2014 {username}</title>
{_CHARTJS}
<style>
{_CSS}

/* \u2500\u2500 Page tabs \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500 */
.page-tabs-wrap {{
  background: #0d1b38;
  display: flex;
  gap: 0;
  border-bottom: 3px solid #00b894;
  padding: 0 24px;
  position: sticky;
  top: 0;
  z-index: 100;
}}
.ptab {{
  background: transparent;
  border: none;
  color: #a0a0c0;
  padding: 14px 28px;
  cursor: pointer;
  font-size: 1rem;
  font-weight: 600;
  border-bottom: 3px solid transparent;
  margin-bottom: -3px;
}}
.ptab.active {{ color: #00b894; border-bottom-color: #00b894; }}
.ptab:hover {{ color: #ffffff; }}
.page-content {{ display: none; }}
.page-content.active {{ display: block; }}

/* \u2500\u2500 Opening page \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500 */
.op-selector-bar {{
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 20px;
}}
.op-badge {{
  background: #0f3460;
  border-radius: 20px;
  padding: 4px 14px;
  font-size: 0.82rem;
  color: #a0a0c0;
}}
.op-board-theory {{
  display: flex;
  gap: 28px;
  flex-wrap: wrap;
  align-items: flex-start;
  margin: 16px 0 24px;
}}
.op-theory-col {{
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-width: 220px;
}}
.theory-depth-box {{
  background: #0d1b38;
  border-radius: 10px;
  padding: 16px 20px;
  border: 1px solid #00b894;
}}
.theory-depth-num {{
  font-size: 3rem;
  font-weight: 700;
  color: #00b894;
  line-height: 1;
}}
.theory-bar-wrap {{
  background: #0f3460;
  border-radius: 4px;
  height: 10px;
  margin: 8px 0;
  overflow: hidden;
}}
.theory-bar-fill {{
  background: #00b894;
  height: 100%;
  border-radius: 4px;
  transition: width 0.3s;
}}
.move-seq-box {{
  background: #0d1b38;
  border-radius: 10px;
  padding: 14px 16px;
  border: 1px solid #0f3460;
  font-family: monospace;
  font-size: 0.88rem;
  line-height: 1.8;
  color: #e0e0e0;
  max-height: 180px;
  overflow-y: auto;
}}
.cmp-table td:first-child {{ color: #a0a0c0; }}
.cmp-table td:nth-child(2) {{ color: #00b894; font-weight: 700; }}
.cmp-table td:nth-child(3) {{ color: #74b9ff; }}
.tc-grid {{
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  margin: 12px 0;
}}
.tc-card {{
  background: #0d1b38;
  border-radius: 8px;
  padding: 12px 16px;
  border: 1px solid #0f3460;
  min-width: 120px;
}}
.tc-card .tc-name {{
  color: #a0a0c0;
  font-size: 0.78rem;
  margin-bottom: 6px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}}
.tc-card .tc-stat {{ font-size: 0.88rem; }}
.op-section-title {{
  color: #a0a0c0;
  font-size: 0.78rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  margin: 24px 0 8px;
  border-top: 1px solid #0f3460;
  padding-top: 16px;
}}
.op-summary-table tr {{ cursor: pointer; }}
</style>
</head>
<body>

<!-- \u2500\u2500 Header \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500 -->
<div class="header">
  <div>
    <h1>ChessVision</h1>
    <div style="color:#a0a0c0">Analysis for <strong>{username}</strong></div>
    <div style="color:#a0a0c0;font-size:0.83rem;margin-top:3px">Based on your last <strong style="color:#ffffff">{total} games</strong> &nbsp;&middot;&nbsp; Avg accuracy <strong style="color:#00b894">{_na(avg_acc)}%</strong> &nbsp;&middot;&nbsp; {wins}W / {losses}L / {draws}D</div>
  </div>
</div>

<!-- \u2500\u2500 Page tabs \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500 -->
<div class="page-tabs-wrap">
  <button class="ptab" id="ptab-dashboard" onclick="showPage('dashboard')">Dashboard</button>
  <button class="ptab" id="ptab-openings"  onclick="showPage('openings')">Openings</button>
  <button class="ptab" id="ptab-games"     onclick="showPage('games')">Games</button>
  <button class="ptab" id="ptab-patterns"  onclick="showPage('patterns')">⚡ Patterns</button>
  <button class="ptab" id="ptab-docs"      onclick="showPage('docs')">📖 How it works</button>
</div>

<!-- \u2500\u2500 Global filter bar \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500 -->
<div class="container" style="padding-bottom:0;padding-top:16px">
<div class="filter-bar">
  <span style="font-weight:700;color:#ffffff;font-size:1rem">Filters</span>
  <div>
    <label for="gColorFilter">Color</label>
    <select id="gColorFilter" onchange="applyFilters()">
      <option value="">All</option>
      <option value="white">White</option>
      <option value="black">Black</option>
    </select>
  </div>
  <div>
    <label for="gCategoryFilter">Game Type</label>
    <select id="gCategoryFilter" onchange="applyFilters()">
      <option value="">All types</option>
      <option value="Bullet">Bullet</option>
      <option value="Blitz">Blitz</option>
      <option value="Rapid">Rapid</option>
      <option value="Classical">Classical</option>
    </select>
  </div>
  <span id="gFilterCount" class="filter-count"></span>
</div>
</div>

<!-- \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
     PAGE 1: DASHBOARD
     \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550 -->
<div id="page-dashboard" class="page-content">
<div class="container">

<!-- Move Quality Table -->
<h2>Move Quality \u2014 You vs Opponents (averages per game)</h2>
<table style="max-width:600px;margin:12px 0">
  <thead>
    <tr>
      <th></th>
      <th style="color:{C_WIN}">You ({username})</th>
      <th style="color:{C_LOSS}">Opponents (avg)</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><strong class="blunder">Blunders</strong> (&gt;150cp)</td>
      <td class="blunder" id="dashMyBlu">{avg_blunders:.2f}</td>
      <td class="blunder" id="dashOppBlu">{avg_opp_blunders:.2f}</td>
    </tr>
    <tr>
      <td><strong class="mistake">Mistakes</strong> (&gt;80cp)</td>
      <td class="mistake" id="dashMyMist">{avg_mistakes:.2f}</td>
      <td class="mistake" id="dashOppMist">{avg_opp_mistakes:.2f}</td>
    </tr>
    <tr>
      <td><strong class="inaccuracy">Inaccuracies</strong> (&gt;40cp)</td>
      <td class="inaccuracy" id="dashMyInacc">{avg_inaccuracies:.2f}</td>
      <td class="inaccuracy" id="dashOppInacc">{avg_opp_inaccuracies:.2f}</td>
    </tr>
  </tbody>
</table>

<!-- Dynamic stat cards -->
<h2>Overall Statistics</h2>
<div id="dashStatCards" class="cards"></div>

<!-- Performance by Time Control -->
<h2>Performance by Time Control</h2>
<div class="tabs" id="dashTcTabBtns">
  {tab_buttons_html}
</div>
{tc_tabs_html}

<!-- Error Breakdown -->
<h2>Error Breakdown</h2>
<div class="chart-row">
  <div class="chart-box" style="max-width:320px">
    <h3>Error Distribution</h3>
    <canvas id="dashDonut"></canvas>
  </div>
  <div class="chart-box">
    <h3>Blunders by Phase</h3>
    <canvas id="dashPhase"></canvas>
  </div>
  <div class="chart-box">
    <h3>Missed Tactics</h3>
    <canvas id="dashTactics"></canvas>
  </div>
</div>

<!-- Critical Patterns -->
<h2>Critical Patterns</h2>
<div class="cards">
  <div class="card red">
    <div class="value" id="dashCrit1">{pct_1_blunder_lost:.1f}%</div>
    <div class="label">Games Lost After 1 Blunder</div>
  </div>
  <div class="card">
    <div class="value" id="dashCrit2">{pct_converted:.1f}%</div>
    <div class="label">Winning Positions Converted</div>
  </div>
  <div class="card orange">
    <div class="value" id="dashCrit3">{_na(avg_first_error, ".1f")}</div>
    <div class="label">Avg Move # of First Error</div>
  </div>
  <div class="card orange">
    <div class="value" id="dashCrit4">{pct_king_unsafe:.1f}%</div>
    <div class="label">Blunders with King Unsafe</div>
  </div>
</div>

</div><!-- /container -->
</div><!-- /page-dashboard -->

<!-- \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
     PAGE 2: OPENINGS
     \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550 -->
<div id="page-openings" class="page-content">
<div class="container">

<!-- Opening selector -->
<div class="op-selector-bar">
  <div>
    <label style="display:block;color:#a0a0c0;font-size:0.78rem;text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px">Opening</label>
    <select id="opTabSel" onchange="openingTabUpdate()" style="min-width:260px">
      <option value="">&#8212; select opening &#8212;</option>
      {opening_options_html}
    </select>
  </div>
  <span id="opEcoBadge" class="op-badge">ECO \u2014</span>
  <span id="opGamesBadge" class="op-badge">0 games</span>
</div>

<!-- Board + Theory depth side by side -->
<div class="op-board-theory" id="opBoardTheory">
  <div>
    <div class="cb-board-area">
      <div class="cb-labels" id="opRankLabels"></div>
      <div>
        <div class="cb-board" id="opBoard"></div>
        <div class="cb-files" id="opFileLabels"></div>
      </div>
    </div>
    <div class="cb-nav">
      <button onclick="opStart()">&#10218;</button>
      <button onclick="opPrev()">&#8592; Prev</button>
      <button onclick="opNext()">Next &#8594;</button>
      <button onclick="opEnd()">&#10219;</button>
      <button onclick="opFlip()" title="Flip">&#8645;</button>
      <span id="opStep" class="cb-step"></span>
    </div>
    <div class="cb-legend" id="opLegend">
      <span><span class="dot" style="background:#74b9ff"></span><span style="color:#74b9ff">Book theory</span></span>
      <span><span class="dot" style="background:#fdcb6e"></span><span style="color:#fdcb6e">Game continuation</span></span>
    </div>
  </div>
  <div class="op-theory-col">
    <div class="theory-depth-box">
      <div style="color:#a0a0c0;font-size:0.78rem;text-transform:uppercase;letter-spacing:.05em;margin-bottom:8px">Book Theory Depth</div>
      <div id="opTheoryNum" class="theory-depth-num">\u2014</div>
      <div style="color:#a0a0c0;font-size:0.78rem;margin-top:4px">moves of known theory</div>
      <div class="theory-bar-wrap"><div id="opTheoryBar" class="theory-bar-fill" style="width:0%"></div></div>
      <div id="opTheoryNote" style="color:#a0a0c0;font-size:0.78rem"></div>
    </div>
    <div style="color:#a0a0c0;font-size:0.78rem;text-transform:uppercase;letter-spacing:.05em;margin-top:4px">Opening sequence</div>
    <div class="move-seq-box" id="opMoveSeq">\u2014</div>
  </div>
  <div class="cb-right">
    <div style="color:#a0a0c0;font-size:0.78rem;margin-bottom:6px;text-transform:uppercase;letter-spacing:.05em">Move navigator</div>
    <div class="cb-move-list" id="opMoveList"></div>
  </div>
</div>

<!-- Unified statistics comparison -->
<div class="op-section-title">Statistics: This Opening vs All Games</div>
<div style="overflow-x:auto">
<table class="cmp-table" style="max-width:700px">
  <thead>
    <tr>
      <th>Metric</th>
      <th style="color:{C_WIN}">This Opening</th>
      <th style="color:{C_DRAW}">All Games</th>
    </tr>
  </thead>
  <tbody id="opCmpBody">
    <tr><td colspan="3" style="color:#a0a0c0">Select an opening above.</td></tr>
  </tbody>
</table>
</div>

<!-- Performance per time control -->
<div class="op-section-title">Performance per Time Control</div>
<div id="opTcGrid" class="tc-grid"></div>

<!-- Charts row -->
<div class="op-section-title">Trends</div>
<div class="chart-row">
  <div class="chart-box">
    <h3>Win Rate Trend (recent games)</h3>
    <canvas id="opTrendChart"></canvas>
  </div>
  <div class="chart-box" style="max-width:300px">
    <h3>W / D / L</h3>
    <canvas id="opWdlDonut"></canvas>
  </div>
</div>

<!-- Error analysis -->
<div class="op-section-title">Error Analysis</div>
<div id="opErrCards" class="cards" style="margin-bottom:16px"></div>
<div class="chart-row">
  <div class="chart-box">
    <h3>Blunders by Phase</h3>
    <canvas id="opPhaseChart"></canvas>
  </div>
  <div class="chart-box">
    <h3>Missed Tactics</h3>
    <canvas id="opTacticsChart"></canvas>
  </div>
</div>

<!-- All Openings Summary -->
<div class="op-section-title">All Openings Summary</div>
<div style="overflow-x:auto">
<table id="opSummaryTable" class="op-summary-table">
  <thead>
    <tr>
      <th onclick="sortTable('opSummaryTable',0)">Opening</th>
      <th onclick="sortTable('opSummaryTable',1)">ECO</th>
      <th onclick="sortTable('opSummaryTable',2)">Games</th>
      <th onclick="sortTable('opSummaryTable',3)">Win%</th>
      <th onclick="sortTable('opSummaryTable',4)">Avg Acc.</th>
      <th onclick="sortTable('opSummaryTable',5)">Avg Theory</th>
      <th onclick="sortTable('opSummaryTable',6)">Avg 1st Err</th>
      <th onclick="sortTable('opSummaryTable',7)" style="white-space:nowrap">Top Blunder Type <span style="cursor:help;color:#74b9ff;font-weight:normal" title="The most frequent tactical pattern behind your blunders in this opening.&#10;&#10;Possible values:&#10;&#8226; Hanging piece — you left or missed an undefended piece&#10;&#8226; Fork — a piece that attacks two or more valuable pieces simultaneously&#10;&#8226; Pin — a sliding piece aligned with your king, making a piece in between immovable&#10;&#8226; Skewer — like a pin, but the more valuable piece is in front&#10;&#8226; Discovered attack — moving a piece reveals a hidden attack from a piece behind it&#10;&#8226; Forcing check — you missed or allowed a check that gains material or initiative&#10;&#8226; Promotion — a pawn promotion was missed or allowed&#10;&#8226; Checkmate threat — a forced mate sequence was available&#10;&#8226; Positional — no specific tactical pattern detected; the error was likely structural (bad piece placement, weakened pawn structure, poor coordination)">&#9432;</span></th>
    </tr>
  </thead>
  <tbody id="opSummaryBody">
    <tr><td colspan="8" style="color:#a0a0c0">Loading\u2026</td></tr>
  </tbody>
</table>
</div>

</div><!-- /container -->
</div><!-- /page-openings -->

<!-- \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
     PAGE 3: GAMES
     \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550 -->
<div id="page-games" class="page-content">
<div class="container">

<h2>Games</h2>
<div id="gamesStatCards" class="cards" style="margin-bottom:20px"></div>

<div style="display:flex;align-items:flex-end;gap:16px;margin-bottom:16px;flex-wrap:wrap">
  <div>
    <label style="display:block;color:#a0a0c0;font-size:0.78rem;text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px">Opening</label>
    <select id="gOpeningFilter" onchange="applyFilters()" style="min-width:220px">
      <option value="">All openings</option>
      {opening_options_html}
    </select>
  </div>
  <span id="gamesFilterCount" style="color:#a0a0c0;font-size:0.88rem;align-self:center"></span>
</div>

<div style="overflow-x:auto">
<table id="gamesTable">
  <thead>
    <tr>
      <th onclick="sortTable('gamesTable',0)">#</th>
      <th onclick="sortTable('gamesTable',1)">Date</th>
      <th onclick="sortTable('gamesTable',2)">Players</th>
      <th onclick="sortTable('gamesTable',3)">Result</th>
      <th onclick="sortTable('gamesTable',4)">Category</th>
      <th onclick="sortTable('gamesTable',5)">Opening</th>
      <th onclick="sortTable('gamesTable',6)">Accuracy</th>
      <th onclick="sortTable('gamesTable',7)">Blunders</th>
      <th onclick="sortTable('gamesTable',8)">Opp. ELO</th>
    </tr>
  </thead>
  <tbody id="gamesTableBody">
    {games_table}
  </tbody>
</table>
</div>

</div><!-- /container -->
</div><!-- /page-games -->

<!-- ══════════════════════════════════════════════════════════════════════════
     PAGE 4: PATTERNS
     ══════════════════════════════════════════════════════════════════════════ -->
<div id="page-patterns" class="page-content">
<div class="container">

<h2>⚡ Recurring Mistakes</h2>
<p style="color:#a0a0c0;margin-bottom:20px;font-size:0.9rem">
  Positions where you repeatedly played the same bad move across multiple games.
  Only patterns occurring in <strong style="color:#ffffff">≥2 games</strong> are shown.
  <span style="color:#ff6b6b">Red arrow</span> = your move &nbsp;·&nbsp;
  <span style="color:#00b894">Green arrow</span> = Stockfish best.
</p>

<div id="patSummaryCards" class="cards" style="margin-bottom:28px"></div>
<div id="patGrid" class="pat-grid"></div>

</div>
</div><!-- /page-patterns -->

<!-- ══════════════════════════════════════════════════════════════════════════
     PAGE 5: DOCUMENTATION
     ══════════════════════════════════════════════════════════════════════════ -->
<div id="page-docs" class="page-content">
<div class="container">

<h2>📖 How metrics are calculated</h2>

<p class="doc-intro">
  This page explains every number you see in the dashboard — what it means, how it is computed,
  and where the data comes from. <strong>No data science background needed.</strong>
  ChessVision uses two data sources: the <strong>Chess.com API</strong> (game results, ratings,
  opening tags) and the <strong>Stockfish engine</strong> (move-by-move evaluation, best moves,
  centipawn loss). Stockfish is the same engine used by world-class players; it assigns a score
  in <em>centipawns</em> (cp) — one pawn of advantage = 100 cp.
</p>

<!-- Table of contents -->
<nav class="doc-toc">
  <a href="#doc-general">🏆 General Performance</a>
  <a href="#doc-errors">⚠️ Error Metrics</a>
  <a href="#doc-tactics">🧩 Tactic Types</a>
  <a href="#doc-openings">♟️ Opening Metrics</a>
  <a href="#doc-opponent">👤 Opponent Metrics</a>
  <a href="#doc-patterns">⚡ Pattern Analysis</a>
  <a href="#doc-critical">🔍 Critical Patterns</a>
</nav>

<!-- ── 1. General Performance ─────────────────────────────────────────────── -->
<div class="doc-section" id="doc-general">
  <div class="doc-section-title">🏆 General Performance</div>
  <div class="doc-grid">

    <div class="doc-card">
      <div class="doc-card-name">Games Played</div>
      <div class="doc-card-def">The total number of games included in the current view, after any filters (color, time control) are applied.</div>
      <div class="doc-formula">Count of games matching the active filters</div>
      <div class="doc-example">You played 200 games total. With the "Blitz" filter on, only 80 blitz games are counted.</div>
      <div class="doc-source"><span>Chess.com API</span></div>
    </div>

    <div class="doc-card">
      <div class="doc-card-name">Win Rate</div>
      <div class="doc-card-def">The share of games you won, expressed as a percentage. A draw does not count as a win.</div>
      <div class="doc-formula">Win Rate = (Games won ÷ Total games) × 100</div>
      <div class="doc-example">You won 55 out of 100 games → Win Rate = 55%</div>
      <div class="doc-source"><span>Chess.com API</span></div>
    </div>

    <div class="doc-card">
      <div class="doc-card-name">Draw Rate &amp; Loss Rate</div>
      <div class="doc-card-def">Same principle as win rate, applied to draws and losses respectively. The three rates always add up to 100%.</div>
      <div class="doc-formula">Draw Rate = (Draws ÷ Total games) × 100<br>Loss Rate = (Losses ÷ Total games) × 100</div>
      <div class="doc-example">55 wins, 10 draws, 35 losses out of 100 games → 55% / 10% / 35%</div>
      <div class="doc-source"><span>Chess.com API</span></div>
    </div>

    <div class="doc-card">
      <div class="doc-card-name">Accuracy</div>
      <div class="doc-card-def">
        A score from 0 to 100 that measures how close your moves were to Stockfish's best move throughout the game.
        100% means every move was perfect; 50% means you made many suboptimal choices.
        It is computed per game and then averaged across all games.
      </div>
      <div class="doc-formula">
        For each move: Move Score = 100 − f(centipawn loss), where f is a smoothing curve<br>
        Game Accuracy = average of all move scores<br>
        Displayed Accuracy = average across all selected games
      </div>
      <div class="doc-example">In a 30-move game, if your average centipawn loss per move is small, your accuracy will be around 85–95%. A game with a single big blunder might drop to 70%.</div>
      <div class="doc-source"><span>Stockfish engine</span></div>
    </div>

    <div class="doc-card">
      <div class="doc-card-name">Avg Blunders / Game</div>
      <div class="doc-card-def">The average number of blunder-level mistakes you made per game. Lower is better.</div>
      <div class="doc-formula">Avg Blunders/Game = Total blunders across all games ÷ Number of games</div>
      <div class="doc-example">You made 40 blunders across 20 games → 2.0 blunders per game on average.</div>
      <div class="doc-source"><span>Stockfish engine</span></div>
    </div>

  </div>
</div>

<!-- ── 2. Error Metrics ───────────────────────────────────────────────────── -->
<div class="doc-section" id="doc-errors">
  <div class="doc-section-title">⚠️ Error Metrics</div>

  <div class="doc-card" style="margin-bottom:16px">
    <div class="doc-card-name">Centipawn Loss (CP Loss)</div>
    <div class="doc-card-def">
      The centipawn loss of a move is the difference between the evaluation before and after you played it,
      measured in centipawns (1 pawn = 100 cp). It tells you how much ground you lost with a single move.
      Stockfish evaluates the position before your move, you play, then it re-evaluates — the drop is your centipawn loss.
    </div>
    <div class="doc-formula">CP Loss = Eval before your move − Eval after your move (from your perspective)</div>
    <div class="doc-example">Stockfish says position is +0.5 (slightly better for you). You play a bad move, now it's −0.8 (better for opponent). CP Loss = 130 cp → classified as a Blunder.</div>
    <div class="doc-source"><span>Stockfish engine</span></div>
  </div>

  <div class="doc-grid">

    <div class="doc-card">
      <div class="doc-card-name">Error Classifications</div>
      <div class="doc-card-def">Every move is scored by Stockfish. If the centipawn loss crosses a threshold, the move is flagged as an error of the corresponding severity.</div>
      <table class="doc-threshold-table">
        <tr><th>Label</th><th>CP Loss threshold</th><th>Severity</th></tr>
        <tr><td>Inaccuracy</td><td>&gt; 40 cp</td><td>Minor slip</td></tr>
        <tr><td>Mistake</td><td>&gt; 80 cp</td><td>Significant error</td></tr>
        <tr><td>Blunder</td><td>&gt; 150 cp</td><td>Serious error</td></tr>
      </table>
      <div class="doc-source"><span>Stockfish engine</span></div>
    </div>

    <div class="doc-card">
      <div class="doc-card-name">Blunders per Game</div>
      <div class="doc-card-def">Count of moves in a game where your centipawn loss exceeded 150 cp. Each such move is one blunder, regardless of how big the loss was.</div>
      <div class="doc-formula">Blunders = count of moves with CP Loss &gt; 150 in that game</div>
      <div class="doc-example">In one game you made 3 moves with losses of 200 cp, 180 cp, and 90 cp. Only the first two are blunders (≥150 cp); the third is a mistake.</div>
      <div class="doc-source"><span>Stockfish engine</span></div>
    </div>

    <div class="doc-card">
      <div class="doc-card-name">Mistakes per Game</div>
      <div class="doc-card-def">Count of moves with a centipawn loss above 80 cp but at or below 150 cp. Less severe than a blunder, but still a meaningful error.</div>
      <div class="doc-formula">Mistakes = count of moves with 80 cp &lt; CP Loss ≤ 150 cp</div>
      <div class="doc-example">A move that loses half a pawn (80 cp) is a mistake. A move that loses a full pawn (100 cp) is also a mistake.</div>
      <div class="doc-source"><span>Stockfish engine</span></div>
    </div>

    <div class="doc-card">
      <div class="doc-card-name">Inaccuracies per Game</div>
      <div class="doc-card-def">Count of moves with a centipawn loss above 40 cp but at or below 80 cp. These are small but suboptimal decisions.</div>
      <div class="doc-formula">Inaccuracies = count of moves with 40 cp &lt; CP Loss ≤ 80 cp</div>
      <div class="doc-example">Slightly misjudging piece coordination and losing a third of a pawn's worth of advantage counts as an inaccuracy.</div>
      <div class="doc-source"><span>Stockfish engine</span></div>
    </div>

    <div class="doc-card">
      <div class="doc-card-name">Error Phase (Opening / Middlegame / Endgame)</div>
      <div class="doc-card-def">Each error is tagged with the phase of the game in which it occurred, based on the move number at the time of the mistake.</div>
      <div class="doc-formula">Opening: moves 1–10 &nbsp;·&nbsp; Middlegame: moves 11–30 &nbsp;·&nbsp; Endgame: move 31+</div>
      <div class="doc-example">A blunder on move 8 is tagged "Opening". A blunder on move 25 is tagged "Middlegame". The "Blunders by Phase" chart shows how your mistakes are distributed across these three stages.</div>
      <div class="doc-source"><span>Stockfish engine</span></div>
    </div>

    <div class="doc-card">
      <div class="doc-card-name">Avg 1st Blunder Move</div>
      <div class="doc-card-def">The average move number at which you make your first blunder in a game. A higher number means you tend to stay clean longer before cracking.</div>
      <div class="doc-formula">First Blunder Move = the move number of the earliest blunder in a game<br>Average = mean across all games that had at least one blunder</div>
      <div class="doc-example">In 5 games your first blunders occurred on moves 12, 18, 9, 24, and 15. Average = (12+18+9+24+15) ÷ 5 = 15.6</div>
      <div class="doc-source"><span>Stockfish engine</span></div>
    </div>

  </div>
</div>

<!-- ── 3. Tactic Types ────────────────────────────────────────────────────── -->
<div class="doc-section" id="doc-tactics">
  <div class="doc-section-title">🧩 Tactic Types (Missed Tactics)</div>

  <div class="doc-card" style="margin-bottom:16px">
    <div class="doc-card-def">
      When you blunder, ChessVision automatically analyses <em>why</em> the move was bad by
      inspecting the board position. Each blunder is classified into one of the categories below.
      The "Missed Tactics" chart shows which patterns you miss most often.
    </div>
  </div>

  <div class="doc-grid">

    <div class="doc-card">
      <div class="doc-card-name">Hanging Piece</div>
      <div class="doc-card-def">You left a piece undefended (or moved away a defender), allowing your opponent to capture it for free.</div>
      <div class="doc-example">You move your bishop, accidentally leaving your knight attacked with no defender. Opponent takes it for free.</div>
    </div>

    <div class="doc-card">
      <div class="doc-card-name">Fork</div>
      <div class="doc-card-def">You made a move that allows the opponent to attack two of your pieces simultaneously with one of their pieces, and you can only save one.</div>
      <div class="doc-example">Opponent plays Nd5 — the knight attacks both your queen and your rook at the same time. You can only move one of them.</div>
    </div>

    <div class="doc-card">
      <div class="doc-card-name">Pin</div>
      <div class="doc-card-def">You moved a piece that was shielding a more valuable piece behind it, creating a pin — the moved piece cannot safely move without exposing the piece behind it.</div>
      <div class="doc-example">Your knight is between your king and the opponent's bishop. Moving the knight exposes the king to check — the knight is pinned.</div>
    </div>

    <div class="doc-card">
      <div class="doc-card-name">Skewer</div>
      <div class="doc-card-def">Like a pin in reverse — a valuable piece is attacked and forced to move, exposing a less valuable piece behind it that gets captured.</div>
      <div class="doc-example">Opponent's rook attacks your queen. You move the queen to safety; now your rook behind it is captured.</div>
    </div>

    <div class="doc-card">
      <div class="doc-card-name">Discovered Attack</div>
      <div class="doc-card-def">You made a move that allowed the opponent to uncover an attack from a piece behind the piece that moved, hitting a target you did not see coming.</div>
      <div class="doc-example">Opponent moves a pawn, uncovering a bishop that now attacks your queen across the board.</div>
    </div>

    <div class="doc-card">
      <div class="doc-card-name">Forcing Check</div>
      <div class="doc-card-def">The best move was to give check, forcing the opponent into a specific response, but you missed it and played something else instead.</div>
      <div class="doc-example">Stockfish's best move was Qh5+ (check), which would have won material. You played a quiet move instead, missing the opportunity.</div>
    </div>

    <div class="doc-card">
      <div class="doc-card-name">Promotion</div>
      <div class="doc-card-def">You missed a move that would have promoted a pawn to a queen (or other piece), or you underestimated a promotion threat from your opponent.</div>
      <div class="doc-example">Your pawn was one square away from queening. Instead of advancing it, you played elsewhere — and lost the chance to promote.</div>
    </div>

    <div class="doc-card">
      <div class="doc-card-name">Checkmate Threat</div>
      <div class="doc-card-def">You missed that the opponent had a checkmate threat, or you failed to play a move that would have delivered checkmate or set up an unavoidable mating net.</div>
      <div class="doc-example">Stockfish shows Qg7# (checkmate in one). You played a different move and the moment was lost.</div>
    </div>

    <div class="doc-card">
      <div class="doc-card-name">Positional</div>
      <div class="doc-card-def">The blunder doesn't fit a specific tactical pattern — it was a strategic or positional mistake such as weakening your king, trading pieces unfavourably, or mishandling pawn structure.</div>
      <div class="doc-example">You exchanged your good bishop for the opponent's bad bishop, weakening your position long-term. No single tactic caused the loss — it was a strategic misjudgement.</div>
    </div>

  </div>
</div>

<!-- ── 4. Opening Metrics ─────────────────────────────────────────────────── -->
<div class="doc-section" id="doc-openings">
  <div class="doc-section-title">♟️ Opening Metrics</div>
  <div class="doc-grid">

    <div class="doc-card">
      <div class="doc-card-name">Opening Name &amp; ECO Code</div>
      <div class="doc-card-def">The name and classification code (from the Encyclopaedia of Chess Openings) of the opening you played. These are read directly from the tags Chess.com attaches to each game's PGN file.</div>
      <div class="doc-example">ECO "B13" → Caro-Kann Defence, Exchange Variation. Each letter+number combination uniquely identifies an opening line.</div>
      <div class="doc-source"><span>Chess.com API</span></div>
    </div>

    <div class="doc-card">
      <div class="doc-card-name">Theory Depth</div>
      <div class="doc-card-def">The number of moves (half-moves / plies) that are considered "book" theory in this opening, according to the Chess.com opening classification URL. Moves up to this depth are shown in blue on the opening board; moves after it are in orange (your own continuation).</div>
      <div class="doc-formula">Extracted from the Chess.com ECOUrl tag in the PGN — e.g. "…-with-1-e4-c5-2.Nf3-3.d4" → 3 moves of theory</div>
      <div class="doc-example">The Sicilian Dragon has 7 moves of established theory. If you deviated on move 4, the board shows moves 1–7 in blue and your move 4 in orange.</div>
      <div class="doc-source"><span>Chess.com API</span></div>
    </div>

    <div class="doc-card">
      <div class="doc-card-name">Win % by Opening</div>
      <div class="doc-card-def">Your win rate specifically within a given opening, letting you identify which openings you perform best and worst in.</div>
      <div class="doc-formula">Opening Win % = (Wins in this opening ÷ Games played in this opening) × 100</div>
      <div class="doc-example">You played the Caro-Kann 20 times, winning 12 → Win % = 60%. Across all openings your win rate is 50%, so Caro-Kann is above average for you.</div>
      <div class="doc-source"><span>Chess.com API + Stockfish</span></div>
    </div>

    <div class="doc-card">
      <div class="doc-card-name">Avg Accuracy by Opening</div>
      <div class="doc-card-def">Your average Stockfish accuracy score for games played in a specific opening. Comparing this to your global average reveals openings where you play more or less precisely.</div>
      <div class="doc-formula">Mean of accuracy scores across all games in that opening</div>
      <div class="doc-example">Your global average accuracy is 83%. In the London System your average is 88% → you play it more confidently than your other openings.</div>
      <div class="doc-source"><span>Stockfish engine</span></div>
    </div>

    <div class="doc-card">
      <div class="doc-card-name">Avg Theory Depth (opening table)</div>
      <div class="doc-card-def">Across all your games in a given opening, the average number of moves that fell within known book theory before you deviated. A higher number means you tend to follow established lines longer.</div>
      <div class="doc-formula">Mean of theory_depth across all games in that opening</div>
      <div class="doc-example">In 10 Ruy Lopez games you deviated from theory on moves 4, 5, 6, 4, 7, 5, 4, 6, 5, 5. Average = 5.1 moves of theory followed.</div>
      <div class="doc-source"><span>Chess.com API</span></div>
    </div>

    <div class="doc-card">
      <div class="doc-card-name">Avg First Error Move (by opening)</div>
      <div class="doc-card-def">On average, at which move number do you make your first blunder when playing a particular opening? Helps identify openings where you lose the thread early.</div>
      <div class="doc-formula">Mean of the first-blunder move number across all games in that opening where a blunder occurred</div>
      <div class="doc-example">In the King's Indian you consistently blunder around move 14, vs. move 22 in the Slav — suggesting you are less comfortable in the King's Indian middlegame.</div>
      <div class="doc-source"><span>Stockfish engine</span></div>
    </div>

    <div class="doc-card">
      <div class="doc-card-name">Top Blunder Type (by opening)</div>
      <div class="doc-card-def">The most frequently missed tactic across all blunders made in a given opening. Tells you the specific weakness that opening tends to expose in your play.</div>
      <div class="doc-formula">Mode of tactic_type among all blunders in that opening</div>
      <div class="doc-example">In the French Defence, 7 of your 11 blunders are "Hanging Piece" → you need to be more careful about undefended pieces in this structure.</div>
      <div class="doc-source"><span>Stockfish engine</span></div>
    </div>

    <div class="doc-card">
      <div class="doc-card-name">Avg Game Length (by opening)</div>
      <div class="doc-card-def">The average total number of moves (both players combined) in games where this opening was played. Some openings lead to quick tactical games; others to long positional battles.</div>
      <div class="doc-formula">Mean of total move counts across all games in that opening</div>
      <div class="doc-example">Your King's Gambit games last an average of 28 moves; your Queen's Gambit Declined games average 52 moves.</div>
      <div class="doc-source"><span>Chess.com API</span></div>
    </div>

  </div>
</div>

<!-- ── 5. Opponent Metrics ─────────────────────────────────────────────────── -->
<div class="doc-section" id="doc-opponent">
  <div class="doc-section-title">👤 Opponent Metrics</div>
  <div class="doc-grid">

    <div class="doc-card">
      <div class="doc-card-name">Opponent ELO</div>
      <div class="doc-card-def">The Elo rating of your opponent at the time the game was played. Elo is a number that represents playing strength — a higher number means a stronger player. It is shown in the Games table so you can see which results came against stronger or weaker opposition.</div>
      <div class="doc-example">A win against a 1600-rated opponent is more meaningful than a win against a 900-rated player, even if both count as one win.</div>
      <div class="doc-source"><span>Chess.com API</span></div>
    </div>

    <div class="doc-card">
      <div class="doc-card-name">Opponent Blunders / Game</div>
      <div class="doc-card-def">The average number of blunder-level mistakes your opponents made per game. Stockfish analyses both sides of every game. A high opponent blunder rate can explain wins that were gifted rather than earned.</div>
      <div class="doc-formula">Opponent Blunders/Game = Total opponent blunders ÷ Number of games</div>
      <div class="doc-example">If opponents averaged 3.0 blunders/game while you averaged 1.5, many of your wins may have come from opponent errors rather than superior play.</div>
      <div class="doc-source"><span>Stockfish engine</span></div>
    </div>

    <div class="doc-card">
      <div class="doc-card-name">Opponent Mistakes &amp; Inaccuracies</div>
      <div class="doc-card-def">Same as your own mistake and inaccuracy counts, but calculated for the opponent's moves. Shown in the Move Quality table alongside your own figures for direct comparison.</div>
      <div class="doc-formula">Same thresholds: mistakes &gt;80 cp, inaccuracies &gt;40 cp — applied to opponent moves</div>
      <div class="doc-example">If your opponents average 1.2 mistakes/game and you average 2.1, you are making proportionally more mistakes than your opponents at your current level.</div>
      <div class="doc-source"><span>Stockfish engine</span></div>
    </div>

    <div class="doc-card">
      <div class="doc-card-name">% Games Ended by Checkmate</div>
      <div class="doc-card-def">The proportion of games that ended with checkmate (rather than resignation or time forfeit). Shown in the Openings tab error section to reveal how often games in a given opening reach a forced conclusion.</div>
      <div class="doc-formula">(Games with termination = "checkmate" ÷ Total games in opening) × 100</div>
      <div class="doc-example">In your King's Gambit games, 40% end by checkmate — meaning tactical, decisive games. In the Queen's Gambit Declined, only 5% end by checkmate.</div>
      <div class="doc-source"><span>Chess.com API</span></div>
    </div>

  </div>
</div>

<!-- ── 6. Pattern Analysis Metrics ───────────────────────────────────────── -->
<div class="doc-section" id="doc-patterns">
  <div class="doc-section-title">⚡ Pattern Analysis Metrics</div>

  <div class="doc-card" style="margin-bottom:16px">
    <div class="doc-card-def">
      The ⚡ Patterns tab identifies <strong>recurring mistakes</strong> — situations where you made
      the same bad move (same UCI move code) in the same opening, across two or more different games.
      These are your <em>true blind spots</em>: not random errors, but systematic habits that cost you
      material repeatedly.
    </div>
  </div>

  <div class="doc-grid">

    <div class="doc-card">
      <div class="doc-card-name">Recurring Patterns (count)</div>
      <div class="doc-card-def">The total number of distinct (opening + bad move) combinations that appeared in at least 2 different games. Each unique pattern represents a habit worth fixing.</div>
      <div class="doc-formula">Count of unique (opening_name, bad_move_uci) pairs with occurrence count ≥ 2</div>
      <div class="doc-example">If you played e5 as a bad move in the London System 3 times and castled prematurely in the Caro-Kann twice, that is 2 distinct patterns.</div>
      <div class="doc-source"><span>Stockfish engine + Chess.com API</span></div>
    </div>

    <div class="doc-card">
      <div class="doc-card-name">Total Occurrences</div>
      <div class="doc-card-def">The sum of all times a recurring pattern was triggered across your games. If you have 5 patterns that happened 2, 3, 2, 4, and 2 times respectively, the total is 13 occurrences.</div>
      <div class="doc-formula">Total Occurrences = sum of (count) for each pattern</div>
      <div class="doc-example">12 patterns × average 2.5 occurrences each = 30 total occurrences of recurring mistakes.</div>
      <div class="doc-source"><span>Stockfish engine</span></div>
    </div>

    <div class="doc-card">
      <div class="doc-card-name">Avg CP Loss / Pattern</div>
      <div class="doc-card-def">The average centipawn loss per pattern, averaged across all patterns. Patterns with higher CP loss are more costly and should be prioritised.</div>
      <div class="doc-formula">Avg CP Loss / Pattern = mean of (avg_cp_loss) across all recurring patterns</div>
      <div class="doc-example">Pattern A costs −200 cp on average, pattern B costs −100 cp. Avg CP Loss = (200 + 100) ÷ 2 = 150 cp per pattern.</div>
      <div class="doc-source"><span>Stockfish engine</span></div>
    </div>

    <div class="doc-card">
      <div class="doc-card-name">Pattern Occurrence Count (×N)</div>
      <div class="doc-card-def">The number shown on each pattern card (e.g. "3×") is how many times you played that specific bad move in that specific opening across all your games.</div>
      <div class="doc-example">"5×" on a pattern card means you played that exact mistake in that opening five separate times across five different games.</div>
      <div class="doc-source"><span>Stockfish engine</span></div>
    </div>

    <div class="doc-card">
      <div class="doc-card-name">Pattern Avg CP Loss (−N cp)</div>
      <div class="doc-card-def">For each individual pattern, the average centipawn loss each time you made that specific mistake. It is the mean of the Stockfish-measured loss across all occurrences of that pattern.</div>
      <div class="doc-formula">Avg CP Loss for pattern = sum of CP Loss across all occurrences ÷ number of occurrences</div>
      <div class="doc-example">You played Nf6 badly 3 times in the Caro-Kann, losing 120 cp, 180 cp, and 150 cp each time. Avg CP Loss = (120+180+150) ÷ 3 = 150 cp.</div>
      <div class="doc-source"><span>Stockfish engine</span></div>
    </div>

    <div class="doc-card">
      <div class="doc-card-name">Your Move (✗) vs Best Move (✓)</div>
      <div class="doc-card-def">Each pattern card shows the move you repeatedly played (in red, marked ✗) and the move Stockfish considers best in that position (in green, marked ✓). The arrows on the mini board visually show both moves.</div>
      <div class="doc-formula">Your move = the bad UCI move you played most often in this pattern<br>Best move = the most common Stockfish recommendation across all occurrences</div>
      <div class="doc-example">✗ e5 (your move, costs −200 cp) → ✓ dxe4 (Stockfish best, would have maintained equality)</div>
      <div class="doc-source"><span>Stockfish engine</span></div>
    </div>

  </div>
</div>

<!-- ── 7. Critical Patterns ───────────────────────────────────────────────── -->
<div class="doc-section" id="doc-critical">
  <div class="doc-section-title">🔍 Critical Patterns (Dashboard)</div>
  <div class="doc-grid">

    <div class="doc-card">
      <div class="doc-card-name">Games Lost After Exactly 1 Blunder</div>
      <div class="doc-card-def">The percentage of your losses that occurred in games where you made only one blunder. This reveals how often a single mistake is decisive — i.e. you were otherwise playing well but one error cost you the game.</div>
      <div class="doc-formula">(Games where blunders = 1 AND outcome = loss) ÷ Total games × 100</div>
      <div class="doc-example">Out of 100 games, 15 were losses where you made exactly 1 blunder → 15%. This suggests that eliminating just one blunder type could save many games.</div>
      <div class="doc-source"><span>Stockfish engine + Chess.com API</span></div>
    </div>

    <div class="doc-card">
      <div class="doc-card-name">Winning Positions Converted</div>
      <div class="doc-card-def">Among games where you held a clearly winning advantage at some point (Stockfish evaluation ≥ +200 cp in your favour), the percentage you actually went on to win. A low score means you struggle to convert advantages.</div>
      <div class="doc-formula">(Games won where you had a +200 cp advantage at some point) ÷ (Games where you had a +200 cp advantage) × 100</div>
      <div class="doc-example">In 20 games you reached a +200 cp winning position. You converted 14 of them → Conversion rate = 70%.</div>
      <div class="doc-source"><span>Stockfish engine</span></div>
    </div>

    <div class="doc-card">
      <div class="doc-card-name">Blunders with King Unsafe</div>
      <div class="doc-card-def">The percentage of your blunders that happened when your king was in a vulnerable position (not fully castled and sheltered). Highlights whether king safety issues contribute to your errors.</div>
      <div class="doc-formula">(Blunders where king_unsafe = true) ÷ Total blunders × 100</div>
      <div class="doc-example">30 of your 80 blunders happened when your king was exposed → 37.5%. Prioritising king safety could reduce your blunder rate significantly.</div>
      <div class="doc-source"><span>Stockfish engine</span></div>
    </div>

    <div class="doc-card">
      <div class="doc-card-name">Win Rate Trend (by opening)</div>
      <div class="doc-card-def">A chronological chart of your results in a specific opening, showing how your win/loss record evolves over time. An upward trend means you are improving in that opening; a flat or downward trend means you have stagnated.</div>
      <div class="doc-formula">For each game (sorted by date): 1 = Win, 0 = Loss/Draw. Plotted as a line chart.</div>
      <div class="doc-example">Your last 10 Sicilian games: L, L, W, L, W, W, W, W, W, W → clear improvement trend over time.</div>
      <div class="doc-source"><span>Chess.com API + Stockfish</span></div>
    </div>

  </div>
</div>

</div>
</div><!-- /page-docs -->

<script>
// \u2500\u2500 Injected data \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
const perGameData      = {per_game_js_data};
const allOpeningData   = {opening_js_data};
const openingMovesData = {opening_moves_js};
const patternsData     = {patterns_js};

// \u2500\u2500 Color constants \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
const C_WIN='{C_WIN}', C_LOSS='{C_LOSS}', C_DRAW='{C_DRAW}';
const C_MIST='{C_MIST}', C_INACC='{C_INACC}', C_GRID='{C_GRID}';
const MIN_GAMES = {min_games};

// \u2500\u2500 Chart registry \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
let _charts = {{}};
function _mkChart(id, cfg) {{
  if (_charts[id]) {{ _charts[id].destroy(); delete _charts[id]; }}
  const el = document.getElementById(id);
  if (el) _charts[id] = new Chart(el, cfg);
}}

// \u2500\u2500 Shared chart helpers \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
function _hBar(id, labels, values, colors) {{
  _mkChart(id, {{
    type: 'bar',
    data: {{ labels, datasets: [{{ data: values, backgroundColor: colors, borderRadius: 4 }}] }},
    options: {{
      indexAxis:'y', responsive:true, animation:false,
      plugins: {{ legend:{{display:false}}, tooltip:{{callbacks:{{label: c=>' '+c.parsed.x}}}} }},
      scales: {{ x:{{ticks:{{color:'#a0a0c0'}},grid:{{color:C_GRID}}}}, y:{{ticks:{{color:'#a0a0c0'}},grid:{{display:false}}}} }}
    }}
  }});
}}
function _vBar(id, labels, values, colors) {{
  _mkChart(id, {{
    type: 'bar',
    data: {{ labels, datasets: [{{ data: values, backgroundColor: colors, borderRadius: 4 }}] }},
    options: {{
      responsive:true, animation:false,
      plugins: {{ legend:{{display:false}} }},
      scales: {{ x:{{ticks:{{color:'#a0a0c0'}},grid:{{display:false}}}}, y:{{ticks:{{color:'#a0a0c0'}},grid:{{color:C_GRID}}}} }}
    }}
  }});
}}

// \u2500\u2500 Table sort \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
function sortTable(tableId, colIdx) {{
  const table = document.getElementById(tableId);
  if (!table) return;
  const tbody = table.tBodies[0];
  const th    = table.tHead.rows[0].cells[colIdx];
  const asc   = !th.classList.contains('sort-asc');
  Array.from(table.tHead.rows[0].cells).forEach(c => c.classList.remove('sort-asc','sort-desc'));
  th.classList.add(asc ? 'sort-asc' : 'sort-desc');
  const rows = Array.from(tbody.rows);
  rows.sort((a, b) => {{
    const av = a.cells[colIdx]?.textContent.trim() || '';
    const bv = b.cells[colIdx]?.textContent.trim() || '';
    const an = parseFloat(av), bn = parseFloat(bv);
    if (!isNaN(an) && !isNaN(bn)) return asc ? an-bn : bn-an;
    return asc ? av.localeCompare(bv) : bv.localeCompare(av);
  }});
  rows.forEach(r => tbody.appendChild(r));
}}

// \u2500\u2500 Helpers \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
function _isWin(g)  {{ return (g.player_color==='white'&&g.result==='1-0')||(g.player_color==='black'&&g.result==='0-1'); }}
function _isLoss(g) {{ return (g.player_color==='white'&&g.result==='0-1')||(g.player_color==='black'&&g.result==='1-0'); }}

function _getSubset(colorF, catF) {{
  const fc = colorF !== undefined ? colorF : (document.getElementById('gColorFilter')||{{}}).value||'';
  const ft = catF   !== undefined ? catF   : (document.getElementById('gCategoryFilter')||{{}}).value||'';
  return perGameData.filter(g =>
    (!fc || g.player_color===fc) &&
    (!ft || g.category===ft)
  );
}}

function _getOpSubset(opName, colorF, catF) {{
  const base = _getSubset(colorF, catF);
  return base.filter(g => g.opening_name === opName);
}}

// \u2500\u2500 Page navigation \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
let _activePage = 'dashboard';
function showPage(name) {{
  _activePage = name;
  document.querySelectorAll('.page-content').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.ptab').forEach(b => b.classList.remove('active'));
  const pg = document.getElementById('page-'+name);
  if (pg) pg.classList.add('active');
  const btn = document.getElementById('ptab-'+name);
  if (btn) btn.classList.add('active');
  applyFilters();
}}

// \u2500\u2500 Master filter dispatch \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
function applyFilters() {{
  const sub = _getSubset();
  if (_activePage === 'dashboard') {{
    _updateDashboard(sub);
  }} else if (_activePage === 'openings') {{
    openingTabUpdate();
  }} else if (_activePage === 'games') {{
    _updateGamesPage(sub);
  }} else if (_activePage === 'patterns') {{
    _updatePatternsPage();
  }}
  const el = document.getElementById('gFilterCount');
  if (el) el.textContent = sub.length + ' games';
}}

// \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
// DASHBOARD
// \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
function _updateDashboard(sub) {{
  _updateDashCards(sub);
  _updateDashMoveQuality(sub);
  _updateDashCharts(sub);
  _updateDashCritical(sub);
  const tabs = {categories_js};
  for (const t of tabs) {{
    const el = document.getElementById('tab-'+t);
    const capT = t.charAt(0).toUpperCase()+t.slice(1);
    if (el && !el.textContent.includes('No '+capT)) {{ switchTab(t); break; }}
  }}
  if (!document.querySelector('#dashTcTabBtns .tab-btn.active') && tabs.length) switchTab(tabs[0]);
}}

function switchTab(name) {{
  document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  const el = document.getElementById('tab-' + name);
  if (el) el.classList.add('active');
  const btn = Array.from(document.querySelectorAll('.tab-btn')).find(b => b.textContent.toLowerCase() === name);
  if (btn) btn.classList.add('active');
}}

function _updateDashCards(sub) {{
  const el = document.getElementById('dashStatCards');
  if (!el) return;
  const n = sub.length;
  if (n===0) {{ el.innerHTML='<div class="card"><div class="value">\u2014</div><div class="label">No matching games</div></div>'; return; }}
  let w=0,l=0,d=0,accS=0,accN=0,blu=0;
  for (const g of sub) {{
    if (_isWin(g)) w++; else if (_isLoss(g)) l++; else d++;
    if (g.accuracy>0) {{ accS+=g.accuracy; accN++; }}
    blu+=g.blunders;
  }}
  const avgAcc = accN ? (accS/accN).toFixed(1)+'%' : 'N/A';
  el.innerHTML = `
    <div class="card blue"><div class="value">${{n}}</div><div class="label">Games</div></div>
    <div class="card"><div class="value" style="color:${{C_WIN}}">${{w}}</div><div class="label">Wins (${{n?(w/n*100).toFixed(1):0}}%)</div></div>
    <div class="card red"><div class="value">${{l}}</div><div class="label">Losses (${{n?(l/n*100).toFixed(1):0}}%)</div></div>
    <div class="card blue"><div class="value">${{d}}</div><div class="label">Draws (${{n?(d/n*100).toFixed(1):0}}%)</div></div>
    <div class="card blue"><div class="value">${{avgAcc}}</div><div class="label">Avg Accuracy</div></div>
    <div class="card red"><div class="value">${{n?(blu/n).toFixed(2):0}}</div><div class="label">Avg Blunders/Game</div></div>`;
}}

function _updateDashMoveQuality(sub) {{
  const n = sub.length;
  if (!n) return;
  let myBlu=0,myMist=0,myInacc=0,oppBlu=0,oppMist=0,oppInacc=0;
  for (const g of sub) {{
    myBlu+=g.blunders; myMist+=g.mistakes; myInacc+=g.inaccuracies;
    oppBlu+=g.opp_blunders; oppMist+=g.opp_mistakes; oppInacc+=g.opp_inaccuracies;
  }}
  const set = (id,v) => {{ const el=document.getElementById(id); if(el) el.textContent=v; }};
  set('dashMyBlu',   (myBlu/n).toFixed(2));
  set('dashMyMist',  (myMist/n).toFixed(2));
  set('dashMyInacc', (myInacc/n).toFixed(2));
  set('dashOppBlu',  (oppBlu/n).toFixed(2));
  set('dashOppMist', (oppMist/n).toFixed(2));
  set('dashOppInacc',(oppInacc/n).toFixed(2));
}}

function _updateDashCharts(sub) {{
  let blu=0, mist=0, inacc=0, bOpen=0, bMid=0, bEnd=0;
  const tCounts={{}};
  for (const g of sub) {{
    blu+=g.blunders; mist+=g.mistakes; inacc+=g.inaccuracies;
    for (const ph of (g.blunder_phases||[])) {{
      if (ph==='opening') bOpen++; else if (ph==='middlegame') bMid++; else bEnd++;
    }}
    for (const t of (g.tactic_types||[])) tCounts[t]=(tCounts[t]||0)+1;
  }}
  _mkChart('dashDonut', {{
    type:'doughnut',
    data: {{ labels:['Blunders','Mistakes','Inaccuracies'], datasets:[{{data:[blu,mist,inacc],backgroundColor:[C_LOSS,C_MIST,C_INACC],borderColor:'#1a1a2e',borderWidth:3}}] }},
    options: {{responsive:true,animation:false,plugins:{{legend:{{labels:{{color:'#ffffff'}}}}}}}}
  }});
  _vBar('dashPhase',['Opening','Middlegame','Endgame'],[bOpen,bMid,bEnd],[C_INACC,C_MIST,C_LOSS]);
  const tL=Object.keys(tCounts), tV=Object.values(tCounts);
  _vBar('dashTactics', tL.length?tL:['None'], tV.length?tV:[0], C_WIN);
}}

function _updateDashCritical(sub) {{
  const n = sub.length;
  if (!n) return;
  let lost1=0;
  for (const g of sub) if (g.blunders===1 && _isLoss(g)) lost1++;
  const set = (id,v) => {{ const el=document.getElementById(id); if(el) el.textContent=v; }};
  set('dashCrit1', (lost1/n*100).toFixed(1)+'%');
  const fes = sub.filter(g=>g.first_error_move!=null).map(g=>g.first_error_move);
  set('dashCrit3', fes.length ? (fes.reduce((a,b)=>a+b,0)/fes.length).toFixed(1) : 'N/A');
}}

// \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
// OPENINGS PAGE
// \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
let _opName    = null;
let _opStep    = 0;
let _opFlipped = false;

const WP = {{'K':'\u2654','Q':'\u2655','R':'\u2656','B':'\u2657','N':'\u2658','P':'\u2659'}};
const BP = {{'K':'\u265a','Q':'\u265b','R':'\u265c','B':'\u265d','N':'\u265e','P':'\u265f'}};

function _fenToGrid(fen) {{
  return fen.split(' ')[0].split('/').map(row => {{
    const cells = [];
    for (const ch of row) {{
      if (/\d/.test(ch)) for (let i=0;i<+ch;i++) cells.push('');
      else cells.push(ch);
    }}
    return cells;
  }});
}}

function _drawBoard(fen, fromSq, toSq, inTheory) {{
  // Highlight color: blue for book theory moves, yellow for game continuation
  const hlColor = inTheory === false
    ? 'rgba(253,203,110,0.85)'   // game-only: yellow
    : 'rgba(255,220,0,0.9)';     // theory / unknown: gold
  const grid  = _fenToGrid(fen);
  const files = _opFlipped ? 'hgfedcba' : 'abcdefgh';
  const ranks = _opFlipped ? [1,2,3,4,5,6,7,8] : [8,7,6,5,4,3,2,1];
  const rl = document.getElementById('opRankLabels');
  const fl = document.getElementById('opFileLabels');
  if (rl) rl.innerHTML = ranks.map(r=>`<span>${{r}}</span>`).join('');
  if (fl) fl.innerHTML = Array.from(files).map(f=>`<span>${{f}}</span>`).join('');
  let html = '';
  for (const rank of ranks) {{
    for (const file of Array.from(files)) {{
      const c = 'abcdefgh'.indexOf(file);
      const r = 8 - rank;
      const light = (r + c) % 2 === 0;
      const piece = grid[r][c];
      const sq    = file + rank;
      const hl    = sq===fromSq || sq===toSq;
      let pieceHtml = '';
      if (piece) {{
        const isW = piece === piece.toUpperCase();
        const glyph = isW ? WP[piece] : BP[piece.toUpperCase()];
        pieceHtml = `<span class="${{isW?'cb-wp':'cb-bp'}}">${{glyph}}</span>`;
      }}
      const hlStyle = hl ? ` style="outline:4px solid ${{hlColor}};outline-offset:-4px"` : '';
      html += `<div class="cb-sq ${{light?'cb-light':'cb-dark'}}"${{hlStyle}}>${{pieceHtml}}</div>`;
    }}
  }}
  const board = document.getElementById('opBoard');
  if (board) board.innerHTML = html;
}}

function _renderOpMoveList(steps, curIdx) {{
  const data = openingMovesData[_opName];
  const hasTheory = data && data.theory_depth > 0;
  let html = '';
  let mn = 1, i = 1;
  let shownTheoryLabel = false, shownGameLabel = false;

  while (i < steps.length) {{
    const ws = steps[i];
    const bs = i+1 < steps.length ? steps[i+1] : null;

    // Insert section labels when crossing the theory/game boundary
    if (hasTheory) {{
      if (!shownTheoryLabel && ws.in_theory) {{
        html += `<div class="cb-section-label theory-lbl">&#9679; Book theory</div>`;
        shownTheoryLabel = true;
      }}
      if (!shownGameLabel && !ws.in_theory) {{
        html += `<div class="cb-section-label game-lbl">&#9679; Game continuation</div>`;
        shownGameLabel = true;
      }}
    }}

    const wTheory = hasTheory ? (ws.in_theory ? ' theory' : ' game-only') : '';
    const bTheory = (bs && hasTheory) ? (bs.in_theory ? ' theory' : ' game-only') : '';
    const wCls = (i===curIdx ? 'cb-mv cur' : 'cb-mv') + wTheory;
    const bCls = (bs && i+1===curIdx ? 'cb-mv cur' : 'cb-mv') + bTheory;

    html += `<div class="cb-pair">`;
    html += `<span class="cb-mn">${{mn}}.</span>`;
    html += `<span class="${{wCls}}" onclick="_opGoTo(${{i}})">${{ws.san}}</span>`;
    if (bs) html += `<span class="${{bCls}}" onclick="_opGoTo(${{i+1}})">${{bs.san}}</span>`;
    html += `</div>`;
    mn++; i += 2;
  }}
  const ml = document.getElementById('opMoveList');
  if (ml) {{
    ml.innerHTML = html || '<span style="color:#a0a0c0">No moves</span>';
    const cur = ml.querySelector('.cb-mv.cur');
    if (cur) cur.scrollIntoView({{block:'nearest'}});
  }}
}}

function _refreshOpBoard() {{
  if (!_opName || !openingMovesData[_opName]) return;
  const data  = openingMovesData[_opName];
  const step  = data.steps[_opStep];
  const total = data.steps.length - 1;
  const stepEl = document.getElementById('opStep');
  if (stepEl) {{
    let label = '';
    if (_opStep === 0) {{
      label = 'Starting position';
    }} else if (data.theory_depth > 0) {{
      const inTheory = step.in_theory;
      const prefix   = inTheory ? '&#9670; Theory' : '&#9670; Game';
      label = `${{prefix}} &mdash; move ${{_opStep}} / ${{total}}`;
    }} else {{
      label = `Move ${{_opStep}} / ${{total}}`;
    }}
    stepEl.innerHTML = label;
  }}
  _drawBoard(step.fen, step.from, step.to, step.in_theory);
  _renderOpMoveList(data.steps, _opStep);
}}

function opPrev()  {{ if (_opStep > 0) {{ _opStep--; _refreshOpBoard(); }} }}
function opNext()  {{ const d=openingMovesData[_opName]; if(d&&_opStep<d.steps.length-1){{_opStep++;_refreshOpBoard();}} }}
function opStart() {{ _opStep=0; _refreshOpBoard(); }}
function opEnd()   {{ const d=openingMovesData[_opName]; if(d){{_opStep=d.steps.length-1;_refreshOpBoard();}} }}
function opFlip()  {{ _opFlipped=!_opFlipped; _refreshOpBoard(); }}
function _opGoTo(i){{ _opStep=i; _refreshOpBoard(); }}

function _updateOpBoardTheory(opName) {{
  if (!opName || !openingMovesData[opName]) return;
  const data    = openingMovesData[opName];
  _opName       = opName;
  _opStep       = data.theory_depth > 0 ? data.theory_depth * 2 : data.steps.length - 1;
  _opStep       = Math.min(_opStep, data.steps.length - 1);
  _refreshOpBoard();

  // Theory depth box
  const theoryMoves = data.theory_depth;
  const numEl  = document.getElementById('opTheoryNum');
  const barEl  = document.getElementById('opTheoryBar');
  const noteEl = document.getElementById('opTheoryNote');
  const sub    = perGameData.filter(g=>g.opening_name===opName);
  const avgLen = sub.length ? Math.round(sub.reduce((a,g)=>a+g.num_moves,0)/sub.length) : 40;
  if (theoryMoves > 0) {{
    if (numEl) numEl.textContent = theoryMoves;
    const pct = Math.min(100, Math.round(theoryMoves/Math.max(avgLen,1)*100));
    if (barEl) barEl.style.width = pct+'%';
    if (noteEl) noteEl.textContent = `${{pct}}% of avg game length (${{avgLen}} moves)`;
  }} else {{
    if (numEl) numEl.textContent = '—';
    if (barEl) barEl.style.width = '0%';
    if (noteEl) noteEl.textContent = 'No ECO theory line available';
  }}

  // Move sequence text (theory part only, or all steps if no theory)
  const seqEl = document.getElementById('opMoveSeq');
  if (seqEl) {{
    const limit = theoryMoves > 0 ? theoryMoves * 2 : data.steps.length;
    let txt = '';
    let mn = 1;
    for (let i=1; i<data.steps.length && i<=limit; i++) {{
      if ((i-1)%2===0) txt += mn + '. ';
      txt += data.steps[i].san + ' ';
      if ((i-1)%2===1) mn++;
    }}
    seqEl.textContent = txt.trim() || '\u2014';
  }}

  // Show/hide legend based on whether there is a theory/game split
  const legendEl = document.getElementById('opLegend');
  if (legendEl) legendEl.style.display = theoryMoves > 0 ? '' : 'none';
}}

function _loadOpening(name) {{
  const sel = document.getElementById('opTabSel');
  if (sel) sel.value = name;
  openingTabUpdate();
}}

function openingTabUpdate() {{
  const sel = document.getElementById('opTabSel');
  const opName = sel ? sel.value : '';
  if (!opName) return;
  const colorF = (document.getElementById('gColorFilter')||{{}}).value||'';
  const catF   = (document.getElementById('gCategoryFilter')||{{}}).value||'';
  const allSub = _getSubset(colorF, catF);
  const opSub  = _getOpSubset(opName, colorF, catF);
  _updateOpBadges(opSub, opName);
  _updateOpBoardTheory(opName);
  _updateOpStats(opSub, allSub);
  _updateOpTc(opSub);
  _updateOpTrends(opSub);
  _updateOpErrors(opSub, allSub);
  _updateOpSummary(allSub);
}}

function _updateOpBadges(opSub, opName) {{
  const data = openingMovesData[opName];
  const eco  = data ? data.eco : '\u2014';
  const ecoBadge   = document.getElementById('opEcoBadge');
  const gamesBadge = document.getElementById('opGamesBadge');
  if (ecoBadge)   ecoBadge.textContent   = 'ECO ' + eco;
  if (gamesBadge) gamesBadge.textContent = opSub.length + ' games';
}}

function _updateOpStats(opSub, allSub) {{
  const tbody = document.getElementById('opCmpBody');
  if (!tbody) return;
  function metrics(sub) {{
    const n = sub.length;
    if (!n) return null;
    let w=0,d=0,l=0,accS=0,accN=0,blu=0,fe=[],td2=[],len=[];
    for (const g of sub) {{
      if (_isWin(g)) w++; else if (_isLoss(g)) l++; else d++;
      if (g.accuracy>0) {{ accS+=g.accuracy; accN++; }}
      blu+=g.blunders;
      if (g.first_error_move!=null) fe.push(g.first_error_move);
      if (g.theory_depth>0) td2.push(g.theory_depth);
      len.push(g.num_moves);
    }}
    return {{
      n, wPct:(w/n*100).toFixed(1), dPct:(d/n*100).toFixed(1), lPct:(l/n*100).toFixed(1),
      acc: accN?(accS/accN).toFixed(1):'N/A',
      blu: (blu/n).toFixed(2),
      fe:  fe.length?(fe.reduce((a,b)=>a+b,0)/fe.length).toFixed(1):'N/A',
      td:  td2.length?(td2.reduce((a,b)=>a+b,0)/td2.length).toFixed(1):'N/A',
      len: len.length?(len.reduce((a,b)=>a+b,0)/len.length).toFixed(0):'N/A'
    }};
  }}
  const op  = metrics(opSub);
  const all = metrics(allSub);
  if (!op || !all) {{ tbody.innerHTML='<tr><td colspan="3" style="color:#a0a0c0">Not enough data.</td></tr>'; return; }}
  const rows = [
    ['Win %',              op.wPct+'%',  all.wPct+'%'],
    ['Draw %',             op.dPct+'%',  all.dPct+'%'],
    ['Loss %',             op.lPct+'%',  all.lPct+'%'],
    ['Avg Accuracy',       op.acc+(op.acc!=='N/A'?'%':''), all.acc+(all.acc!=='N/A'?'%':'')],
    ['Avg Blunders/Game',  op.blu,       all.blu],
    ['Avg 1st Error Move', op.fe,        all.fe],
    ['Avg Theory Depth',   op.td,        all.td],
    ['Avg Game Length',    op.len,       all.len],
  ];
  tbody.innerHTML = rows.map(([m,a,b])=>`<tr><td>${{m}}</td><td>${{a}}</td><td>${{b}}</td></tr>`).join('');
}}

function _updateOpTc(opSub) {{
  const grid = document.getElementById('opTcGrid');
  if (!grid) return;
  const cats = ['Bullet','Blitz','Rapid','Classical'];
  let html = '';
  for (const cat of cats) {{
    const sub = opSub.filter(g=>g.category===cat);
    if (!sub.length) continue;
    let w=0,l=0,d=0;
    for (const g of sub) {{ if(_isWin(g)) w++; else if(_isLoss(g)) l++; else d++; }}
    html += `<div class="tc-card">
      <div class="tc-name">${{cat}}</div>
      <div class="tc-stat" style="color:${{C_WIN}}">${{w}}W</div>
      <div class="tc-stat" style="color:#a0a0c0">${{d}}D</div>
      <div class="tc-stat" style="color:${{C_LOSS}}">${{l}}L</div>
    </div>`;
  }}
  grid.innerHTML = html || '<span style="color:#a0a0c0">No data.</span>';
}}

function _updateOpTrends(opSub) {{
  let w=0,d=0,l=0;
  for (const g of opSub) {{ if(_isWin(g)) w++; else if(_isLoss(g)) l++; else d++; }}
  _mkChart('opWdlDonut', {{
    type:'doughnut',
    data: {{ labels:['Win','Draw','Loss'], datasets:[{{data:[w,d,l],backgroundColor:[C_WIN,C_DRAW,C_LOSS],borderColor:'#1a1a2e',borderWidth:3}}] }},
    options: {{responsive:true,animation:false,plugins:{{legend:{{labels:{{color:'#ffffff'}}}}}}}}
  }});
  const sorted = [...opSub].sort((a,b)=>a.date.localeCompare(b.date));
  const labels=[], vals=[];
  for (let i=0;i<sorted.length;i++) {{
    labels.push(sorted[i].date.slice(0,10));
    vals.push(_isWin(sorted[i])?1:0);
  }}
  _mkChart('opTrendChart', {{
    type:'line',
    data: {{ labels, datasets:[{{label:'Win',data:vals,borderColor:C_WIN,backgroundColor:'rgba(0,184,148,0.15)',fill:true,tension:0.3,pointRadius:3,borderWidth:2}}] }},
    options: {{
      responsive:true,animation:false,
      scales: {{ x:{{ticks:{{color:'#a0a0c0',maxTicksLimit:8}},grid:{{color:C_GRID}}}}, y:{{min:0,max:1,ticks:{{color:'#a0a0c0',callback:v=>v?'Win':'Loss'}},grid:{{color:C_GRID}}}} }},
      plugins: {{ legend:{{display:false}} }}
    }}
  }});
}}

function _updateOpErrors(opSub, allSub) {{
  const n = opSub.length;
  const errCards = document.getElementById('opErrCards');
  if (errCards && n>0) {{
    let blu=0, bOpen=0, bMid=0, bEnd=0;
    const tCounts={{}};
    let mates=0, oppBlu=0;
    const fe=[];
    for (const g of opSub) {{
      blu+=g.blunders; oppBlu+=g.opp_blunders;
      if (g.termination==='checkmate') mates++;
      if (g.first_error_move!=null) fe.push(g.first_error_move);
      for (const ph of (g.blunder_phases||[])) {{
        if (ph==='opening') bOpen++; else if (ph==='middlegame') bMid++; else bEnd++;
      }}
      for (const t of (g.tactic_types||[])) tCounts[t]=(tCounts[t]||0)+1;
    }}
    const topT = Object.keys(tCounts).length ? Object.keys(tCounts).sort((a,b)=>tCounts[b]-tCounts[a])[0] : 'N/A';
    const avgFe = fe.length ? (fe.reduce((a,b)=>a+b,0)/fe.length).toFixed(1) : 'N/A';
    errCards.innerHTML = `
      <div class="card orange"><div class="value">${{avgFe}}</div><div class="label">Avg 1st Blunder Move</div></div>
      <div class="card red"><div class="value">${{topT}}</div><div class="label">Top Missed Tactic</div></div>
      <div class="card blue"><div class="value">${{(mates/n*100).toFixed(0)}}%</div><div class="label">% Ended by Checkmate</div></div>
      <div class="card"><div class="value">${{(oppBlu/n).toFixed(2)}}</div><div class="label">Opp Blunders/Game</div></div>`;
    _vBar('opPhaseChart',   ['Opening','Middlegame','Endgame'],[bOpen,bMid,bEnd],[C_INACC,C_MIST,C_LOSS]);
    const tL=Object.keys(tCounts), tV=Object.values(tCounts);
    _vBar('opTacticsChart', tL.length?tL:['None'], tV.length?tV:[0], C_WIN);
  }}
}}

function _updateOpSummary(allSub) {{
  const tbody = document.getElementById('opSummaryBody');
  if (!tbody) return;
  const opMap={{}};
  for (const g of allSub) {{
    const k=g.opening_name;
    if (!opMap[k]) opMap[k]={{wins:0,total:0,eco:g.eco,accs:[],td:[],fe:[],tc:{{}}}};
    const m=opMap[k]; m.total++;
    if (_isWin(g)) m.wins++;
    if (g.accuracy>0) m.accs.push(g.accuracy);
    if (g.theory_depth>0) m.td.push(g.theory_depth);
    if (g.first_error_move!=null) m.fe.push(g.first_error_move);
    for (const t of (g.tactic_types||[])) m.tc[t]=(m.tc[t]||0)+1;
  }}
  const rows = Object.entries(opMap)
    .sort((a,b)=>b[1].total-a[1].total)
    .map(([name,m]) => {{
      const n=m.total;
      const wr=(m.wins/n*100).toFixed(1);
      const acc=m.accs.length?(m.accs.reduce((a,b)=>a+b,0)/m.accs.length).toFixed(1)+'%':'N/A';
      const td=m.td.length?(m.td.reduce((a,b)=>a+b,0)/m.td.length).toFixed(1):'N/A';
      const fe=m.fe.length?(m.fe.reduce((a,b)=>a+b,0)/m.fe.length).toFixed(1):'N/A';
      const topT=Object.keys(m.tc).length?Object.keys(m.tc).sort((a,b)=>m.tc[b]-m.tc[a])[0]:'N/A';
      const safeName=name.replace(/'/g,"\\'");
      return `<tr onclick="_loadOpening('${{safeName}}')" title="Click to load this opening">
        <td>${{name}}</td><td>${{m.eco}}</td><td>${{n}}</td>
        <td>${{wr}}%</td><td>${{acc}}</td><td>${{td}}</td><td>${{fe}}</td><td>${{topT}}</td>
      </tr>`;
    }});
  tbody.innerHTML = rows.length ? rows.join('') : '<tr><td colspan="8" style="color:#a0a0c0">No data.</td></tr>';
}}

// \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
// GAMES PAGE
// \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
function _updateGamesPage(sub) {{
  const el = document.getElementById('gamesStatCards');
  if (el) {{
    const n=sub.length;
    if (!n) {{ el.innerHTML='<div class="card"><div class="value">\u2014</div><div class="label">No matching games</div></div>'; }}
    else {{
      let w=0,l=0,d=0,accS=0,accN=0,blu=0;
      for (const g of sub) {{
        if (_isWin(g)) w++; else if (_isLoss(g)) l++; else d++;
        if (g.accuracy>0) {{ accS+=g.accuracy; accN++; }}
        blu+=g.blunders;
      }}
      const avgAcc = accN?(accS/accN).toFixed(1)+'%':'N/A';
      el.innerHTML = `
        <div class="card blue"><div class="value">${{n}}</div><div class="label">Games</div></div>
        <div class="card"><div class="value" style="color:${{C_WIN}}">${{w}}</div><div class="label">Wins (${{n?(w/n*100).toFixed(1):0}}%)</div></div>
        <div class="card red"><div class="value">${{l}}</div><div class="label">Losses (${{n?(l/n*100).toFixed(1):0}}%)</div></div>
        <div class="card blue"><div class="value">${{d}}</div><div class="label">Draws (${{n?(d/n*100).toFixed(1):0}}%)</div></div>
        <div class="card blue"><div class="value">${{avgAcc}}</div><div class="label">Avg Accuracy</div></div>
        <div class="card red"><div class="value">${{n?(blu/n).toFixed(2):0}}</div><div class="label">Avg Blunders/Game</div></div>`;
    }}
  }}
  const colorF = (document.getElementById('gColorFilter')||{{}}).value||'';
  const catF   = (document.getElementById('gCategoryFilter')||{{}}).value||'';
  const opF    = (document.getElementById('gOpeningFilter')||{{}}).value||'';
  const tbody  = document.getElementById('gamesTableBody');
  if (!tbody) return;
  const rows = Array.from(tbody.rows);
  let vis = 0;
  rows.forEach(r => {{
    const ok =
      (!colorF || r.dataset.color    === colorF) &&
      (!opF    || r.dataset.opening  === opF) &&
      (!catF   || r.dataset.category === catF);
    r.style.display = ok ? '' : 'none';
    if (ok) vis++;
  }});
  const cnt = document.getElementById('gamesFilterCount');
  if (cnt) cnt.textContent = vis===rows.length ? `${{rows.length}} games` : `${{vis}} / ${{rows.length}} games`;
}}

// ── Patterns tab functions ────────────────────────────────────────────────────
function _updatePatternsPage() {{
  const col = (document.getElementById('gColorFilter')    || {{}}).value || '';
  const cat = (document.getElementById('gCategoryFilter') || {{}}).value || '';
  let patterns = (patternsData && patternsData.patterns) ? patternsData.patterns : [];
  patterns = patterns.filter(p => {{
    if (col && p.color    !== col) return false;
    if (cat && p.category !== cat) return false;
    return true;
  }});

  const totalPatterns = patterns.length;
  const totalOccurrences = patterns.reduce((s,p) => s + p.count, 0);
  const avgCpLoss = patterns.length
    ? (patterns.reduce((s,p) => s + p.avg_cp_loss, 0) / patterns.length).toFixed(0)
    : 0;
  const sc = document.getElementById('patSummaryCards');
  if (sc) sc.innerHTML = `
    <div class="card orange"><div class="value">${{totalPatterns}}</div><div class="label">Recurring Patterns</div></div>
    <div class="card red"><div class="value">${{totalOccurrences}}</div><div class="label">Total Occurrences</div></div>
    <div class="card blue"><div class="value">${{avgCpLoss}}</div><div class="label">Avg CP Loss / Pattern</div></div>
  `;

  const grid = document.getElementById('patGrid');
  if (!grid) return;
  if (!patterns.length) {{
    grid.innerHTML = '<div style="color:#a0a0c0;padding:40px;text-align:center;">No recurring patterns found for the selected filters.</div>';
    return;
  }}

  // Group by opening
  const byOpening = {{}};
  for (const p of patterns) {{
    if (!byOpening[p.opening]) byOpening[p.opening] = [];
    byOpening[p.opening].push(p);
  }}

  let html = '';
  for (const [opening, pats] of Object.entries(byOpening)) {{
    html += `<div class="pat-opening-group">
      <h3 class="pat-opening-name">${{opening}}</h3>
      <div class="pat-cards-row">
        ${{pats.map(p => _renderPatCard(p)).join('')}}
      </div>
    </div>`;
  }}
  grid.innerHTML = html;

  // Draw boards after DOM is updated
  for (const p of patterns) {{
    const boardId = _patBoardId(p);
    _drawPatBoard(boardId, p.fen, p.move_bad_uci, p.move_good_uci);
  }}
}}

function _patBoardId(p) {{
  const raw = (p.opening || '').slice(0,12) + (p.move_bad_uci || '') + (p.fen || '').slice(0,8);
  try {{
    return 'pb_' + btoa(unescape(encodeURIComponent(raw))).replace(/[^a-zA-Z0-9]/g, '');
  }} catch(e) {{
    return 'pb_' + Math.abs(raw.split('').reduce((a,c) => (a*31 + c.charCodeAt(0))|0, 0));
  }}
}}

function _renderPatCard(p) {{
  const bid    = _patBoardId(p);
  const cpStr  = p.avg_cp_loss >= 9999 ? '##' : Math.round(p.avg_cp_loss);
  const badSan  = p.move_bad_san  || p.move_bad_uci  || '?';
  const goodSan = p.move_good_san || p.move_good_uci || '?';
  return `
    <div class="pat-card">
      <div class="pat-header">
        <span class="pat-chip">${{p.count}}\u00d7</span>
        <span class="pat-cp-loss" title="Average centipawn loss">\u2212${{cpStr}}\u00a0cp</span>
      </div>
      <div class="pat-board-wrap">
        <div class="pat-board" id="${{bid}}"></div>
        <svg class="pat-arrows" id="${{bid}}_svg" viewBox="0 0 320 320" xmlns="http://www.w3.org/2000/svg"></svg>
      </div>
      <div class="pat-moves">
        <span class="pat-move bad" title="Your move">\u2717\u00a0${{badSan}}</span>
        <span class="pat-move good" title="Best move">\u2713\u00a0${{goodSan}}</span>
      </div>
    </div>`;
}}

function _drawPatBoard(boardId, fen, badUCI, goodUCI) {{
  const board = document.getElementById(boardId);
  if (!board) return;
  const SQ = 40;
  const PIECES = {{
    'K':'\u2654','Q':'\u2655','R':'\u2656','B':'\u2657','N':'\u2658','P':'\u2659',
    'k':'\u265a','q':'\u265b','r':'\u265c','b':'\u265d','n':'\u265e','p':'\u265f'
  }};
  const LIGHT = '#f0d9b5';
  const DARK  = '#b58863';

  const badFrom  = badUCI  && badUCI.length  >= 4 ? badUCI.slice(0,2)  : null;
  const badTo    = badUCI  && badUCI.length  >= 4 ? badUCI.slice(2,4)  : null;
  const goodFrom = goodUCI && goodUCI.length >= 4 ? goodUCI.slice(0,2) : null;
  const goodTo   = goodUCI && goodUCI.length >= 4 ? goodUCI.slice(2,4) : null;

  function sqName(file, rank8) {{ return String.fromCharCode(97+file) + (8-rank8); }}

  const ranks = (fen.split(' ')[0] || '').split('/');
  let html = '';
  for (let rank=0; rank<8; rank++) {{
    const rowStr = ranks[rank] || '';
    let col = 0;
    for (const ch of rowStr) {{
      const count = (ch >= '1' && ch <= '8') ? parseInt(ch) : 1;
      const pieceChar = (ch >= '1' && ch <= '8') ? '' : ch;
      for (let e=0; e<count; e++) {{
        const sq = sqName(col, rank);
        const isLight = (col+rank)%2===0;
        let bg = isLight ? LIGHT : DARK;
        if (sq===badTo)    bg = 'rgba(220,50,50,0.70)';
        if (sq===badFrom)  bg = 'rgba(220,50,50,0.35)';
        if (sq===goodTo)   bg = 'rgba(46,204,113,0.70)';
        if (sq===goodFrom) bg = 'rgba(46,204,113,0.35)';
        const piece = pieceChar ? (PIECES[pieceChar]||'') : '';
        const pColor = pieceChar && pieceChar===pieceChar.toUpperCase() ? '#fff' : '#111';
        html += `<div class="pat-sq" style="background:${{bg}};color:${{pColor}}">${{piece}}</div>`;
        col++;
      }}
    }}
  }}
  board.innerHTML = html;

  const svg = document.getElementById(boardId+'_svg');
  if (svg) {{
    svg.innerHTML = '';
    if (badUCI  && badUCI.length  >= 4) _patArrow(svg, badUCI.slice(0,2),  badUCI.slice(2,4),  '#e74c3c', SQ);
    if (goodUCI && goodUCI.length >= 4) _patArrow(svg, goodUCI.slice(0,2), goodUCI.slice(2,4), '#2ecc71', SQ);
  }}
}}

function _patArrow(svg, fromAlg, toAlg, color, SQ) {{
  const fileOf = s => s.charCodeAt(0) - 97;
  const rankOf = s => 8 - parseInt(s[1]);
  const cx = s => (fileOf(s) + 0.5) * SQ;
  const cy = s => (rankOf(s) + 0.5) * SQ;
  const x1=cx(fromAlg), y1=cy(fromAlg), x2=cx(toAlg), y2=cy(toAlg);
  const dx=x2-x1, dy=y2-y1;
  const len = Math.sqrt(dx*dx+dy*dy) || 1;
  const ux=dx/len, uy=dy/len;
  const hw=5, hl=12;
  const ex=x2-ux*hl, ey=y2-uy*hl;
  const line = document.createElementNS('http://www.w3.org/2000/svg','line');
  line.setAttribute('x1',x1); line.setAttribute('y1',y1);
  line.setAttribute('x2',ex); line.setAttribute('y2',ey);
  line.setAttribute('stroke',color);
  line.setAttribute('stroke-width','4');
  line.setAttribute('stroke-opacity','0.85');
  line.setAttribute('stroke-linecap','round');
  svg.appendChild(line);
  const px=-uy*hw, py=ux*hw;
  const pts=`${{x2}},${{y2}} ${{ex+px}},${{ey+py}} ${{ex-px}},${{ey-py}}`;
  const tri = document.createElementNS('http://www.w3.org/2000/svg','polygon');
  tri.setAttribute('points', pts);
  tri.setAttribute('fill', color);
  tri.setAttribute('fill-opacity','0.85');
  svg.appendChild(tri);
}}

// \u2500\u2500 Keyboard nav for openings board \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
document.addEventListener('keydown', e => {{
  if (document.getElementById('page-openings')?.classList.contains('active')) {{
    if (e.key==='ArrowLeft')  {{ opPrev();  e.preventDefault(); }}
    if (e.key==='ArrowRight') {{ opNext();  e.preventDefault(); }}
    if (e.key==='Home')       {{ opStart(); e.preventDefault(); }}
    if (e.key==='End')        {{ opEnd();   e.preventDefault(); }}
  }}
}});

// \u2500\u2500 Init \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
(function() {{
  const sel = document.getElementById('opTabSel');
  if (sel && allOpeningData.length > 0) {{
    const firstOp = allOpeningData[0]?.opening_name || '';
    if (firstOp) {{
      const opt = sel.querySelector(`option[value="${{CSS.escape(firstOp)}}"]`) ||
                  Array.from(sel.options).find(o=>o.value===firstOp);
      if (opt) sel.value = firstOp;
    }}
  }}
  showPage('dashboard');
}})();
</script>
</body>
</html>"""


# ══════════════════════════════════════════════════════════════════════════════
#  Public entry point
# ══════════════════════════════════════════════════════════════════════════════

def generate_reports(df: pd.DataFrame, opening_df: pd.DataFrame, username: str) -> None:
    """
    Write:
      - output/games/game_{id}.html  for every game
      - output/dashboard.html
    """
    Path(config.GAMES_DIR).mkdir(parents=True, exist_ok=True)
    Path(config.OUTPUT_DIR).mkdir(parents=True, exist_ok=True)

    all_game_ids = list(df["game_id"])
    total        = len(df)

    print(f"[reporter] Writing {total} per-game pages …")
    for i, (_, row) in enumerate(df.iterrows(), 1):
        gid  = row["game_id"]
        html = _render_game_page(row, i, total, all_game_ids, username, opening_df)
        path = Path(config.GAMES_DIR) / f"game_{gid}.html"
        path.write_text(html, encoding="utf-8")

    print("[reporter] Writing dashboard …")
    dashboard_html = _build_dashboard(df, opening_df, username)
    Path(config.DASHBOARD_PATH).write_text(dashboard_html, encoding="utf-8")
    print(f"[reporter] Dashboard: {config.DASHBOARD_PATH}")
