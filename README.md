# DeFi Portfolio Tracker

A local, privacy-first portfolio tracker for AAVE V3 + Uniswap V3 positions on Ethereum mainnet.

Runs entirely on your own machine. No server. No cloud. No API keys required.

---

## What it does

- Fetches live on-chain data from Ethereum via public RPC (read-only)
- Tracks AAVE V3 collateral, debt, health factor, and liquidation prices
- Tracks Uniswap V3 LP position count
- Calculates correlated liquidation risk (what % market drop triggers liquidation)
- Saves daily snapshots to a local SQLite database
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

## Setup

### 1. Clone the repo
```bash
git clone https://github.com/NGA25-nor/defi-tracker.git
cd defi-tracker
```

### 2. Create virtual environment and install dependencies
```bash
python3 -m venv venv
source venv/bin/activate
pip install requests
```

### 3. Add your wallet addresses
```bash
cp config.example.py config.py
```

Open `config.py` and fill in your Ethereum wallet addresses:
```python
MAIN_WALLET = "0xYOUR_AAVE_WALLET_HERE"   # wallet with AAVE positions
LP_WALLET   = "0xYOUR_UNI_WALLET_HERE"    # wallet with Uniswap LP positions
```

If you use the same wallet for both, use the same address in both fields.

> **Your wallet addresses are never shared.** `config.py` is listed in `.gitignore`
> and will never be pushed to GitHub.

### 4. Run
```bash
python3 tracker.py
```

The dashboard opens automatically at `http://localhost:5050`.

---

## Daily use

Every time you want an updated snapshot:

```bash
cd defi-tracker
source venv/bin/activate
python3 tracker.py
```

Or just click **⟳ Refresh** in the browser if `tracker.py` is already running.

Press `Ctrl+C` in Terminal to stop the server when you're done.

---

## What the dashboard shows

| Section | Description |
|---|---|
| Health banner | Health Factor with green/amber/red status |
| KPI grid | ETH price, BTC price, collateral, debt, balances |
| Liq Price ETH | Price at which your ETH collateral triggers liquidation |
| Liq Price BTC | Price at which your WBTC collateral triggers liquidation |
| Market Drop to Liq | % drop in both ETH+BTC that triggers liquidation (correlated) |
| Liquidation Risk Summary | All liq prices + buffers in one place |
| Chart 1 | 30-day total equity trend |
| Chart 2 | AAVE health factor over time |
| Chart 3 | LTV% over time |
| Chart 4 | ETH price vs liquidation price over time |

---

## Security

- **Read-only** — no private keys, no seed phrases, no transactions
- **Local only** — all data stays on your machine
- **Public RPC** — only outbound calls are read requests to `ethereum-rpc.publicnode.com`
- Wallet addresses are public on-chain data — safe to use in read-only scripts

---

## Project structure

```
defi-tracker/
├── tracker.py          # main script — fetch, store, serve dashboard
├── db.py               # SQLite helper
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

**Dashboard not loading**
Make sure `tracker.py` is running in Terminal. The browser needs the local server active at `http://localhost:5050`.

**RPC error / no data**
The public RPC endpoint may be temporarily unavailable. Try again in a few minutes, or replace `RPC_URL` in `tracker.py` with a free Alchemy endpoint.

**Health Factor looks wrong**
Cross-check at [aavescan.com](https://aavescan.com) by searching your wallet address.

---

## Data sources

| Data | Source |
|---|---|
| ETH/BTC prices | Chainlink on-chain oracles |
| AAVE positions | AAVE V3 Pool contract (Ethereum mainnet) |
| LP position count | Uniswap V3 NFT Position Manager |
| All RPC calls | [ethereum-rpc.publicnode.com](https://ethereum-rpc.publicnode.com) (free, no key) |
