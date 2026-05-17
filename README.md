# DeFi Path Dashboard

A local, privacy-first Capital OS DeFi dashboard for AAVE V3 + Uniswap V3 positions on Ethereum mainnet.

Runs on your own machine with a local browser dashboard. No hosted server, no cloud account, no subscription, and no private keys.

---

## ⚡ New user? Start here

**Requirements:**
- Mac or Linux
- Python 3.10+
- Ethereum wallet with AAVE V3 and/or Uniswap V3 positions
- The Graph API key for live Uniswap fee tracking

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
```

Open `config.py` in your editor. On macOS you can use:
```bash
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

Dashboard opens at `http://localhost:5050`. If that port is busy, the tracker tries the next available port.

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

Optional, but recommended if you want operator-grade deployment accounting.

The live chain data can tell what an LP NFT is worth now. It cannot know what you originally deployed into that farm. `data/farm_history.csv` is the manual ledger that fills that gap.

Create your own file from the example:
```bash
cp data/farm_history.example.csv data/farm_history.csv
```

Fill in one row per Uniswap NFT/farm:
```csv
nft_id,pair,stage,status,input_usd,output_usd,input_weth,input_wbtc,input_usdt,input_usdc,output_weth,output_wbtc,output_usdt,output_usdc,notes
1269178,WETH/USDT,Stage 1,active,8000,0,1.20,0,4000,0,0,0,0,0,Current active farm input seed
1147472,WETH/USDT,Stage 1,closed,5000,5420,0.80,0,2500,0,0.84,0,2680,0,Old ETH farm deployment result
1198334,WBTC/USDT,Stage 2,closed,6000,6420,0,0.11,3000,0,0,0.118,3250,0,BTC accumulation
```

This file is an operator ledger, not tax accounting:
- Input = what was deployed when the farm started.
- Output = what was received when the farm closed, collected, or was manually recorded.
- Result = output minus input.
- Stables = USDT + USDC.

For active farms, seed the input fields manually. The dashboard uses the live LP value plus current unclaimed fees as the current output estimate.

If `data/farm_history.csv` is missing, the dashboard still runs and uses live/snapshot data only.

Do not enter current unclaimed fees for active farms here; those are fetched live.

Recommended workflow:
1. Add a row when you deploy a new farm and mark it `active`.
2. Keep the input fields as the original deployment amounts.
3. When the farm is closed, update `status` to `closed` and fill the output fields with the final received amounts.
4. Leave current unclaimed fees out of the CSV; they are fetched live.

When a farm appears closed and is not already in your manual history, the tracker may create:
```text
data/farm_history_suggestions.csv
```

Review suggested rows before copying them into `data/farm_history.csv`. Suggestions are passive helpers and are not treated as final accounting.

---

## What the dashboard shows

### System Health
Six cards at the top — always visible at a glance:

| Card | What it measures |
|---|---|
| Health Factor | AAVE liquidation safety. Target ≥1.80, floor 1.60 |
| LP Stable Buffer | USDT + USDC in LP / total equity. Target ≥25% |
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
- Pair, status, current price range, and position value
- 24h / 7d / 30d farm APY and APY quality
- Active farm input, current value, result, and WETH/WBTC/stable deltas
- Current unclaimed fees
- WETH/WBTC/USDT/USDC composition and LP stable %
- Range bar

### Flywheel Strength
- Collateral growth 30d
- Debt growth 30d
- Net flywheel expansion (collateral growth − debt growth)
- Gross Farm Result from the farm ledger before financing: input, farm value, result, ETH delta, BTC delta, stable delta
- Financing Carry as estimated stable debt interest; negative means net borrowing cost
- Net Strategy Output = Gross Farm Result + Financing Carry

### Per-Farm Ledger
Confirmed farm accounting in one table:
- Live active farms, using current LP value plus unclaimed fees
- Confirmed `data/farm_history.csv` rows
- Input, current/final value, result, WETH delta, BTC delta, stable delta, unclaimed fees, and notes

Pending suggestions are excluded from this table until copied into `data/farm_history.csv`.

### Farm History Summary and Review Queue
- Confirmed Rows = rows currently counted from `data/farm_history.csv`
- Pending Suggestions = rows waiting in `data/farm_history_suggestions.csv`
- Detected Closed = closed NFTs seen live but not yet in the manual ledger or suggestions
- Confirmed Result = confirmed farm result from the reviewed ledger

The Review Queue shows helper rows only. It is there to make closed farms easier to review before adding them to the manual ledger.

### Unit Accumulation
- Total ETH exposure (AAVE + wallet + LP)
- Total BTC exposure (AAVE)
- Net stable position (LP USDT + USDC − AAVE USDT + USDC stable debt)

The Net Stable Position card also shows the AAVE stable debt split by USDT and USDC.

### Core Charts
1. Total Equity Trend
2. LTV Over Time
3. Farm APY Trend
4. Daily Yield Breakdown (LP fees + AAVE carry)
5. Cumulative Fee Snapshot
6. Unit Accumulation Over Time (ETH + BTC)

### Strategy vs HODL
Placeholder only. Baseline fields are documented in `config.example.py`, but the current tracker does not calculate a Strategy vs HODL benchmark yet.

---

## Configuration (`config.py`)

```python
MAIN_WALLET    = "0x..."         # wallet with AAVE positions
LP_WALLET      = "0x..."         # wallet with Uniswap LP (can be same as MAIN)
GRAPH_API_KEY  = "..."           # The Graph API key for unclaimed fee tracking
CURRENT_STAGE  = "Stage 1"       # DeFi Path stage — update manually

# Optional — future Strategy vs HODL benchmark inputs.
# These are not used by the current tracker yet.
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
- Supply APY (WETH) and borrow APY (USDT + USDC)
- Financing carry = weighted estimated borrow cost on USDT + USDC stable debt, shown as a negative farm cost
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
- Optional manual deployment ledger from `data/farm_history.csv`

**Portfolio:**
- Total equity = AAVE equity + ETH balances + LP value
- Borrow usage = debt / (collateral × weighted max LTV)
- Weighted max LTV: ETH 80%, WBTC 70%
- Farm APY = daily fee yield / LP value × 365
- Farm APY fallback = 7d average when today's yield is $0
- Flywheel expansion = collateral growth % − debt growth %
- Gross Farm Result = confirmed closed farm result + configured active farm current result
- Net Strategy Output = Gross Farm Result + Financing Carry

---

## Security

- **Read-only** — no private keys, no seed phrases, no transactions
- **Local only** — all data stays on your machine
- `config.py` never pushed to GitHub
- `data/farm_history.csv` and `data/farm_history_suggestions.csv` never pushed to GitHub
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

**Active Farm Result says `Input not configured`**
Add that NFT to `data/farm_history.csv` with `status` set to `active` and fill the input fields with the original deployment amounts.

**A closed farm appears in the Review Queue**
Inspect `data/farm_history_suggestions.csv`. If the row is correct, copy it into `data/farm_history.csv`, fill any missing input fields, and keep it as the confirmed ledger row.

**Dashboard not loading**
`tracker.py` must be running. If port 5050 is busy it tries 5051, 5052 automatically.

**Health Factor looks wrong**
Cross-check at aavescan.com with your wallet address.

**Positions show as out of range when they shouldn't**
Old closed Uniswap NFTs stay in your wallet. The tracker labels them as "Closed" and excludes them from status and value calculations.
