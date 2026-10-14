# spread_reversion

Paper-trading spread-reversion bot for BANKBEES vs SETFNIFBK (NSE ETFs). No real orders are ever placed — see [AGENTS.md](AGENTS.md).

## Setup

```bash
cp .env.example .env
```

Fill in `.env` with either:
- `GROWW_API_KEY` + `GROWW_API_SECRET` (generated/approved on the [Groww Cloud API Keys page](https://groww.in/trade-api/docs/curl)) — a token is fetched automatically at startup, or
- `GROWW_ACCESS_TOKEN` directly, to skip token generation.

## Run

```bash
cargo run
```

This opens a terminal UI showing live prices, spread/z-score, current position (what to buy/short and how much), and P&L. Press `q` to quit.

Logs (not shown on stdout, since the TUI owns the terminal) are written to `spread_reversion.log`.
