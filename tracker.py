from __future__ import annotations

import argparse
import http.server
import json
import math
import socketserver
import sys
import threading
import webbrowser
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

import requests

from config import LP_WALLET, MAIN_WALLET
try:
    from config import GRAPH_API_KEY
except ImportError:
    GRAPH_API_KEY = None
try:
    from config import CURRENT_STAGE
except ImportError:
    CURRENT_STAGE = "Stage 1"
from db import get_history, init_db, insert_snapshot


RPC_URL = "https://ethereum-rpc.publicnode.com"
SERVER_HOST = "localhost"
SERVER_PORTS = (5050, 5051, 5052)


AAVE_POOL = "0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2"
AWETH = "0x4d5F47FA6A74757f35C14fD3a6Ef8E3C9BC514E8"
AWBTC = "0x5Ee5bf7ae06D1Be5997A1A72006FE6C607eC6DE8"
VDUSDT = "0x531842cebfcce26401911cb6d3b170f8b2fc57c6"
UNI_V3_NFT_MANAGER = "0xC36442b4a4522E871399CD717aBDD847Ab11FE88"
UNI_WETH_USDT_POOL = "0x4e68Ccd3E89f51C3074ca5072bbAC773960dFa36"
WETH = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"
USDT = "0xdAC17F958D2ee523a2206206994597C13D831ec7"
ETH_USD_FEED = "0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419"
BTC_USD_FEED = "0xF4030086522a5bEEa4988F8cA5B36dbC97BeE88c"
ETH_LIQ_THRESHOLD = 0.825
BTC_LIQ_THRESHOLD = 0.750
ETH_MAX_LTV = 0.80
WBTC_MAX_LTV = 0.70

LATEST_ROUND_DATA_SELECTOR = "0xfeaf968c"
BALANCE_OF_SELECTOR = "0x70a08231"
AAVE_USER_DATA_SELECTOR = "0xbf92857c"
GET_RESERVE_DATA_SELECTOR = "0x35ea6a75"
TOKEN_OF_OWNER_BY_INDEX_SELECTOR = "0x2f745c59"
POSITIONS_SELECTOR = "0x99fbab88"
SLOT0_SELECTOR = "0x3850c7bd"
Q96 = 2**96
Q128 = 2**128
Q256 = 2**256
RAY = 1e27
UNISWAP_V3_SUBGRAPH_ID = "5zvR82QoaXYFyDEKLZ9t6v9adgnptxYpKpSbxtgVENFV"

BASE_DIR = Path(__file__).resolve().parent
DASHBOARD_PATH = BASE_DIR / "dashboard.html"
DB_FILE = BASE_DIR / "data" / "portfolio.db"
REQUEST_TIMEOUT = 20


class RpcError(Exception):
    """Raised when a JSON-RPC request returns an error or malformed response."""


def rpc_request(method: str, params: list[Any]) -> Any:
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    response = requests.post(RPC_URL, json=payload, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    data = response.json()
    if "error" in data:
        raise RpcError(data["error"].get("message", str(data["error"])))
    if "result" not in data:
        raise RpcError("missing JSON-RPC result")
    return data["result"]


def clean_address(address: str) -> str:
    if not isinstance(address, str) or not address.startswith("0x") or len(address) != 42:
        raise ValueError(f"invalid Ethereum address: {address}")
    int(address[2:], 16)
    return address.lower()


def pad_address(address: str) -> str:
    return clean_address(address)[2:].rjust(64, "0")


def hex_to_int(value: str) -> int:
    if not value or value == "0x":
        return 0
    return int(value, 16)


def pad_uint(value: int) -> str:
    return hex(value)[2:].rjust(64, "0")


def decode_address_word(word: int) -> str:
    return "0x" + hex(word)[2:].rjust(64, "0")[-40:]


def decode_signed_word(word: int) -> int:
    if word >= 2**255:
        return word - 2**256
    return word


def eth_call(to_address: str, data: str) -> str:
    return rpc_request("eth_call", [{"to": to_address, "data": data}, "latest"])


def decode_uint_words(result: str) -> list[int]:
    hex_data = result[2:] if result.startswith("0x") else result
    if not hex_data:
        return []
    return [int(hex_data[index : index + 64], 16) for index in range(0, len(hex_data), 64)]


def decode_reserve_rate(hex_data: str, word_index: int) -> int:
    if not hex_data or hex_data == "0x":
        return 0
    data = hex_data[2:] if hex_data.startswith("0x") else hex_data
    start = word_index * 64
    end = start + 64
    if len(data) < end:
        return 0
    return int(data[start:end], 16)


def safe_fetch(label: str, fetcher: Any) -> tuple[Any, bool]:
    try:
        return fetcher(), True
    except Exception as exc:
        print(f"Warning: could not fetch {label}: {exc}")
        return None, False


def fetch_price(feed_address: str) -> float:
    result = eth_call(feed_address, LATEST_ROUND_DATA_SELECTOR)
    words = decode_uint_words(result)
    if len(words) < 2:
        raise RpcError("latestRoundData returned too few fields")
    return words[1] / 1e8


def fetch_eth_balance(wallet: str) -> float:
    result = rpc_request("eth_getBalance", [clean_address(wallet), "latest"])
    return hex_to_int(result) / 1e18


def fetch_aave_user_data(wallet: str) -> dict[str, float]:
    result = eth_call(AAVE_POOL, AAVE_USER_DATA_SELECTOR + pad_address(wallet))
    words = decode_uint_words(result)
    if len(words) < 6:
        raise RpcError("getUserAccountData returned too few fields")
    collateral = words[0] / 1e8
    debt = words[1] / 1e8
    return {
        "aave_collateral": collateral,
        "aave_debt": debt,
        "health_factor": words[5] / 1e18,
    }


def fetch_aave_reserve_rates(asset: str) -> dict[str, float]:
    result = eth_call(AAVE_POOL, GET_RESERVE_DATA_SELECTOR + pad_address(asset))
    liquidity_rate = decode_reserve_rate(result, 2)
    borrow_rate = decode_reserve_rate(result, 4)
    if liquidity_rate == 0 and borrow_rate == 0:
        raise RpcError("getReserveData returned too few fields")
    return {
        "supply_apy_pct": (liquidity_rate / RAY) * 100,
        "borrow_apy_pct": (borrow_rate / RAY) * 100,
    }


def fetch_token_balance(token_address: str, wallet: str, decimals: int) -> float:
    result = eth_call(token_address, BALANCE_OF_SELECTOR + pad_address(wallet))
    return hex_to_int(result) / (10**decimals)


def fetch_uni_position_count(wallet: str) -> int:
    result = eth_call(UNI_V3_NFT_MANAGER, BALANCE_OF_SELECTOR + pad_address(wallet))
    return hex_to_int(result)


def fetch_uni_token_ids(wallet: str, count: int) -> list[int]:
    token_ids = []
    for index in range(count):
        result = eth_call(
            UNI_V3_NFT_MANAGER,
            TOKEN_OF_OWNER_BY_INDEX_SELECTOR + pad_address(wallet) + pad_uint(index),
        )
        token_ids.append(hex_to_int(result))
    return token_ids


def fetch_uni_position(token_id: int) -> dict[str, Any]:
    result = eth_call(UNI_V3_NFT_MANAGER, POSITIONS_SELECTOR + pad_uint(token_id))
    words = decode_uint_words(result)
    if len(words) < 12:
        raise RpcError("positions() returned too few fields")
    return {
        "token_id": token_id,
        "token0": decode_address_word(words[2]),
        "token1": decode_address_word(words[3]),
        "fee": words[4],
        "tick_lower": decode_signed_word(words[5]),
        "tick_upper": decode_signed_word(words[6]),
        "liquidity": words[7],
        "tokens_owed0": words[10],
        "tokens_owed1": words[11],
    }


def fetch_weth_usdt_slot0() -> dict[str, int]:
    result = eth_call(UNI_WETH_USDT_POOL, SLOT0_SELECTOR)
    words = decode_uint_words(result)
    if len(words) < 2:
        raise RpcError("slot0() returned too few fields")
    return {"sqrt_price_x96": words[0], "tick": decode_signed_word(words[1])}


def tick_to_sqrt_price(tick: int) -> float:
    return math.sqrt(1.0001**tick) * Q96


def tick_to_price(tick: int, token0_decimals: int = 18, token1_decimals: int = 6) -> float:
    raw_price = 1.0001**tick
    return raw_price * (10**token0_decimals) / (10**token1_decimals)


def get_uni_amounts(
    liquidity: int,
    sqrt_price_x96: int,
    tick_lower: int,
    tick_upper: int,
    current_tick: int,
) -> tuple[float, float]:
    sqrt_price = sqrt_price_x96 / Q96
    sqrt_lower = tick_to_sqrt_price(tick_lower) / Q96
    sqrt_upper = tick_to_sqrt_price(tick_upper) / Q96

    if current_tick < tick_lower:
        amount0 = liquidity * (1 / sqrt_lower - 1 / sqrt_upper)
        amount1 = 0
    elif current_tick >= tick_upper:
        amount0 = 0
        amount1 = liquidity * (sqrt_upper - sqrt_lower)
    else:
        amount0 = liquidity * (1 / sqrt_price - 1 / sqrt_upper)
        amount1 = liquidity * (sqrt_price - sqrt_lower)

    return max(amount0, 0), max(amount1, 0)


def fetch_unclaimed_fees_subgraph(token_ids: list[int]) -> list[dict[str, Any]]:
    if not token_ids:
        return []
    if not GRAPH_API_KEY:
        print("  Warning: GRAPH_API_KEY not set in config.py — fees shown as $0.00")
        return []

    ids = ", ".join(f'"{token_id}"' for token_id in token_ids)
    query = f"""
    {{
      positions(where: {{id_in: [{ids}]}}) {{
        id
        feeGrowthInside0LastX128
        feeGrowthInside1LastX128
        liquidity
        token0 {{
          symbol
          decimals
        }}
        token1 {{
          symbol
          decimals
        }}
        pool {{
          feeGrowthGlobal0X128
          feeGrowthGlobal1X128
          tick
        }}
        tickLower {{
          tickIdx
          feeGrowthOutside0X128
          feeGrowthOutside1X128
        }}
        tickUpper {{
          tickIdx
          feeGrowthOutside0X128
          feeGrowthOutside1X128
        }}
      }}
    }}
    """

    try:
        url = f"https://gateway.thegraph.com/api/{GRAPH_API_KEY}/subgraphs/id/{UNISWAP_V3_SUBGRAPH_ID}"
        response = requests.post(url, json={"query": query}, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data.get("errors"):
            print(f"  Warning: Subgraph query failed: {data['errors']}")
            return []
        return data.get("data", {}).get("positions", [])
    except Exception as exc:
        print(f"  Warning: Subgraph query failed: {exc}")
        return []


def compute_fees_from_subgraph(position: dict[str, Any], eth_price: float | None) -> tuple[float, float, float]:
    try:
        liquidity = int(position["liquidity"])
        if liquidity == 0:
            return 0.0, 0.0, 0.0

        fg0 = int(position["pool"]["feeGrowthGlobal0X128"])
        fg1 = int(position["pool"]["feeGrowthGlobal1X128"])
        current_tick = int(position["pool"]["tick"])

        tick_lower = position["tickLower"]
        tick_upper = position["tickUpper"]
        tick_lower_idx = int(tick_lower["tickIdx"])
        tick_upper_idx = int(tick_upper["tickIdx"])

        fo0_lower = int(tick_lower["feeGrowthOutside0X128"])
        fo1_lower = int(tick_lower["feeGrowthOutside1X128"])
        fo0_upper = int(tick_upper["feeGrowthOutside0X128"])
        fo1_upper = int(tick_upper["feeGrowthOutside1X128"])
        fi0 = int(position["feeGrowthInside0LastX128"])
        fi1 = int(position["feeGrowthInside1LastX128"])

        if current_tick >= tick_lower_idx:
            fb0 = fo0_lower
            fb1 = fo1_lower
        else:
            fb0 = (fg0 - fo0_lower) % Q256
            fb1 = (fg1 - fo1_lower) % Q256

        if current_tick < tick_upper_idx:
            fa0 = fo0_upper
            fa1 = fo1_upper
        else:
            fa0 = (fg0 - fo0_upper) % Q256
            fa1 = (fg1 - fo1_upper) % Q256

        fg_inside0 = (fg0 - fb0 - fa0) % Q256
        fg_inside1 = (fg1 - fb1 - fa1) % Q256

        token0_decimals = int(position["token0"]["decimals"])
        token1_decimals = int(position["token1"]["decimals"])
        amount0 = (liquidity * ((fg_inside0 - fi0) % Q256)) / Q128 / (10**token0_decimals)
        amount1 = (liquidity * ((fg_inside1 - fi1) % Q256)) / Q128 / (10**token1_decimals)

        token0_symbol = position["token0"]["symbol"]
        token1_symbol = position["token1"]["symbol"]
        usd = 0.0
        if token0_symbol in ("WETH", "ETH") and eth_price is not None:
            usd += amount0 * eth_price
        else:
            usd += amount0

        if token1_symbol in ("USDT", "USDC", "DAI"):
            usd += amount1
        elif token1_symbol in ("WETH", "ETH") and eth_price is not None:
            usd += amount1 * eth_price
        else:
            usd += amount1

        return amount0, amount1, max(0.0, usd)
    except Exception as exc:
        print(f"  Warning: Fee calculation failed for position: {exc}")
        return 0.0, 0.0, 0.0


def fetch_uni_position_details(wallet: str, eth_price: float | None) -> dict[str, Any]:
    count = fetch_uni_position_count(wallet)
    if count <= 0:
        return {
            "uni_positions": 0,
            "uni_position_ids": None,
            "uni_position_value": None,
            "uni_fees_unclaimed": None,
            "uni_weth_amount": None,
            "uni_usdt_amount": None,
            "uni_in_range": None,
            "uni_tick_lower": None,
            "uni_tick_upper": None,
            "uni_current_tick": None,
        }

    token_ids = fetch_uni_token_ids(wallet, count)
    slot0 = fetch_weth_usdt_slot0()
    total_value = 0.0
    total_weth = 0.0
    total_usdt = 0.0
    in_range_values = []
    tick_lowers = []
    tick_uppers = []
    active_ids = []
    closed_ids = []
    valued_any = False

    for token_id in token_ids:
        position = fetch_uni_position(token_id)
        liquidity = position["liquidity"]
        if liquidity == 0:
            closed_ids.append(token_id)
            continue

        token0 = position["token0"].lower()
        token1 = position["token1"].lower()
        if token0 != WETH.lower() or token1 != USDT.lower() or position["fee"] != 3000:
            print(f"Warning: unknown Uniswap pool for token ID #{token_id}; skipping value calculation")
            closed_ids.append(token_id)
            continue

        tick_lower = position["tick_lower"]
        tick_upper = position["tick_upper"]
        current_tick = slot0["tick"]
        in_range = tick_lower <= current_tick <= tick_upper
        amount0, amount1 = get_uni_amounts(
            liquidity,
            slot0["sqrt_price_x96"],
            tick_lower,
            tick_upper,
            current_tick,
        )
        weth_amount = amount0 / 1e18
        usdt_amount = amount1 / 1e6

        total_weth += weth_amount
        total_usdt += usdt_amount
        if eth_price is not None:
            total_value += weth_amount * eth_price + usdt_amount
            valued_any = True
        active_ids.append(token_id)
        in_range_values.append(1 if in_range else 0)
        tick_lowers.append(tick_lower)
        tick_uppers.append(tick_upper)

    total_fees = 0.0
    total_weth_fees = 0.0
    total_usdt_fees = 0.0
    subgraph_positions = fetch_unclaimed_fees_subgraph(active_ids)
    if active_ids and not subgraph_positions:
        print("  Warning: Subgraph unavailable — fees shown as $0.00")

    for subgraph_position in subgraph_positions:
        amount0, amount1, fee_usd = compute_fees_from_subgraph(subgraph_position, eth_price)
        total_fees += fee_usd
        token0_symbol = subgraph_position["token0"]["symbol"]
        token1_symbol = subgraph_position["token1"]["symbol"]
        print(f"  Subgraph token order for #{subgraph_position['id']}: token0={token0_symbol}, token1={token1_symbol}")
        if token0_symbol in ("WETH", "ETH"):
            total_weth_fees += amount0
        elif token0_symbol in ("USDT", "USDC", "DAI"):
            total_usdt_fees += amount0

        if token1_symbol in ("WETH", "ETH"):
            total_weth_fees += amount1
        elif token1_symbol in ("USDT", "USDC", "DAI"):
            total_usdt_fees += amount1

    return {
        "uni_positions": count,
        "uni_position_ids": ",".join(str(token_id) for token_id in token_ids),
        "uni_active_position_ids": ",".join(str(token_id) for token_id in active_ids) if active_ids else None,
        "uni_closed_position_ids": ",".join(str(token_id) for token_id in closed_ids) if closed_ids else None,
        "uni_position_value": total_value if valued_any else None,
        "uni_fees_unclaimed": total_fees if valued_any else None,
        "uni_weth_fees": total_weth_fees if valued_any else None,
        "uni_usdt_fees": total_usdt_fees if valued_any else None,
        "uni_weth_amount": total_weth if tick_lowers else None,
        "uni_usdt_amount": total_usdt if tick_lowers else None,
        "uni_in_range": 1 if in_range_values and all(in_range_values) else 0 if in_range_values else None,
        "uni_tick_lower": tick_lowers[0] if tick_lowers else None,
        "uni_tick_upper": tick_uppers[0] if tick_uppers else None,
        "uni_current_tick": slot0["tick"] if tick_lowers else None,
        "uni_price_lower": tick_to_price(tick_lowers[0]) if tick_lowers else None,
        "uni_price_upper": tick_to_price(tick_uppers[0]) if tick_uppers else None,
    }


def money(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"${value:,.2f}"


def number(value: float | int | None, digits: int = 2) -> str:
    if value is None:
        return "N/A"
    return f"{value:,.{digits}f}"


def percent(value: float | None, digits: int = 1) -> str:
    if value is None:
        return "N/A"
    return f"{value:,.{digits}f}%"


def signed_percent(value: float | None, digits: int = 1) -> str:
    if value is None:
        return "Need more data"
    return f"{value:+,.{digits}f}%"


def apy_value(value: float | None) -> str:
    if value is None:
        return "Not enough data"
    return percent(value, 1)


def signed_drop(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"-{number(value, 1)}%"


def truncated(address: str) -> str:
    if not isinstance(address, str) or len(address) < 12:
        return address
    return f"{address[:8]}...{address[-4:]}"


def js_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True).replace("</", "<\\/")


def compute_snapshot(
    raw: dict[str, Any],
    timestamp: str,
    previous_fees_usd: float | None = None,
    gas_eth: float = 0.0,
) -> dict[str, Any]:
    collateral = raw.get("aave_collateral")
    debt = raw.get("aave_debt")
    eth_main = raw.get("eth_main")
    eth_lp = raw.get("eth_lp")
    eth_price = raw.get("eth_price")
    btc_price = raw.get("btc_price")
    aweth_balance = raw.get("aweth_balance")
    awbtc_balance = raw.get("awbtc_balance")
    uni_position_value = raw.get("uni_position_value")
    vdusdt_balance = raw.get("vdusdt_balance")
    eth_supply_apy = raw.get("eth_supply_apy")
    usdt_borrow_apy = raw.get("usdt_borrow_apy")
    uni_fees_unclaimed = raw.get("uni_fees_unclaimed")

    aave_equity = collateral - debt if collateral is not None and debt is not None else None
    ltv_pct = (debt / collateral) * 100 if collateral and debt is not None else None
    eth_equity = (eth_main + eth_lp) * eth_price if None not in (eth_main, eth_lp, eth_price) else None
    total_equity = (
        aave_equity + eth_equity + (uni_position_value or 0)
        if aave_equity is not None and eth_equity is not None
        else None
    )
    btc_collateral_usd = awbtc_balance * btc_price if None not in (awbtc_balance, btc_price) else None
    liq_price_eth = None
    liq_price_btc = None
    correlated_liq_drop_pct = None
    correlated_liq_price_eth = None
    correlated_liq_price_btc = None
    aave_daily_carry = None
    uni_daily_fee_yield = 0.0 if previous_fees_usd is None else None
    gas_usd = gas_eth * eth_price if eth_price is not None else None
    gas_drag_pct = 0.0
    total_daily_yield = None

    if (
        debt is not None
        and btc_collateral_usd is not None
        and aweth_balance is not None
        and aweth_balance > 0
    ):
        liq_price_eth = (debt - btc_collateral_usd * BTC_LIQ_THRESHOLD) / (
            aweth_balance * ETH_LIQ_THRESHOLD
        )
        if liq_price_eth <= 0:
            liq_price_eth = None

    if (
        debt is not None
        and eth_price is not None
        and aweth_balance is not None
        and awbtc_balance is not None
        and awbtc_balance > 0
    ):
        liq_price_btc = (debt - aweth_balance * eth_price * ETH_LIQ_THRESHOLD) / (
            awbtc_balance * BTC_LIQ_THRESHOLD
        )
        if liq_price_btc <= 0:
            liq_price_btc = None

    if None not in (debt, aweth_balance, eth_price, awbtc_balance, btc_price):
        weighted_collateral = (
            aweth_balance * eth_price * ETH_LIQ_THRESHOLD
            + awbtc_balance * btc_price * BTC_LIQ_THRESHOLD
        )
        if weighted_collateral > debt:
            correlated_liq_drop_pct = (1 - debt / weighted_collateral) * 100
            correlated_liq_price_eth = eth_price * (1 - correlated_liq_drop_pct / 100)
            correlated_liq_price_btc = btc_price * (1 - correlated_liq_drop_pct / 100)

    if None not in (aweth_balance, eth_price, eth_supply_apy, vdusdt_balance, usdt_borrow_apy):
        aave_daily_carry = (
            aweth_balance * eth_price * (eth_supply_apy / 100) / 365
        ) - (vdusdt_balance * (usdt_borrow_apy / 100) / 365)

    if uni_fees_unclaimed is not None:
        if previous_fees_usd is None:
            uni_daily_fee_yield = 0.0
        else:
            uni_daily_fee_yield = max(0.0, uni_fees_unclaimed - previous_fees_usd)

    if aave_daily_carry is not None and uni_daily_fee_yield is not None:
        total_daily_yield = aave_daily_carry + uni_daily_fee_yield
        if gas_usd is not None and total_daily_yield > 0:
            gas_drag_pct = (gas_usd / total_daily_yield) * 100

    stable_value_usd = raw.get("uni_usdt_amount")
    # TODO: extend stable_buffer to include wallet stables + supplied stables on AAVE
    stable_buffer_pct = (
        stable_value_usd / total_equity * 100
        if stable_value_usd is not None and total_equity and total_equity > 0
        else 0
    )
    max_borrow_capacity, weighted_max_ltv = calc_weighted_borrow_capacity(
        aweth_balance,
        awbtc_balance,
        eth_price,
        btc_price,
        collateral,
    )
    borrow_usage_pct = (
        debt / max_borrow_capacity * 100
        if debt is not None and max_borrow_capacity and max_borrow_capacity > 0
        else 0
    )
    available_borrow = (
        max(0, max_borrow_capacity - debt)
        if debt is not None and max_borrow_capacity is not None
        else None
    )
    current_farm_apy = (
        uni_daily_fee_yield / uni_position_value * 365 * 100
        if uni_daily_fee_yield is not None and uni_position_value and uni_position_value > 0
        else 0
    )
    net_daily_yield = (
        uni_daily_fee_yield + aave_daily_carry
        if uni_daily_fee_yield is not None and aave_daily_carry is not None
        else None
    )
    net_farm_apy = (
        net_daily_yield / total_equity * 365 * 100
        if net_daily_yield is not None and total_equity and total_equity > 0
        else 0
    )
    apy_7d = calc_rolling_apy(DB_FILE, 7, uni_position_value)
    apy_30d = calc_rolling_apy(DB_FILE, 30, uni_position_value)
    in_range = raw.get("uni_in_range") == 1
    farm_apy_quality = apy_quality(current_farm_apy, in_range, uni_position_value)
    risk_state = calc_risk_state(raw.get("health_factor"), stable_buffer_pct, borrow_usage_pct)
    coll_growth_30d, debt_growth_30d, flywheel_expansion = calc_flywheel(DB_FILE, 30)

    eth_aave = aweth_balance or 0
    eth_wallet = (eth_main or 0) + (eth_lp or 0)
    eth_lp_amount = raw.get("uni_weth_amount") or 0
    total_eth_units = eth_aave + eth_wallet + eth_lp_amount
    total_eth_value = total_eth_units * eth_price if eth_price is not None else None
    btc_aave = awbtc_balance or 0
    total_btc_units = btc_aave
    total_btc_value = total_btc_units * btc_price if btc_price is not None else None
    # Stable position
    stable_lp = raw.get("uni_usdt_amount") or 0  # USDT in active LP position
    stable_debt = vdusdt_balance if vdusdt_balance and vdusdt_balance > 0 else debt or 0
    # TODO: if USDC debt is added later, sum here: stable_debt += vdusdc_balance

    stable_debt_usd = stable_debt  # USDT is 1:1 USD
    net_stable = stable_lp - stable_debt_usd

    return {
        "timestamp": timestamp,
        "eth_price": eth_price,
        "btc_price": btc_price,
        "eth_main": eth_main,
        "eth_lp": eth_lp,
        "aave_collateral": collateral,
        "aave_debt": debt,
        "aave_equity": aave_equity,
        "health_factor": raw.get("health_factor"),
        "ltv_pct": ltv_pct,
        "aweth_balance": aweth_balance,
        "awbtc_balance": awbtc_balance,
        "vdusdt_balance": vdusdt_balance,
        "uni_positions": raw.get("uni_positions"),
        "uni_position_ids": raw.get("uni_position_ids"),
        "uni_active_position_ids": raw.get("uni_active_position_ids"),
        "uni_closed_position_ids": raw.get("uni_closed_position_ids"),
        "uni_position_value": uni_position_value,
        "uni_fees_unclaimed": raw.get("uni_fees_unclaimed"),
        "uni_weth_fees": raw.get("uni_weth_fees"),
        "uni_usdt_fees": raw.get("uni_usdt_fees"),
        "uni_weth_amount": raw.get("uni_weth_amount"),
        "uni_usdt_amount": raw.get("uni_usdt_amount"),
        "uni_in_range": raw.get("uni_in_range"),
        "uni_tick_lower": raw.get("uni_tick_lower"),
        "uni_tick_upper": raw.get("uni_tick_upper"),
        "uni_current_tick": raw.get("uni_current_tick"),
        "uni_price_lower": raw.get("uni_price_lower"),
        "uni_price_upper": raw.get("uni_price_upper"),
        "liq_price_eth": liq_price_eth,
        "liq_price_btc": liq_price_btc,
        "correlated_liq_drop_pct": correlated_liq_drop_pct,
        "correlated_liq_price_eth": correlated_liq_price_eth,
        "correlated_liq_price_btc": correlated_liq_price_btc,
        "eth_supply_apy": eth_supply_apy,
        "usdt_borrow_apy": usdt_borrow_apy,
        "aave_daily_carry": aave_daily_carry,
        "uni_daily_fee_yield": uni_daily_fee_yield,
        "gas_eth": gas_eth,
        "gas_usd": gas_usd,
        "gas_drag_pct": gas_drag_pct,
        "total_daily_yield": total_daily_yield,
        "total_equity": total_equity,
        "stable_value_usd": stable_value_usd,
        "stable_buffer_pct": stable_buffer_pct,
        "weighted_max_ltv": weighted_max_ltv,
        "max_borrow_capacity": max_borrow_capacity,
        "borrow_usage_pct": borrow_usage_pct,
        "current_farm_apy": current_farm_apy,
        "net_daily_yield": net_daily_yield,
        "net_farm_apy": net_farm_apy,
        "apy_7d": apy_7d,
        "apy_30d": apy_30d,
        "apy_quality": farm_apy_quality,
        "risk_state": risk_state,
        "coll_growth_30d": coll_growth_30d,
        "debt_growth_30d": debt_growth_30d,
        "flywheel_expansion": flywheel_expansion,
        "available_borrow": available_borrow,
        "eth_aave": eth_aave,
        "eth_wallet": eth_wallet,
        "eth_lp_amount": eth_lp_amount,
        "total_eth_units": total_eth_units,
        "total_eth_value": total_eth_value,
        "btc_aave": btc_aave,
        "total_btc_units": total_btc_units,
        "total_btc_value": total_btc_value,
        "stable_lp": stable_lp,
        "stable_debt": stable_debt,
        "stable_debt_usd": stable_debt_usd,
        "net_stable": net_stable,
        "current_stage": CURRENT_STAGE,
        "notes": raw.get("notes"),
    }


def health_class(health_factor: float | None) -> str:
    if health_factor is None:
        return "muted"
    if health_factor >= 1.8:
        return "green"
    if health_factor >= 1.6:
        return "amber"
    return "red"


def liquidation_buffer(current_price: float | None, liquidation_price: float | None) -> float | None:
    if current_price is None or liquidation_price is None or current_price <= 0:
        return None
    return ((current_price - liquidation_price) / current_price) * 100


def liquidation_risk_class(*buffers: float | None) -> str:
    known_buffers = [buffer for buffer in buffers if buffer is not None]
    if not known_buffers:
        return "green"
    if any(buffer < 15 for buffer in known_buffers):
        return "red"
    if any(buffer <= 30 for buffer in known_buffers):
        return "amber"
    return "green"


def market_drop_class(drop_pct: float | None) -> str:
    if drop_pct is None:
        return "muted"
    if drop_pct < 20:
        return "red"
    if drop_pct <= 35:
        return "amber"
    return "green"


def liquidation_status(drop_pct: float | None) -> tuple[str, str]:
    risk_class = market_drop_class(drop_pct)
    if risk_class == "red":
        return "DANGER", "red"
    if risk_class == "amber":
        return "WATCH", "amber"
    if risk_class == "green":
        return "SAFE", "green"
    return "UNKNOWN", "muted"


def uni_status(snapshot: dict[str, Any]) -> tuple[str, str, str]:
    if snapshot.get("uni_in_range") is None:
        return "No active positions", "muted", "muted"
    if snapshot.get("uni_in_range") == 1:
        return "In Range", "green", "green"
    return "Out of Range", "red", "red"


def format_uni_ids(position_ids: str | None) -> str:
    if not position_ids:
        return "N/A"
    return ", ".join(f"#{token_id}" for token_id in position_ids.split(","))


def whole_money(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"${value:,.0f}"


def calc_weighted_borrow_capacity(
    aweth_balance: float | None,
    awbtc_balance: float | None,
    eth_price: float | None,
    btc_price: float | None,
    aave_collateral: float | None,
) -> tuple[float | None, float | None]:
    if aave_collateral is None:
        return None, None

    eth_collateral_usd = (
        aweth_balance * eth_price
        if None not in (aweth_balance, eth_price)
        else 0
    )
    btc_collateral_usd = (
        awbtc_balance * btc_price
        if None not in (awbtc_balance, btc_price)
        else 0
    )
    total_collateral_usd = eth_collateral_usd + btc_collateral_usd

    if total_collateral_usd > 0:
        weighted_max_ltv = (
            (eth_collateral_usd * ETH_MAX_LTV)
            + (btc_collateral_usd * WBTC_MAX_LTV)
        ) / total_collateral_usd
    else:
        weighted_max_ltv = 0.75

    return aave_collateral * weighted_max_ltv, weighted_max_ltv


def calc_rolling_apy(db_path: Path, days: int, current_lp_value: float | None) -> float | None:
    """Calculate rolling average farm APY from last N snapshots."""
    import sqlite3

    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT uni_daily_fee_yield FROM daily_snapshots "
            "WHERE uni_daily_fee_yield IS NOT NULL "
            "ORDER BY id DESC LIMIT ?",
            (days,),
        )
        rows = cur.fetchall()
        conn.close()
        if len(rows) < 2:
            return None
        avg_daily = sum(row[0] for row in rows) / len(rows)
        return (avg_daily / current_lp_value * 365 * 100) if current_lp_value and current_lp_value > 0 else None
    except Exception:
        return None


def apy_quality(current_farm_apy: float | None, in_range: bool, uni_position_value: float | None) -> str:
    current_farm_apy = current_farm_apy or 0
    if not uni_position_value or uni_position_value < 100:
        return "Distorted"
    if not in_range:
        return "Weak"
    if current_farm_apy > 80:
        return "Distorted"
    if current_farm_apy > 30:
        return "Strong"
    if current_farm_apy > 10:
        return "Normal"
    return "Weak"


def calc_risk_state(hf, stable_buffer_pct, borrow_usage_pct):
    hf = hf or 0
    stable_buffer_pct = stable_buffer_pct or 0
    borrow_usage_pct = borrow_usage_pct or 0

    # Overextended: hard risk triggers only
    if hf < 1.60 or borrow_usage_pct > 85:
        return "Overextended"

    # Aggressive: moderate risk on any dimension
    if hf < 1.80 or borrow_usage_pct >= 70:
        return "Aggressive"

    # At this point: HF >= 1.80 AND borrow_usage < 70
    # Defensive requires strong stable buffer too
    if stable_buffer_pct >= 25:
        return "Defensive"

    # Balanced: good HF and borrow usage, but low stable buffer
    return "Balanced"


def calc_flywheel(db_path: Path, days: int = 30) -> tuple[float | None, float | None, float | None]:
    """Calculate collateral and debt growth over last N snapshots."""
    import sqlite3

    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT aave_collateral, aave_debt FROM daily_snapshots "
            "WHERE aave_collateral IS NOT NULL "
            "ORDER BY id DESC LIMIT ?",
            (days,),
        )
        rows = cur.fetchall()
        conn.close()
        if len(rows) < 2:
            return None, None, None
        oldest = rows[-1]
        newest = rows[0]
        coll_growth = (newest[0] - oldest[0]) / oldest[0] * 100 if oldest[0] else 0
        debt_growth = (newest[1] - oldest[1]) / oldest[1] * 100 if oldest[1] else 0
        net_expansion = coll_growth - debt_growth
        return coll_growth, debt_growth, net_expansion
    except Exception:
        return None, None, None


def metric_class(value: float | None, green_at: float, amber_at: float, lower_is_better: bool = False) -> str:
    if value is None:
        return "muted"
    if lower_is_better:
        if value < green_at:
            return "green"
        if value <= amber_at:
            return "amber"
        return "red"
    if value >= green_at:
        return "green"
    if value >= amber_at:
        return "amber"
    return "red"


def risk_state_class(risk_state: str) -> str:
    return {
        "Defensive": "green",
        "Balanced": "blue",
        "Aggressive": "amber",
        "Overextended": "red",
    }.get(risk_state, "muted")


def risk_state_subtitle(risk_state: str, stable_buffer_pct: float | None) -> str:
    if risk_state == "Balanced" and (stable_buffer_pct or 0) < 25:
        return "Balanced · LP stable buffer low"
    if risk_state == "Defensive":
        return "HF + Borrow + Buffer all strong"
    if risk_state == "Aggressive":
        return "One or more risk dimensions elevated"
    if risk_state == "Overextended":
        return "HF or borrow usage at critical level"
    return "HF + Buffer + Borrow"


def build_risk_alerts(snapshot: dict[str, Any]) -> list[tuple[str, str]]:
    alerts = []
    hf = snapshot.get("health_factor")
    if hf is not None and hf < 1.60:
        alerts.append(("red", "⚠️ Health Factor is critically low. Consider adding collateral immediately."))
    elif hf is not None and hf < 1.80:
        alerts.append(("amber", "Health Factor is below target (1.80). Monitor closely and avoid new borrowing."))
    if snapshot.get("stable_buffer_pct") is not None and snapshot["stable_buffer_pct"] < 25:
        alerts.append(("amber", "Stable buffer is below 25%. Consider strengthening stable reserves."))
    if snapshot.get("borrow_usage_pct") is not None and snapshot["borrow_usage_pct"] > 85:
        alerts.append(("amber", "Borrow usage is above 85%. Avoid new borrowing until collateral improves."))
    if snapshot.get("uni_in_range") == 0:
        alerts.append(("amber", "Uniswap LP is out of range. Fees have stopped accruing."))
    if snapshot.get("gas_drag_pct") is not None and snapshot["gas_drag_pct"] > 20:
        alerts.append(("amber", "Gas costs are consuming more than 20% of daily yield."))
    if (
        snapshot.get("aave_daily_carry") is not None
        and snapshot.get("uni_daily_fee_yield") is not None
        and snapshot["aave_daily_carry"] < 0
        and abs(snapshot["aave_daily_carry"]) > snapshot["uni_daily_fee_yield"]
    ):
        alerts.append(("amber", "AAVE borrow cost exceeds LP fee income. Net yield is negative."))
    return alerts


def generate_dashboard(snapshot: dict[str, Any], history: list[dict[str, Any]]) -> None:
    labels = [row["timestamp"][:10] for row in history]
    total_equity = [row.get("total_equity") for row in history]
    ltv_values = [row.get("ltv_pct") for row in history]
    fee_yields = [row.get("uni_daily_fee_yield") for row in history]
    aave_carries = [row.get("aave_daily_carry") for row in history]
    cumulative_fee_yields = []
    cumulative_aave_carries = []
    cumulative_net_outputs = []
    total_eth_exposures = []
    total_btc_exposures = []
    running_fees = 0.0
    running_aave = 0.0
    for row, fee_value, carry_value in zip(history, fee_yields, aave_carries):
        running_fees += fee_value or 0
        running_aave += carry_value or 0
        cumulative_fee_yields.append(running_fees)
        cumulative_aave_carries.append(running_aave)
        cumulative_net_outputs.append(running_fees + running_aave)
        total_eth_exposures.append(
            (row.get("aweth_balance") or 0)
            + (row.get("eth_main") or 0)
            + (row.get("eth_lp") or 0)
            + (row.get("uni_weth_amount") or 0)
        )
        total_btc_exposures.append(row.get("awbtc_balance"))
    show_unit_chart = any(value is not None for value in total_btc_exposures) or any(
        value for value in total_eth_exposures
    )

    hf = snapshot.get("health_factor")
    banner_class = health_class(hf)
    eth_total = (
        snapshot["eth_main"] + snapshot["eth_lp"]
        if snapshot.get("eth_main") is not None and snapshot.get("eth_lp") is not None
        else None
    )
    eth_value = eth_total * snapshot["eth_price"] if eth_total is not None and snapshot.get("eth_price") is not None else None
    uni_status_text, uni_status_class, uni_dot_class = uni_status(snapshot)
    active_ids = format_uni_ids(snapshot.get("uni_active_position_ids"))
    closed_ids = format_uni_ids(snapshot.get("uni_closed_position_ids"))
    uni_weth_value = (
        snapshot["uni_weth_amount"] * snapshot["eth_price"]
        if snapshot.get("uni_weth_amount") is not None and snapshot.get("eth_price") is not None
        else None
    )
    risk_label, risk_class = liquidation_status(snapshot.get("correlated_liq_drop_pct"))
    risk_display = risk_label.title()
    carry_class = "green" if (snapshot.get("aave_daily_carry") or 0) >= 0 else "red"
    gas_row = ""
    if snapshot.get("gas_usd") is not None and snapshot.get("gas_usd") > 0:
        gas_row = f"""
    <section class="gas-row">
      Gas today: {number(snapshot.get("gas_eth"), 6)} ETH ({money(snapshot.get("gas_usd"))}) | Gas drag: {percent(snapshot.get("gas_drag_pct"), 1)} of yield
    </section>
"""
    range_position = 50
    if None not in (snapshot.get("uni_price_lower"), snapshot.get("uni_price_upper"), snapshot.get("eth_price")):
        price_width = snapshot["uni_price_upper"] - snapshot["uni_price_lower"]
        if price_width > 0:
            range_position = max(
                0,
                min(
                    100,
                    ((snapshot["eth_price"] - snapshot["uni_price_lower"]) / price_width) * 100,
                ),
            )
    liquidation_equity_threshold = snapshot.get("aave_debt")
    stable_class = metric_class(snapshot.get("stable_buffer_pct"), 25, 15)
    borrow_usage_class = metric_class(snapshot.get("borrow_usage_pct"), 70, 85, lower_is_better=True)
    risk_state_color = risk_state_class(snapshot.get("risk_state", ""))
    risk_state_note = risk_state_subtitle(snapshot.get("risk_state", ""), snapshot.get("stable_buffer_pct"))
    risk_alerts = build_risk_alerts(snapshot)
    risk_alerts_html = ""
    if risk_alerts:
        alert_items = "\n".join(
            f'      <div class="alert {alert_class}">{escape(message)}</div>'
            for alert_class, message in risk_alerts
        )
        risk_alerts_html = f"""
    <section class="alerts">
{alert_items}
    </section>
"""
    net_stable_class = "green" if (snapshot.get("net_stable") or 0) > 0 else "red"
    lp_stable_pct = (
        snapshot["uni_usdt_amount"] / snapshot["uni_position_value"] * 100
        if snapshot.get("uni_usdt_amount") is not None
        and snapshot.get("uni_position_value")
        and snapshot["uni_position_value"] > 0
        else None
    )
    cumulative_lp_fees = cumulative_fee_yields[-1] if cumulative_fee_yields else None
    cumulative_aave_carry = cumulative_aave_carries[-1] if cumulative_aave_carries else None
    cumulative_net_output = cumulative_net_outputs[-1] if cumulative_net_outputs else None
    unit_chart_html = ""
    if show_unit_chart:
        unit_chart_html = """
      <div class="card"><h2>Unit Accumulation Over Time</h2><div class="chart-wrap"><canvas id="unitAccumulationChart"></canvas></div><div class="subvalue">Includes LP exposure; LP assets may be used to repay debt.</div></div>"""

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>DeFi Portfolio Tracker</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <style>
    :root {{
      --bg: #0f1115;
      --card: #1a1d24;
      --border: #262a33;
      --text: #e5e7eb;
      --muted: #9ca3af;
      --green: #34d399;
      --red: #f87171;
      --blue: #818cf8;
      --amber: #fbbf24;
      --indigo: #a5b4fc;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.5;
    }}
    main {{ width: min(1180px, calc(100% - 32px)); margin: 0 auto; padding: 32px 0; }}
    header {{ display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 24px; }}
    .refresh-btn {{
      background: #262a33;
      color: #e5e7eb;
      border: 1px solid #34d399;
      border-radius: 8px;
      cursor: pointer;
      font: inherit;
      font-weight: 700;
      padding: 10px 14px;
      transition: background 120ms ease, color 120ms ease;
      white-space: nowrap;
    }}
    .refresh-btn:hover:not(:disabled) {{ background: #34d399; color: #0f1115; }}
    .refresh-btn:disabled {{ cursor: wait; opacity: 0.75; }}
    .toast {{
      position: fixed;
      right: 18px;
      top: 18px;
      display: none;
      background: #1a1d24;
      border: 1px solid #f87171;
      border-radius: 8px;
      color: #e5e7eb;
      padding: 12px 14px;
      z-index: 10;
    }}
    h1 {{ margin: 0 0 6px; font-size: 32px; font-weight: 750; }}
    h2 {{ margin: 0 0 14px; font-size: 18px; }}
    .subtitle, .muted {{ color: var(--muted); }}
    .card {{
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 18px;
    }}
    .section-title {{ margin: 26px 0 14px; font-size: 18px; font-weight: 760; }}
    .alerts {{ display: grid; gap: 10px; margin-bottom: 20px; }}
    .alert {{
      background: rgba(251, 191, 36, 0.06);
      border: 1px solid var(--amber);
      border-left-width: 5px;
      border-radius: 8px;
      padding: 13px 16px;
      color: var(--text);
    }}
    .alert.red {{
      background: rgba(248, 113, 113, 0.08);
      border-color: var(--red);
    }}
    .banner {{
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 16px;
      margin-bottom: 20px;
      border-left: 5px solid var(--muted);
    }}
    .banner.green {{ border-left-color: var(--green); }}
    .banner.amber {{ border-left-color: var(--amber); }}
    .banner.red {{ border-left-color: var(--red); }}
    .risk-box {{
      margin-bottom: 20px;
      border-left: 5px solid var(--muted);
    }}
    .risk-box.green {{ border-left-color: var(--green); }}
    .risk-box.amber {{ border-left-color: var(--amber); }}
    .risk-box.red {{ border-left-color: var(--red); }}
    .risk-grid {{ display: grid; grid-template-columns: 190px 1fr; gap: 8px 18px; }}
    .risk-lead {{ font-size: 32px; font-weight: 760; margin-bottom: 4px; }}
    .risk-copy {{ color: var(--muted); margin-bottom: 16px; }}
    .risk-status {{ margin-top: 14px; font-weight: 720; }}
    .health-grid {{ display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 14px; margin-bottom: 20px; }}
    .compact-risk {{ border-left: 5px solid var(--muted); }}
    .compact-risk.green {{ border-left-color: var(--green); }}
    .compact-risk.amber {{ border-left-color: var(--amber); }}
    .compact-risk.red {{ border-left-color: var(--red); }}
    .mini-list {{ display: grid; gap: 5px; margin-top: 8px; font-size: 12px; color: var(--muted); }}
    .mini-list strong {{ color: var(--text); font-weight: 700; }}
    .uni-card {{ margin-top: 20px; }}
    .uni-grid {{ display: grid; grid-template-columns: 160px 1fr; gap: 9px 14px; }}
    .active-farm {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; margin-bottom: 20px; }}
    .farm-panel {{ min-width: 0; }}
    .farm-panel h3 {{ margin: 0 0 12px; font-size: 15px; }}
    .status-dot {{ display: inline-block; width: 9px; height: 9px; border-radius: 999px; margin-right: 7px; background: var(--muted); }}
    .status-dot.green {{ background: var(--green); }}
    .status-dot.red {{ background: var(--red); }}
    .range-labels {{ display: flex; justify-content: space-between; margin-top: 14px; color: var(--muted); font-size: 13px; }}
    .range-bar {{
      position: relative;
      height: 14px;
      margin: 8px 0 20px;
      border-radius: 999px;
      background: linear-gradient(90deg, var(--red) 0 10%, var(--green) 10% 90%, var(--red) 90% 100%);
    }}
    .range-dot {{
      position: absolute;
      left: var(--range-position);
      top: 50%;
      width: 18px;
      height: 18px;
      border: 3px solid #ffffff;
      border-radius: 999px;
      background: var(--card);
      transform: translate(-50%, -50%);
      box-shadow: 0 0 0 2px rgba(15, 17, 21, 0.85);
    }}
    .range-now {{ text-align: center; color: var(--text); font-weight: 700; }}
    .range-caption {{ margin-top: 18px; color: var(--muted); }}
    .gas-row {{
      margin: -8px 0 20px;
      color: var(--muted);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 12px 14px;
      background: rgba(251, 191, 36, 0.06);
    }}
    .label {{ color: var(--muted); font-size: 13px; }}
    .value {{ margin-top: 4px; font-size: 24px; font-weight: 720; }}
    .subvalue {{ margin-top: 7px; color: var(--muted); font-size: 12px; }}
    .grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; margin-bottom: 20px; }}
    .grid.five {{ grid-template-columns: repeat(5, minmax(0, 1fr)); }}
    .grid.three {{ grid-template-columns: repeat(3, minmax(0, 1fr)); }}
    .context-row {{
      margin: -4px 0 20px;
      color: var(--muted);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 12px 14px;
      background: rgba(129, 140, 248, 0.06);
    }}
    .placeholder {{
      white-space: pre-line;
      color: var(--muted);
      line-height: 1.7;
    }}
    .kpi .value {{ font-size: 20px; }}
    .charts {{ display: grid; gap: 20px; margin-bottom: 20px; }}
    .chart-wrap {{ height: 320px; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ padding: 13px 10px; border-bottom: 1px solid var(--border); text-align: left; }}
    th {{ color: var(--muted); font-size: 13px; font-weight: 600; }}
    tr:last-child td {{ border-bottom: 0; }}
    .two-col {{ display: grid; grid-template-columns: 2fr 1fr; gap: 20px; }}
    .green {{ color: var(--green); }}
    .red {{ color: var(--red); }}
    .blue {{ color: var(--blue); }}
    .amber {{ color: var(--amber); }}
    .indigo {{ color: var(--indigo); }}
    footer {{ margin-top: 24px; color: var(--muted); font-size: 13px; text-align: center; }}
    @media (max-width: 820px) {{
      main {{ width: min(100% - 20px, 1180px); padding: 20px 0; }}
      .grid, .grid.five, .grid.three, .health-grid, .active-farm, .banner, .two-col {{ grid-template-columns: 1fr; }}
      header {{ display: block; }}
      .refresh-btn {{ margin-top: 12px; }}
      h1 {{ font-size: 26px; }}
      .chart-wrap {{ height: 280px; }}
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <h1>DeFi Portfolio Tracker</h1>
        <div class="subtitle">{escape(snapshot["timestamp"])} | MAIN {escape(truncated(MAIN_WALLET))} | LP {escape(truncated(LP_WALLET))}</div>
      </div>
      <button class="refresh-btn" onclick="refreshData()">&#10227; Refresh</button>
    </header>
    <div class="toast" id="toast">Start tracker.py in Terminal first</div>
{risk_alerts_html}

    <h2 class="section-title">SYSTEM HEALTH</h2>
    <section class="health-grid">
      <div class="card kpi"><div class="label">Health Factor</div><div class="value {banner_class}">{number(hf, 3)}</div><div class="subvalue">Target &ge;1.80 &middot; Floor 1.60</div></div>
      <div class="card kpi"><div class="label">LP Stable Buffer</div><div class="value {stable_class}">{percent(snapshot.get("stable_buffer_pct"), 1)}</div><div class="subvalue">Currently counts USDT inside active LP only.</div></div>
      <div class="card kpi"><div class="label">Borrow Usage</div><div class="value {borrow_usage_class}">{percent(snapshot.get("borrow_usage_pct"), 1)}</div><div class="subvalue">Capacity {whole_money(snapshot.get("max_borrow_capacity"))} &middot; Used {whole_money(snapshot.get("aave_debt"))}</div></div>
      <div class="card kpi"><div class="label">Current Stage</div><div class="value indigo">{escape(snapshot.get("current_stage") or CURRENT_STAGE)}</div><div class="subvalue">DeFi Path</div></div>
      <div class="card kpi"><div class="label">Risk State</div><div class="value {risk_state_color}">{escape(snapshot.get("risk_state", "N/A"))}</div><div class="subvalue">{escape(risk_state_note)}</div></div>
      <div class="card kpi compact-risk {risk_class}"><div class="label">Liquidation Risk</div><div class="value {risk_class}">{percent(snapshot.get("correlated_liq_drop_pct"))}</div><div class="mini-list"><span>ETH liq <strong>{whole_money(snapshot.get("correlated_liq_price_eth"))}</strong></span><span>BTC liq <strong>{whole_money(snapshot.get("correlated_liq_price_btc"))}</strong></span><span>Status <strong class="{risk_class}">{escape(risk_display)}</strong></span></div></div>
    </section>

    <h2 class="section-title">ACTIVE FARM</h2>
    <section class="active-farm">
      <div class="card farm-panel">
        <h3>Farm Status</h3>
        <div class="uni-grid">
          <div class="label">Pair</div><div>WETH / USDT 0.3%</div>
          <div class="label">Status</div><div class="{uni_status_class}"><span class="status-dot {uni_dot_class}"></span>{escape(uni_status_text)}</div>
          <div class="label">Current price</div><div>{whole_money(snapshot.get("eth_price"))}</div>
          <div class="label">Range</div><div>{whole_money(snapshot.get("uni_price_lower"))} - {whole_money(snapshot.get("uni_price_upper"))}</div>
          <div class="label">Position value</div><div>{money(snapshot.get("uni_position_value"))}</div>
          <div class="label">Active ID</div><div>{escape(active_ids)}</div>
        </div>
      </div>
      <div class="card farm-panel">
        <h3>APY / Output</h3>
        <div class="uni-grid">
          <div class="label">Current Farm APY</div><div class="green">{percent(snapshot.get("current_farm_apy"), 1)}</div>
          <div class="label">7d APY</div><div>{apy_value(snapshot.get("apy_7d"))}</div>
          <div class="label">30d APY</div><div>{apy_value(snapshot.get("apy_30d"))}</div>
          <div class="label">Daily LP fees</div><div>{money(snapshot.get("uni_daily_fee_yield"))}</div>
          <div class="label">Cumulative LP fees</div><div>{money(cumulative_lp_fees)}</div>
          <div class="label">Cumulative AAVE carry</div><div>{money(cumulative_aave_carry)}</div>
          <div class="label">Total cumulative net</div><div>{money(cumulative_net_output)}</div>
          <div class="label">Unclaimed fees</div><div>{money(snapshot.get("uni_fees_unclaimed"))}</div>
        </div>
      </div>
      <div class="card farm-panel">
        <h3>Composition</h3>
        <div class="uni-grid">
          <div class="label">ETH amount</div><div>{number(snapshot.get("uni_weth_amount"), 4)} ETH <span class="muted">({money(uni_weth_value)})</span></div>
          <div class="label">USDT amount</div><div>{number(snapshot.get("uni_usdt_amount"), 2)} USDT</div>
          <div class="label">LP stable %</div><div>{percent(lp_stable_pct, 1)}</div>
          <div class="label">APY quality</div><div>{escape(snapshot.get("apy_quality", "N/A"))}</div>
        </div>
        <div class="range-caption">ETH/USDT 0.3% &middot; {escape(uni_status_text)}</div>
        <div class="range-labels"><span>{whole_money(snapshot.get("uni_price_lower"))}</span><span>{whole_money(snapshot.get("uni_price_upper"))}</span></div>
        <div class="range-bar" style="--range-position: {range_position:.2f}%"><span class="range-dot"></span></div>
        <div class="range-now">{whole_money(snapshot.get("eth_price"))}</div>
      </div>
    </section>
    <div class="context-row">APY {percent(snapshot.get("current_farm_apy"), 1)} &nbsp; | &nbsp; HF {number(hf, 3)} &nbsp; | &nbsp; Borrow Usage {percent(snapshot.get("borrow_usage_pct"), 1)} &nbsp; | &nbsp; Stable Buffer {percent(snapshot.get("stable_buffer_pct"), 1)}</div>

    <h2 class="section-title">FLYWHEEL STRENGTH</h2>
    <section class="grid">
      <div class="card kpi"><div class="label">Collateral Growth 30d</div><div class="value">{signed_percent(snapshot.get("coll_growth_30d"))}</div></div>
      <div class="card kpi"><div class="label">Debt Growth 30d</div><div class="value">{signed_percent(snapshot.get("debt_growth_30d"))}</div></div>
      <div class="card kpi"><div class="label">Net Flywheel Expansion</div><div class="value">{signed_percent(snapshot.get("flywheel_expansion"))}</div></div>
      <div class="card kpi"><div class="label">Available Borrow Optionality</div><div class="value indigo">{money(snapshot.get("available_borrow"))}</div><div class="subvalue">Optionality, not target</div></div>
    </section>

    <h2 class="section-title">UNIT ACCUMULATION</h2>
    <section class="grid three">
      <div class="card kpi"><div class="label">Total ETH Exposure</div><div class="value">{number(snapshot.get("total_eth_units"), 4)} ETH <span class="muted">({money(snapshot.get("total_eth_value"))})</span></div><div class="subvalue">AAVE collateral: {number(snapshot.get("eth_aave"), 4)} permanent core collateral<br>LP exposure: {number(snapshot.get("eth_lp_amount"), 4)} active farm exposure, funded by borrowed stables<br>Wallet: {number(snapshot.get("eth_wallet"), 4)}</div></div>
      <div class="card kpi"><div class="label">Total BTC Exposure</div><div class="value">{number(snapshot.get("total_btc_units"), 6)} BTC <span class="muted">({money(snapshot.get("total_btc_value"))})</span></div><div class="subvalue">AAVE collateral: {number(snapshot.get("btc_aave"), 6)} permanent core collateral<br>LP BTC exposure: 0.000000 active farm exposure</div></div>
      <div class="card kpi"><div class="label">Net Stable Position</div><div class="value {net_stable_class}">Net stable: {money(snapshot.get("net_stable"))}</div><div class="subvalue">LP stables minus AAVE stable debt<br>LP stables: {money(snapshot.get("stable_lp"))}<br>AAVE stable debt: -{money(snapshot.get("stable_debt_usd"))}</div></div>
    </section>
{gas_row}

    <h2 class="section-title">CORE CHARTS</h2>
    <section class="charts">
      <div class="card"><h2>Total Equity Trend</h2><div class="chart-wrap"><canvas id="equityChart"></canvas></div></div>
      <div class="card"><h2>LTV Over Time</h2><div class="chart-wrap"><canvas id="ltvChart"></canvas></div></div>
      <div class="card"><h2>Daily Yield Breakdown</h2><div class="chart-wrap"><canvas id="dailyYieldChart"></canvas></div></div>
      <div class="card"><h2>Cumulative Farm Output</h2><div class="chart-wrap"><canvas id="cumulativeFarmOutputChart"></canvas></div></div>
{unit_chart_html}
    </section>

    <h2 class="section-title">STRATEGY vs HODL</h2>
    <section class="card">
      <div class="placeholder">Baseline not configured yet.
Add BASELINE_ETH, BASELINE_BTC
and BASELINE_STABLES to
config.py to enable this.</div>
    </section>

    <section class="two-col">
      <div class="card">
        <h2>Position table</h2>
        <table>
          <thead><tr><th>Position</th><th>Metric 1</th><th>Metric 2</th><th>Metric 3</th><th>Metric 4</th></tr></thead>
          <tbody>
            <tr><td>Portfolio</td><td>{money(snapshot.get("total_equity"))} total equity</td><td>{money(snapshot.get("eth_price"))} ETH</td><td>{money(snapshot.get("btc_price"))} BTC</td><td>{money(snapshot.get("total_daily_yield"))} daily yield</td></tr>
            <tr><td>AAVE</td><td>{money(snapshot.get("aave_collateral"))} collateral</td><td>{money(snapshot.get("aave_debt"))} debt</td><td>{money(snapshot.get("aave_equity"))} equity</td><td>HF {number(hf, 3)} | LTV {number(snapshot.get("ltv_pct"))}%</td></tr>
            <tr><td>ETH Balances</td><td>{number(snapshot.get("eth_main"), 6)} main</td><td>{number(snapshot.get("eth_lp"), 6)} LP</td><td>{number(eth_total, 6)} total ETH</td><td>{money(eth_value)}</td></tr>
          </tbody>
        </table>
      </div>
    </section>

    <footer>Generated: {escape(snapshot["timestamp"])} | Data: ethereum-rpc.publicnode.com | All data is read-only on-chain</footer>
  </main>

  <script>
    async function refreshData() {{
      const btn = document.querySelector(".refresh-btn");
      const toast = document.getElementById("toast");
      btn.textContent = "Fetching...";
      btn.disabled = true;
      try {{
        const response = await fetch("/refresh");
        if (!response.ok) throw new Error("refresh failed");
        window.location.reload();
      }} catch (error) {{
        toast.style.display = "block";
        setTimeout(() => {{ toast.style.display = "none"; }}, 3500);
        btn.textContent = "Refresh";
        btn.disabled = false;
      }}
    }}

    const labels = {js_json(labels)};
    const equity = {js_json(total_equity)};
    const ltvValues = {js_json(ltv_values)};
    const feeYields = {js_json(fee_yields)};
    const aaveCarries = {js_json(aave_carries)};
    const cumulativeFeeYields = {js_json(cumulative_fee_yields)};
    const cumulativeAaveCarries = {js_json(cumulative_aave_carries)};
    const cumulativeNetOutputs = {js_json(cumulative_net_outputs)};
    const totalEthExposures = {js_json(total_eth_exposures)};
    const totalBtcExposures = {js_json(total_btc_exposures)};
    const showUnitChart = {js_json(show_unit_chart)};
    const liquidationEquityThreshold = {js_json(liquidation_equity_threshold)};

    const gridColor = "#262a33";
    const textColor = "#9ca3af";
    function formatUSD(value) {{
        if (value === null || value === undefined || isNaN(value)) return '';
        const abs = Math.abs(value);
        if (abs >= 1000000) return '$' + (value / 1000000).toFixed(1) + 'M';
        if (abs >= 1000) return '$' + (value / 1000).toFixed(1) + 'k';
        if (abs >= 1) return '$' + Math.round(value);
        return '$' + value.toFixed(2);
    }}

    const linePlugin = (id, yValue, color, label) => ({{
      id,
      afterDatasetsDraw(chart) {{
        const {{ctx, chartArea, scales}} = chart;
        if (!chartArea || !scales.y || yValue === null) return;
        const y = scales.y.getPixelForValue(yValue);
        ctx.save();
        ctx.strokeStyle = color;
        ctx.setLineDash([6, 6]);
        ctx.beginPath();
        ctx.moveTo(chartArea.left, y);
        ctx.lineTo(chartArea.right, y);
        ctx.stroke();
        if (label) {{
          ctx.setLineDash([]);
          ctx.fillStyle = color;
          ctx.font = "12px sans-serif";
          ctx.fillText(label, chartArea.left + 8, y - 6);
        }}
        ctx.restore();
      }}
    }});

    const commonOptions = {{
      responsive: true,
      maintainAspectRatio: false,
      plugins: {{ legend: {{ display: false }} }},
      scales: {{
        x: {{ ticks: {{ color: textColor }}, grid: {{ color: gridColor }} }},
        y: {{ ticks: {{ color: textColor }}, grid: {{ color: gridColor }} }}
      }}
    }};

    new Chart(document.getElementById("equityChart"), {{
      type: "line",
      data: {{ labels, datasets: [{{ data: equity, borderColor: "#a5b4fc", backgroundColor: "rgba(165, 180, 252, 0.15)", tension: 0.25, spanGaps: true }}] }},
      options: {{ ...commonOptions, scales: {{ ...commonOptions.scales, y: {{ ...commonOptions.scales.y, ticks: {{ color: textColor, callback: formatUSD }} }} }} }},
      plugins: [linePlugin("equityLiqThreshold", liquidationEquityThreshold, "#f87171", "Liq threshold")]
    }});

    new Chart(document.getElementById("ltvChart"), {{
      type: "bar",
      data: {{ labels, datasets: [{{ data: ltvValues, backgroundColor: "#fbbf24" }}] }},
      options: commonOptions,
      plugins: [linePlugin("ltvWarning", 80, "#f87171")]
    }});

    new Chart(document.getElementById("dailyYieldChart"), {{
      type: "bar",
      data: {{
        labels,
        datasets: [
          {{ label: "Daily Fee Yield", data: feeYields, backgroundColor: "#34d399", stack: "yield" }},
          {{ label: "AAVE Daily Carry", data: aaveCarries, backgroundColor: "#818cf8", stack: "yield" }}
        ]
      }},
      options: {{
        ...commonOptions,
        plugins: {{ legend: {{ display: true, labels: {{ color: textColor }} }} }},
        scales: {{
          x: {{ ...commonOptions.scales.x, stacked: true }},
          y: {{ ...commonOptions.scales.y, stacked: true, ticks: {{ color: textColor, callback: formatUSD }} }}
        }}
      }}
    }});

    new Chart(document.getElementById("cumulativeFarmOutputChart"), {{
      data: {{
        labels,
        datasets: [
          {{ type: "line", label: "Cumulative LP Fees", data: cumulativeFeeYields, borderColor: "#fbbf24", backgroundColor: "rgba(251, 191, 36, 0.15)", tension: 0.25, yAxisID: "y" }},
          {{ type: "line", label: "Cumulative AAVE Carry", data: cumulativeAaveCarries, borderColor: "#818cf8", backgroundColor: "rgba(129, 140, 248, 0.12)", tension: 0.25, yAxisID: "y" }},
          {{ type: "line", label: "Total Cumulative Net Output", data: cumulativeNetOutputs, borderColor: "#34d399", backgroundColor: "rgba(52, 211, 153, 0.12)", tension: 0.25, yAxisID: "y" }}
        ]
      }},
      options: {{
        responsive: true,
        maintainAspectRatio: false,
        plugins: {{ legend: {{ display: true, labels: {{ color: textColor }} }} }},
        scales: {{
          x: {{ ticks: {{ color: textColor }}, grid: {{ color: gridColor }} }},
          y: {{ ticks: {{ color: textColor, callback: formatUSD }}, grid: {{ color: gridColor }} }}
        }}
      }}
    }});

    if (showUnitChart) {{
      new Chart(document.getElementById("unitAccumulationChart"), {{
        type: "line",
        data: {{
          labels,
          datasets: [
            {{ label: "Total ETH Exposure", data: totalEthExposures, borderColor: "#34d399", backgroundColor: "rgba(52, 211, 153, 0.12)", tension: 0.25, spanGaps: true, yAxisID: "y" }},
            {{ label: "Total BTC Exposure", data: totalBtcExposures, borderColor: "#fbbf24", backgroundColor: "rgba(251, 191, 36, 0.12)", tension: 0.25, spanGaps: true, yAxisID: "y1" }}
          ]
        }},
        options: {{
          responsive: true,
          maintainAspectRatio: false,
          plugins: {{ legend: {{ display: true, labels: {{ color: textColor }} }} }},
          scales: {{
            x: {{ ticks: {{ color: textColor }}, grid: {{ color: gridColor }} }},
            y: {{ position: "left", ticks: {{ color: textColor }}, grid: {{ color: gridColor }} }},
            y1: {{ position: "right", ticks: {{ color: textColor }}, grid: {{ drawOnChartArea: false }} }}
          }}
        }}
      }});
    }}
  </script>
</body>
</html>
"""
    DASHBOARD_PATH.write_text(html, encoding="utf-8")


def fetch_all() -> tuple[dict[str, Any], int]:
    raw: dict[str, Any] = {}
    successes = 0

    fetches = [
        ("ETH price", "eth_price", lambda: fetch_price(ETH_USD_FEED)),
        ("BTC price", "btc_price", lambda: fetch_price(BTC_USD_FEED)),
        ("MAIN ETH balance", "eth_main", lambda: fetch_eth_balance(MAIN_WALLET)),
        ("LP ETH balance", "eth_lp", lambda: fetch_eth_balance(LP_WALLET)),
        ("aWETH balance", "aweth_balance", lambda: fetch_token_balance(AWETH, MAIN_WALLET, 18)),
        ("aWBTC balance", "awbtc_balance", lambda: fetch_token_balance(AWBTC, MAIN_WALLET, 8)),
        ("vdUSDT balance", "vdusdt_balance", lambda: fetch_token_balance(VDUSDT, MAIN_WALLET, 6)),
    ]

    aave_data, ok = safe_fetch("AAVE user data", lambda: fetch_aave_user_data(MAIN_WALLET))
    if ok:
        successes += 1
        raw.update(aave_data)
    else:
        raw.update({"aave_collateral": None, "aave_debt": None, "health_factor": None})

    weth_rates, ok = safe_fetch("AAVE WETH reserve rates", lambda: fetch_aave_reserve_rates(WETH))
    if ok:
        successes += 1
        raw["eth_supply_apy"] = weth_rates["supply_apy_pct"]
    else:
        raw["eth_supply_apy"] = None

    usdt_rates, ok = safe_fetch("AAVE USDT reserve rates", lambda: fetch_aave_reserve_rates(USDT))
    if ok:
        successes += 1
        raw["usdt_borrow_apy"] = usdt_rates["borrow_apy_pct"]
    else:
        raw["usdt_borrow_apy"] = None

    for label, key, fetcher in fetches:
        value, ok = safe_fetch(label, fetcher)
        raw[key] = value
        successes += 1 if ok else 0

    uni_data, ok = safe_fetch(
        "Uniswap V3 position details",
        lambda: fetch_uni_position_details(LP_WALLET, raw.get("eth_price")),
    )
    if ok:
        successes += 1
        raw.update(uni_data)
    else:
        raw.update(
            {
                "uni_positions": None,
                "uni_position_ids": None,
                "uni_position_value": None,
                "uni_fees_unclaimed": None,
                "uni_weth_fees": None,
                "uni_usdt_fees": None,
                "uni_weth_amount": None,
                "uni_usdt_amount": None,
                "uni_in_range": None,
                "uni_tick_lower": None,
                "uni_tick_upper": None,
                "uni_current_tick": None,
            }
        )

    return raw, successes


def run_data_fetch(gas_eth: float = 0.0) -> bool:
    print("Fetching on-chain data...")
    timestamp = datetime.now().astimezone().isoformat(timespec="seconds")

    try:
        raw, successes = fetch_all()
    except ValueError as exc:
        print(f"Error: {exc}")
        print("Replace MAIN_WALLET and LP_WALLET in tracker.py before first run.")
        return False

    if successes == 0:
        print("Error: all RPC calls failed. No database row written.")
        return False

    init_db()
    previous_rows = get_history(1)
    previous_fees_usd = previous_rows[-1].get("uni_fees_unclaimed") if previous_rows else None
    snapshot = compute_snapshot(raw, timestamp, previous_fees_usd, gas_eth)
    risk_label, _ = liquidation_status(snapshot.get("correlated_liq_drop_pct"))
    print(f"ETH price:        {money(snapshot.get('eth_price'))}")
    print(f"BTC price:        {money(snapshot.get('btc_price'))}")
    print(f"Health Factor:    {number(snapshot.get('health_factor'), 2)}")
    print("Liquidation risk:")
    print(f"  Market drop to liq:  {signed_drop(snapshot.get('correlated_liq_drop_pct'))}")
    print(f"  ETH at liq:          {whole_money(snapshot.get('correlated_liq_price_eth'))}")
    print(f"  BTC at liq:          {whole_money(snapshot.get('correlated_liq_price_btc'))}")
    print(f"  Status:              {risk_label}")
    print("AAVE Rates:")
    print(f"  WETH supply APY:   {percent(snapshot.get('eth_supply_apy'), 2)}")
    print(f"  USDT borrow APY:   {percent(snapshot.get('usdt_borrow_apy'), 2)}")
    print(f"  Daily carry:       {money(snapshot.get('aave_daily_carry'))}")
    print("Yield today:")
    print(f"  LP fee yield:      {money(snapshot.get('uni_daily_fee_yield'))}")
    print(f"  AAVE carry:        {money(snapshot.get('aave_daily_carry'))}")
    print(f"  Total:             {money(snapshot.get('total_daily_yield'))}")
    print(f"  Gas drag:          {percent(snapshot.get('gas_drag_pct'), 1)}")
    uni_status_text, _, _ = uni_status(snapshot)
    print("Uniswap LP:")
    print(f"  Token ID:       {format_uni_ids(snapshot.get('uni_position_ids'))}")
    print(f"  Status:         {uni_status_text}")
    print(f"  WETH:           {number(snapshot.get('uni_weth_amount'), 4)} ETH")
    print(f"  USDT:           {number(snapshot.get('uni_usdt_amount'), 2)} USDT")
    print(f"  Position value: {money(snapshot.get('uni_position_value'))}")
    weth_fee_usd = (
        snapshot["uni_weth_fees"] * snapshot["eth_price"]
        if snapshot.get("uni_weth_fees") is not None and snapshot.get("eth_price") is not None
        else None
    )
    print("Unclaimed fees:")
    print(f"  USDT fees:  {number(snapshot.get('uni_usdt_fees'), 2)} USDT  ({money(snapshot.get('uni_usdt_fees'))})")
    print(f"  WETH fees:  {number(snapshot.get('uni_weth_fees'), 6)} WETH  ({money(weth_fee_usd)})")
    print(f"  Total:      {money(snapshot.get('uni_fees_unclaimed'))}")

    insert_snapshot(snapshot)
    history = get_history(30)
    generate_dashboard(snapshot, history)

    print("Dashboard generated: dashboard.html")
    return True


class RefreshHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/refresh":
            ok = run_data_fetch()
            self.send_response(200 if ok else 500)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"OK" if ok else b"ERROR")
        elif self.path in ("/", "/dashboard"):
            content = DASHBOARD_PATH.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(content)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        pass


def start_server() -> tuple[socketserver.TCPServer, int]:
    socketserver.TCPServer.allow_reuse_address = True
    last_error = None
    for port in SERVER_PORTS:
        try:
            return socketserver.TCPServer((SERVER_HOST, port), RefreshHandler), port
        except OSError as exc:
            last_error = exc
    raise OSError(f"could not bind localhost ports {SERVER_PORTS}: {last_error}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gas", type=float, default=0.0, help="ETH spent on gas since last run")
    args = parser.parse_args()

    if not run_data_fetch(args.gas):
        return 1

    try:
        server, port = start_server()
    except OSError as exc:
        print(f"Error: {exc}")
        return 1

    url = f"http://{SERVER_HOST}:{port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"Serving dashboard: {url}")
    webbrowser.open(url)

    try:
        while True:
            thread.join(1)
    except KeyboardInterrupt:
        print("\nStopping dashboard server.")
        server.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
