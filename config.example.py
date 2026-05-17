# config.example.py - copy to config.py and fill in your local settings.
# config.py is gitignored and should contain only your private/local values.

# Wallet with AAVE V3 collateral/debt positions.
MAIN_WALLET = "0xYOUR_AAVE_WALLET_HERE"

# Wallet that owns Uniswap V3 LP NFTs. This can be the same as MAIN_WALLET.
LP_WALLET = "0xYOUR_UNI_WALLET_HERE"

# The Graph API key, used for Uniswap unclaimed fee tracking.
# Get one from https://thegraph.com/studio/
GRAPH_API_KEY = "YOUR_GRAPH_API_KEY_HERE"

# Manual DeFi Path stage label shown in the dashboard.
CURRENT_STAGE = "Stage 1"

# Optional - future Strategy vs HODL benchmark inputs.
# These are documented in README, but not used by the current tracker yet.
# BASELINE_ETH = 0.0
# BASELINE_BTC = 0.0
# BASELINE_STABLES = 0.0
# BASELINE_START_DATE = "2026-01-01"
