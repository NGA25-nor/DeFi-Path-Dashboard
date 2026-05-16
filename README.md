# DeFi Path Dashboard

A local, privacy-first Capital OS DeFi dashboard for AAVE V3 + Uniswap V3 positions on Ethereum mainnet.

Runs entirely on your own machine. No server. No cloud. No subscription.

---

## ⚡ New user? Start here

**Requirements:**
- Mac or Linux
- Python 3.10+
- Ethereum wallet with AAVE V3 and/or Uniswap V3 positions

```bash
# 1. Clone the repo
git clone https://github.com/NGA25-nor/DeFi-Path-Dashboard
cd DeFi-Path-Dashboard

# 2. Create virtual environment and install dependencies
python3 -m venv venv
source venv/bin/activate
pip install requests

# 3. Add your wallet addresses
cp config.example.py config.py
open -e config.py
```

Fill in your addresses and API key in `config.py`:
```python
MAIN_WALLET    = "0xYOUR_AAVE_WALLET_HERE"
LP_WALLET      = "0xYOUR_UNI_WALLET_HERE"
GRAPH_API_KEY  = "YOUR_GRAPH_API_KEY_HERE"  # free at thegraph.com/studio
CURRENT_STAGE  = "Stage 1"                  # update manually: Stage 1 / 1w / 2 / 2w / 3
```

```bash
# 4. Make the launcher clickable (one time only)
chmod +x start.command

# 5. Run
python3 tracker.py
```

Dashboard opens at `http://localhost:5050`. That's it. 🎉

On first run, `tracker.py` automatically creates the local SQLite database at `data/portfolio.db`.

---

## Daily use

**Double-click** `start.command` in Finder — Terminal opens and dashboard loads automatically.

Or from Terminal:
```bash
cd DeFi-Path-Dashboard
source venv/bin/activate
python3 tracker.py
```

With gas tracking:
```bash
python3 tracker.py --gas 0.002
```

Click **⟳ Refresh** in the browser to fetch new data without reopening Terminal.

Press `Ctrl+C` to stop the server.

---

## Manual farm history CSV

Optional, but recommended if you have closed/collected old farms.

Create your own file from the example:
```bash
cp data/farm_history.example.csv data/farm_history.csv
```

Fill in one row per Uniswap NFT/farm:
```csv
nft_id,pair,status,realized_weth,realized_wbtc,realized_usdt,realized_usdc,notes
1269178,ETH/USDT,active,0.0012,0,45.50,0,Collected fees from current farm
1198334,BTC/USDT,closed,0,0.0004,28.00,0,Old BTC/USDT farm
```

Use realized/collected fees only. Current unclaimed fees are fetched live and added separately by `tracker.py`.

If `data/farm_history.csv` is missing, the dashboard still runs and uses live/snapshot data only.

The CSV is for realized/collected fees only. Do not enter current unclaimed fees here; those are fetched live.

When a farm appears closed and is not already in your manual history, the tracker may create:
```text
data/farm_history_suggestions.csv
```

Review suggested rows before copying them into `data/farm_history.csv`. Suggestions are best-effort and are not treated as final accounting.

---

## What the dashboard shows

### System Health
Six cards at the top — always visible at a glance:

| Card | What it measures |
|---|---|
| Health Factor | AAVE liquidation safety. Target ≥1.80, floor 1.60 |
| LP Stable Buffer | USDT in LP / total equity. Target ≥25% |
| Borrow Usage | Debt / max borrow capacity. Target <70% |
| Current Stage | DeFi Path stage (manually set in config.py) |
| Risk State | Derived from HF + borrow usage + stable buffer |
| Liquidation Risk | Correlated market drop % before liquidation |

**Risk State logic:**
- 🟢 Defensive: HF ≥1.80, borrow <70%, stable buffer ≥25%
- 🔵 Balanced: HF ≥1.80, borrow <70%, stable buffer <25%
- 🟡 Aggressive: HF 1.60–1.79, or borrow 70–85%, or stable buffer <15%
- 🔴 Overextended: HF <1.60 or borrow >85%

### Risk Alerts
Appear only when triggered — calm and direct:
- HF below target or critical
- Stable buffer below 25%
- Borrow usage above 85%
- LP out of range
- Gas drag above 20%
- AAVE borrow cost exceeds LP fees

### Active Farms
Live Uniswap V3 position + output view. If multiple farms are active, each NFT is shown separately:
- Pair, status, current price, range, position value
- Current / 7d / 30d farm APY
- Active farm lifetime output estimate by WETH/WBTC/USDT/USDC
- Last 24h LP fees, token fees, and estimated financing carry
- Current unclaimed fees
- ETH/USDT composition and range bar

### Flywheel Strength
- Collateral growth 30d
- Debt growth 30d
- Net flywheel expansion (collateral growth − debt growth)
- Lifetime Strategy Output across all farms
- Lifetime Financing Carry as estimated interest on borrowed stables
- Borrow Room (remaining capacity from AAVE)

### Unit Accumulation
- Total ETH exposure (AAVE + wallet + LP)
- Total BTC exposure (AAVE)
- Net stable position (LP stables − AAVE stable debt)

### Core Charts
1. Total Equity Trend
2. LTV Over Time
3. Farm APY Trend
4. Daily Yield Breakdown (LP fees + AAVE carry)
5. Cumulative Farm Output
6. Unit Accumulation Over Time (ETH + BTC)

### Strategy vs HODL
Placeholder — configure baseline in `config.py` to enable.

---

## Configuration (`config.py`)

```python
MAIN_WALLET    = "0x..."         # wallet with AAVE positions
LP_WALLET      = "0x..."         # wallet with Uniswap LP (can be same as MAIN)
GRAPH_API_KEY  = "..."           # The Graph API key for unclaimed fee tracking
CURRENT_STAGE  = "Stage 1"       # DeFi Path stage — update manually

# Optional — enable Strategy vs HODL benchmark
# BASELINE_ETH     = 0.0
# BASELINE_BTC     = 0.0
# BASELINE_STABLES = 0.0
# BASELINE_START_DATE = "2026-01-01"
```

`config.py` is listed in `.gitignore` and never pushed to GitHub.

---

## Data sources

| Data | Source |
|---|---|
| ETH/BTC prices | Chainlink on-chain oracles |
| AAVE positions, APY | AAVE V3 Pool contract |
| Uniswap V3 LP positions | Position Manager + Pool contracts |
| Unclaimed LP fees | The Graph (authenticated gateway) |
| All RPC calls | ethereum-rpc.publicnode.com (free, no key) |

All calls are **read-only**. No private keys. No transactions.

---

## What is calculated

**AAVE:**
- Collateral, debt, equity, HF, LTV
- Supply APY (WETH) and borrow APY (USDT)
- Financing carry = estimated borrow cost on stable debt, shown as a negative farm cost
- AAVE carry = supply income − borrow cost, kept for reference
- Borrow Room = AAVE `availableBorrowsBase` from `getUserAccountData`

**Liquidation:**
- ETH liq price (isolated)
- BTC liq price (isolated)
- Correlated drop % (both assets fall together)
- Liquidation thresholds: ETH 82.5%, WBTC 75%

**Uniswap V3:**
- Token amounts from liquidity math
- Tick → USD price conversion
- In/out of range status
- Unclaimed fees via The Graph subgraph
- Daily fee yield = difference from previous snapshot
- Optional manual realized fee history from `data/farm_history.csv`

**Portfolio:**
- Total equity = AAVE equity + ETH balances + LP value
- Borrow usage = debt / (collateral × weighted max LTV)
- Weighted max LTV: ETH 80%, WBTC 70%
- Farm APY = daily fee yield / LP value × 365
- Farm APY fallback = 7d average when today's yield is $0
- Flywheel expansion = collateral growth % − debt growth %

---

## Security

- **Read-only** — no private keys, no seed phrases, no transactions
- **Local only** — all data stays on your machine
- `config.py` never pushed to GitHub
- Only outbound calls: RPC reads + The Graph API

---

## Project structure

```
DeFi-Path-Dashboard/
├── tracker.py          # main script — fetch, calculate, store, serve
├── db.py               # SQLite helper
├── start.command       # double-click launcher (Mac)
├── dashboard.html      # generated on each run (not in git)
├── config.py           # your config (not in git)
├── config.example.py   # template
├── data/
│   ├── portfolio.db              # local SQLite database (not in git)
│   ├── farm_history.csv          # your manual farm history (not in git)
│   ├── farm_history_suggestions.csv # closed farm suggestions (not in git)
│   └── farm_history.example.csv  # template for manual farm history
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
open -e config.py
```

**`start.command` won't open**
```bash
chmod +x start.command
```

**Unclaimed fees show $0**
Check that `GRAPH_API_KEY` is set in `config.py`. Get a free key at thegraph.com/studio.

**Dashboard not loading**
`tracker.py` must be running. If port 5050 is busy it tries 5051, 5052 automatically.

**Health Factor looks wrong**
Cross-check at aavescan.com with your wallet address.

**Positions show as out of range when they shouldn't**
Old closed Uniswap NFTs stay in your wallet. The tracker labels them as "Closed" and excludes them from status and value calculations.
