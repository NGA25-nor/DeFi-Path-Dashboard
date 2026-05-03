# DeFi Portfolio Tracker

A local, privacy-first portfolio tracker for AAVE V3 + Uniswap V3 positions on Ethereum mainnet.

Runs entirely on your own machine. No server. No cloud. No API keys required.

---

## ⚡ New user? Start here

**Requirements:**
- Mac or Linux
- Python 3.10+ ([check below](#requirements) if unsure)
- Ethereum wallet with AAVE V3 and/or Uniswap V3 positions

**5-minute setup:**

```bash
# 1. Clone the repo
git clone https://github.com/NGA25-nor/defi-tracker
cd defi-tracker

# 2. Create virtual environment and install dependencies
python3 -m venv venv
source venv/bin/activate
pip install requests

# 3. Add your wallet address(es)
cp config.example.py config.py
open -e config.py
```

In `config.py`, replace the placeholders with your Ethereum wallet address(es):
```python
MAIN_WALLET = "0xYOUR_WALLET_HERE"   # wallet with AAVE positions
LP_WALLET   = "0xYOUR_WALLET_HERE"   # wallet with Uniswap LP positions
```

> If you use the same wallet for both AAVE and Uniswap, use the same address in both fields.

```bash
# 4. Make the launcher clickable (one time only)
chmod +x start.command

# 5. Run
python3 tracker.py
```

Dashboard opens automatically at `http://localhost:5050`. That's it. 🎉

---

## Daily use

**Option A — Double-click (easiest)**
Double-click `start.command` in Finder. Terminal opens and the dashboard loads automatically.

Want it on your Desktop?
```bash
ln -s /path/to/defi-tracker/start.command ~/Desktop/DeFi\ Tracker.command
```

**Option B — Terminal**
```bash
cd defi-tracker
source venv/bin/activate
python3 tracker.py
```

**Option C — Refresh button**
If `tracker.py` is already running, just click **⟳ Refresh** in the browser to fetch new data without opening Terminal.

Press `Ctrl+C` in Terminal to stop the server when you're done.

---

## What it does

- Fetches live on-chain data from Ethereum via public RPC (read-only)
- Tracks AAVE V3 collateral, debt, health factor, and liquidation prices
- Tracks Uniswap V3 LP positions — value, token amounts, unclaimed fees, range status
- Calculates correlated liquidation risk (what % market drop triggers liquidation)
- Saves one snapshot per run to a local SQLite database
- Generates a dark-theme dashboard with charts, opens in your browser
- Includes a **⟳ Refresh** button — no need to open Terminal after first run

---

## Requirements

- Mac or Linux
- Python 3.10 or higher
- Internet connection (for RPC calls to Ethereum)

Check your Python version:
```bash
python3 --version
```

If below 3.10, install via Homebrew (Mac):
```bash
brew install python
```

---

## What the dashboard shows

| Section | Description |
|---|---|
| Health banner | Health Factor with green/amber/red status |
| KPI grid | ETH price, BTC price, collateral, debt, balances |
| Market Drop to Liq | % drop in both ETH+BTC that triggers liquidation |
| Liquidation Risk card | One clear scenario — how far market must fall + prices at liquidation |
| Uniswap V3 Position | Pool, token amounts, value, unclaimed fees, in/out of range |
| Range bar | Visual price range with current price marker |
| Chart 1 | 30-day total equity trend |
| Chart 2 | AAVE health factor over time |
| Chart 3 | LTV% over time |
| Chart 4 | ETH price vs liquidation price over time |
| Chart 5 | Uniswap LP position value over time |

---

## Understanding liquidation risk

**Market Drop to Liq (correlated)**
ETH and BTC tend to fall together. This shows what % both assets must drop simultaneously before you get liquidated.

- 🟢 Green / SAFE: drop > 35%
- 🟡 Amber / WATCH: drop 20–35%
- 🔴 Red / DANGER: drop < 20%

---

## How data is stored

Each run saves one row to a local SQLite database (`data/portfolio.db`). Charts improve as more days accumulate. Run it daily for the best historical view.

---

## Security

- **Read-only** — no private keys, no seed phrases, no transactions
- **Local only** — all data stays on your machine
- **Public RPC** — only outbound calls are read requests to `ethereum-rpc.publicnode.com`
- `config.py` is listed in `.gitignore` and never pushed to GitHub
- Wallet addresses are public on-chain data — safe to use in read-only scripts

---

## Project structure

```
defi-tracker/
├── tracker.py          # main script — fetch, store, serve dashboard
├── db.py               # SQLite helper
├── start.command       # double-click launcher for Mac
├── dashboard.html      # generated on each run (not in git)
├── config.py           # your wallet addresses (not in git)
├── config.example.py   # template — copy this to config.py
├── data/
│   └── portfolio.db    # local database (not in git)
└── README.md
```

---

## Troubleshooting

**`ModuleNotFoundError: requests`**
```bash
source venv/bin/activate
pip install requests
```

**`config.py not found`**
```bash
cp config.example.py config.py
# then open config.py and add your wallet addresses
```

**`start.command` won't open**
```bash
chmod +x start.command
```

**Dashboard not loading**
Make sure `tracker.py` is running in Terminal. The browser needs the local server active at `http://localhost:5050` (or 5051/5052 if 5050 is busy).

**RPC error / no data**
The public RPC endpoint may be temporarily unavailable. Try again in a few minutes, or replace `RPC_URL` in `tracker.py` with a free Alchemy endpoint.

**Health Factor looks wrong**
Cross-check at [aavescan.com](https://aavescan.com) by searching your wallet address.

**Old Uniswap positions showing up**
Uniswap V3 NFTs stay in your wallet even after you remove liquidity. Closed positions (liquidity = 0) are labeled separately and excluded from value and range calculations.

---

## Data sources

| Data | Source |
|---|---|
| ETH/BTC prices | Chainlink on-chain oracles |
| AAVE positions | AAVE V3 Pool contract (Ethereum mainnet) |
| Uniswap V3 LP positions | Uniswap V3 Position Manager + Pool contracts |
| All RPC calls | [ethereum-rpc.publicnode.com](https://ethereum-rpc.publicnode.com) (free, no key) |