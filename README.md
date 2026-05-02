# DeFi Portfolio Tracker

Run once daily to fetch your on-chain AAVE + Uniswap data and view a local dashboard.

## Setup
1. Open tracker.py
2. Replace MAIN_WALLET and LP_WALLET with your Ethereum addresses
3. Install dependency: pip install requests

## Run
python tracker.py

## What it does
- Fetches live data from Ethereum via public RPC (read-only)
- Saves to local SQLite database (data/portfolio.db)
- Generates dashboard.html and opens it in your browser

## Security
- No private keys required or used
- No data leaves your machine except read-only RPC queries
- Wallet addresses are public on-chain data
