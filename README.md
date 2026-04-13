# ChessVision

An interactive chess game analysis dashboard powered by Stockfish. Fetches your games from Chess.com, runs deep engine analysis, and produces a local HTML dashboard with per-opening statistics, error breakdowns, and an interactive chess board.

![Dashboard tabs: Dashboard | Openings | Games](https://via.placeholder.com/900x400?text=ChessVision+Dashboard)

---

## Features

- **Fetches games automatically** from the Chess.com public API (no API key needed)
- **Deep Stockfish analysis** at configurable depth (default: depth 15)
- **Smart caching** — each game is analysed once and cached locally; re-runs are instant
- **3-tab dashboard**:
  - **Dashboard** — accuracy, blunder/mistake/inaccuracy breakdown, error phases, critical patterns
  - **Openings** — interactive chess board with book theory vs your game continuation, per-opening stats
  - **Games** — filterable game list with opponent ELO, accuracy, and blunder count
- **Dynamic filters** — filter all charts and tables by Color (White/Black) and Game Type (Bullet/Blitz/Rapid)
- **Tactic classification** — identifies Hanging piece, Fork, Pin, Skewer, Discovered attack, Forcing check, Promotion, Checkmate threat, and Positional errors

---

## Requirements

- Python 3.9+
- [Stockfish](https://stockfishchess.org/download/) installed via Homebrew:
  ```bash
  brew install stockfish
  ```

---

## Installation

```bash
git clone https://github.com/YOUR_USERNAME/ChessVision.git
cd ChessVision/chess_analyzer
pip install -r requirements.txt
```

**`requirements.txt`** includes: `chess`, `pandas`, `requests`

---

## Usage

### Fetch and analyse your last 200 games from Chess.com

```bash
cd chess_analyzer
python3 main.py --username YOUR_CHESSCOM_USERNAME --limit 200
```

### Analyse a local PGN file

```bash
python3 main.py --pgn path/to/games.pgn --player YOUR_USERNAME --limit 200
```

### Options

| Flag | Description |
|------|-------------|
| `--username NAME` | Chess.com username to fetch games for |
| `--pgn FILE` | Path to a local .pgn file |
| `--player NAME` | Your username for perspective when using `--pgn` |
| `--limit N` | Analyse only the N most recent games (default: all) |
| `--category TC` | Filter by time control: `bullet` \| `blitz` \| `rapid` \| `classical` |
| `--depth D` | Stockfish analysis depth (default: 15; use 12 for faster runs) |
| `--no-cache` | Ignore cached results and re-analyse every game from scratch |

### Serve the dashboard locally

The dashboard is a static HTML file. Open it directly, or serve it over HTTP:

```bash
python3 serve_dashboard.py
# → http://localhost:5050/dashboard.html
```

---

## Performance

| Games | First run (depth 15) | Subsequent runs |
|-------|---------------------|-----------------|
| 20    | ~3 minutes          | < 2 seconds     |
| 200   | ~35 minutes         | < 5 seconds     |

Analysis results are cached in `output/analysis_cache.pkl`. Only newly-fetched games trigger Stockfish. To force a full re-analysis, use `--no-cache`.

---

## Project structure

```
chess_analyzer/
├── main.py           # CLI entry point
├── config.py         # Thresholds, paths, Stockfish config
├── fetcher.py        # Chess.com API client (concurrent fetching)
├── pgn_parser.py     # PGN → DataFrame with stable game IDs
├── openings.py       # ECO opening recognition and theory depth
├── analyzer.py       # Stockfish analysis + tactic classification + caching
├── reporter.py       # HTML dashboard generator
├── serve_dashboard.py# Simple HTTP server for the dashboard
├── requirements.txt
└── output/           # Generated files (gitignored except .gitkeep)
    ├── dashboard.html
    ├── games/
    ├── mes_parties.pgn
    └── analysis_cache.pkl
```

---

## Cache invalidation

The cache is keyed by `(CACHE_VERSION, game_id)`. When the analysis logic changes (new tactic types, scoring formula, etc.), bump `CACHE_VERSION` in `config.py` to automatically invalidate all cached results.

---

## License

MIT
