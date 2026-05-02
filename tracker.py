from __future__ import annotations

import json
import sys
import webbrowser
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

import requests

from db import get_history, init_db, insert_snapshot


# --- USER CONFIGURATION ---
MAIN_WALLET = "0x0C4bE1AC7edf172E0F617548F2a3e76561DEbc2E"  # AAVE collateral & debt
LP_WALLET = "x0C4bE1AC7edf172E0F617548F2a3e76561DEbc2E"  # Uniswap V3 LP positions
RPC_URL = "https://ethereum-rpc.publicnode.com"
# --------------------------


AAVE_POOL = "0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2"
AWETH = "0x4d5F47FA6A74757f35C14fD3a6Ef8E3C9BC514E8"
VDUSDT = "0x531842cebfcce26401911cb6d3b170f8b2fc57c6"
UNI_V3_NFT_MANAGER = "0xC36442b4a4522E871399CD717aBDD847Ab11FE88"
ETH_USD_FEED = "0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419"
BTC_USD_FEED = "0xF4030086522a5bEEa4988F8cA5B36dbC97BeE88c"

LATEST_ROUND_DATA_SELECTOR = "0xfeaf968c"
BALANCE_OF_SELECTOR = "0x70a08231"
AAVE_USER_DATA_SELECTOR = "0xbf92857c"

BASE_DIR = Path(__file__).resolve().parent
DASHBOARD_PATH = BASE_DIR / "dashboard.html"
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


def eth_call(to_address: str, data: str) -> str:
    return rpc_request("eth_call", [{"to": to_address, "data": data}, "latest"])


def decode_uint_words(result: str) -> list[int]:
    hex_data = result[2:] if result.startswith("0x") else result
    if not hex_data:
        return []
    return [int(hex_data[index : index + 64], 16) for index in range(0, len(hex_data), 64)]


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


def fetch_token_balance(token_address: str, wallet: str, decimals: int) -> float:
    result = eth_call(token_address, BALANCE_OF_SELECTOR + pad_address(wallet))
    return hex_to_int(result) / (10**decimals)


def fetch_uni_position_count(wallet: str) -> int:
    result = eth_call(UNI_V3_NFT_MANAGER, BALANCE_OF_SELECTOR + pad_address(wallet))
    return hex_to_int(result)


def money(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"${value:,.2f}"


def number(value: float | int | None, digits: int = 2) -> str:
    if value is None:
        return "N/A"
    return f"{value:,.{digits}f}"


def truncated(address: str) -> str:
    if not isinstance(address, str) or len(address) < 12:
        return address
    return f"{address[:8]}...{address[-4:]}"


def js_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True).replace("</", "<\\/")


def compute_snapshot(raw: dict[str, Any], timestamp: str) -> dict[str, Any]:
    collateral = raw.get("aave_collateral")
    debt = raw.get("aave_debt")
    eth_main = raw.get("eth_main")
    eth_lp = raw.get("eth_lp")
    eth_price = raw.get("eth_price")

    aave_equity = collateral - debt if collateral is not None and debt is not None else None
    ltv_pct = (debt / collateral) * 100 if collateral and debt is not None else None
    eth_equity = (eth_main + eth_lp) * eth_price if None not in (eth_main, eth_lp, eth_price) else None
    total_equity = aave_equity + eth_equity if aave_equity is not None and eth_equity is not None else None

    return {
        "timestamp": timestamp,
        "eth_price": eth_price,
        "btc_price": raw.get("btc_price"),
        "eth_main": eth_main,
        "eth_lp": eth_lp,
        "aave_collateral": collateral,
        "aave_debt": debt,
        "aave_equity": aave_equity,
        "health_factor": raw.get("health_factor"),
        "ltv_pct": ltv_pct,
        "aweth_balance": raw.get("aweth_balance"),
        "vdusdt_balance": raw.get("vdusdt_balance"),
        "uni_positions": raw.get("uni_positions"),
        "total_equity": total_equity,
        "notes": raw.get("notes"),
    }


def health_class(health_factor: float | None) -> str:
    if health_factor is None:
        return "muted"
    if health_factor >= 1.5:
        return "green"
    if health_factor >= 1.2:
        return "amber"
    return "red"


def generate_dashboard(snapshot: dict[str, Any], history: list[dict[str, Any]]) -> None:
    labels = [row["timestamp"][:10] for row in history]
    total_equity = [row.get("total_equity") for row in history]
    health_factors = [row.get("health_factor") for row in history]
    ltv_values = [row.get("ltv_pct") for row in history]
    health_colors = [
        "#34d399" if value is not None and value >= 1.5 else "#fbbf24" if value is not None and value >= 1.2 else "#f87171"
        for value in health_factors
    ]

    hf = snapshot.get("health_factor")
    banner_class = health_class(hf)
    eth_total = (
        snapshot["eth_main"] + snapshot["eth_lp"]
        if snapshot.get("eth_main") is not None and snapshot.get("eth_lp") is not None
        else None
    )
    eth_value = eth_total * snapshot["eth_price"] if eth_total is not None and snapshot.get("eth_price") is not None else None
    uni_positions = snapshot.get("uni_positions")
    uni_text = f"{uni_positions} active positions" if uni_positions else "No positions found"
    uni_class = "green" if uni_positions else "muted"

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
    header {{ margin-bottom: 24px; }}
    h1 {{ margin: 0 0 6px; font-size: 32px; font-weight: 750; }}
    h2 {{ margin: 0 0 14px; font-size: 18px; }}
    .subtitle, .muted {{ color: var(--muted); }}
    .card {{
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 18px;
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
    .label {{ color: var(--muted); font-size: 13px; }}
    .value {{ margin-top: 4px; font-size: 24px; font-weight: 720; }}
    .grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; margin-bottom: 20px; }}
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
    .amber {{ color: var(--amber); }}
    .indigo {{ color: var(--indigo); }}
    footer {{ margin-top: 24px; color: var(--muted); font-size: 13px; text-align: center; }}
    @media (max-width: 820px) {{
      main {{ width: min(100% - 20px, 1180px); padding: 20px 0; }}
      .grid, .banner, .two-col {{ grid-template-columns: 1fr; }}
      h1 {{ font-size: 26px; }}
      .chart-wrap {{ height: 280px; }}
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <h1>DeFi Portfolio Tracker</h1>
      <div class="subtitle">{escape(snapshot["timestamp"])} | MAIN {escape(truncated(MAIN_WALLET))} | LP {escape(truncated(LP_WALLET))}</div>
    </header>

    <section class="card banner {banner_class}">
      <div><div class="label">Health Factor</div><div class="value">{number(hf, 3)}</div></div>
      <div><div class="label">Equity</div><div class="value">{money(snapshot.get("total_equity"))}</div></div>
      <div><div class="label">LTV</div><div class="value">{number(snapshot.get("ltv_pct"))}%</div></div>
    </section>

    <section class="grid">
      <div class="card kpi"><div class="label">Total Equity</div><div class="value">{money(snapshot.get("total_equity"))}</div></div>
      <div class="card kpi"><div class="label">ETH Price</div><div class="value">{money(snapshot.get("eth_price"))}</div></div>
      <div class="card kpi"><div class="label">BTC Price</div><div class="value">{money(snapshot.get("btc_price"))}</div></div>
      <div class="card kpi"><div class="label">Health Factor</div><div class="value">{number(hf, 3)}</div></div>
      <div class="card kpi"><div class="label">AAVE Collateral</div><div class="value">{money(snapshot.get("aave_collateral"))}</div></div>
      <div class="card kpi"><div class="label">AAVE Debt</div><div class="value">{money(snapshot.get("aave_debt"))}</div></div>
      <div class="card kpi"><div class="label">aWETH Balance</div><div class="value">{number(snapshot.get("aweth_balance"), 6)}</div></div>
      <div class="card kpi"><div class="label">vdUSDT Balance</div><div class="value">{number(snapshot.get("vdusdt_balance"), 2)}</div></div>
    </section>

    <section class="charts">
      <div class="card"><h2>30-day Total Equity trend</h2><div class="chart-wrap"><canvas id="equityChart"></canvas></div></div>
      <div class="card"><h2>AAVE Health Factor over time</h2><div class="chart-wrap"><canvas id="hfChart"></canvas></div></div>
      <div class="card"><h2>LTV% over time</h2><div class="chart-wrap"><canvas id="ltvChart"></canvas></div></div>
    </section>

    <section class="two-col">
      <div class="card">
        <h2>Position table</h2>
        <table>
          <thead><tr><th>Position</th><th>Metric 1</th><th>Metric 2</th><th>Metric 3</th><th>Metric 4</th></tr></thead>
          <tbody>
            <tr><td>AAVE</td><td>{money(snapshot.get("aave_collateral"))} collateral</td><td>{money(snapshot.get("aave_debt"))} debt</td><td>{money(snapshot.get("aave_equity"))} equity</td><td>HF {number(hf, 3)} | LTV {number(snapshot.get("ltv_pct"))}%</td></tr>
            <tr><td>ETH Balances</td><td>{number(snapshot.get("eth_main"), 6)} main</td><td>{number(snapshot.get("eth_lp"), 6)} LP</td><td>{number(eth_total, 6)} total ETH</td><td>{money(eth_value)}</td></tr>
          </tbody>
        </table>
      </div>
      <div class="card">
        <h2>Uniswap status</h2>
        <div class="value {uni_class}">{escape(uni_text)}</div>
      </div>
    </section>

    <footer>Generated: {escape(snapshot["timestamp"])} | Data: ethereum-rpc.publicnode.com | All data is read-only on-chain</footer>
  </main>

  <script>
    const labels = {js_json(labels)};
    const equity = {js_json(total_equity)};
    const healthFactors = {js_json(health_factors)};
    const healthColors = {js_json(health_colors)};
    const ltvValues = {js_json(ltv_values)};

    const gridColor = "#262a33";
    const textColor = "#9ca3af";
    const moneyTick = value => {{
      if (value === null || Number.isNaN(value)) return "";
      return "$" + (value / 1000).toFixed(0) + "k";
    }};

    const linePlugin = (id, yValue, color) => ({{
      id,
      afterDatasetsDraw(chart) {{
        const {{ctx, chartArea, scales}} = chart;
        if (!chartArea || !scales.y) return;
        const y = scales.y.getPixelForValue(yValue);
        ctx.save();
        ctx.strokeStyle = color;
        ctx.setLineDash([6, 6]);
        ctx.beginPath();
        ctx.moveTo(chartArea.left, y);
        ctx.lineTo(chartArea.right, y);
        ctx.stroke();
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
      options: {{ ...commonOptions, scales: {{ ...commonOptions.scales, y: {{ ...commonOptions.scales.y, ticks: {{ color: textColor, callback: moneyTick }} }} }} }}
    }});

    new Chart(document.getElementById("hfChart"), {{
      type: "line",
      data: {{ labels, datasets: [{{ data: healthFactors, borderColor: "#34d399", pointBackgroundColor: healthColors, segment: {{ borderColor: ctx => healthColors[ctx.p1DataIndex] || "#34d399" }}, tension: 0.25, spanGaps: true }}] }},
      options: commonOptions,
      plugins: [linePlugin("hfWarning", 1.2, "#f87171")]
    }});

    new Chart(document.getElementById("ltvChart"), {{
      type: "bar",
      data: {{ labels, datasets: [{{ data: ltvValues, backgroundColor: "#fbbf24" }}] }},
      options: commonOptions,
      plugins: [linePlugin("ltvWarning", 80, "#f87171")]
    }});
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
        ("vdUSDT balance", "vdusdt_balance", lambda: fetch_token_balance(VDUSDT, MAIN_WALLET, 6)),
        ("Uniswap V3 position count", "uni_positions", lambda: fetch_uni_position_count(LP_WALLET)),
    ]

    aave_data, ok = safe_fetch("AAVE user data", lambda: fetch_aave_user_data(MAIN_WALLET))
    if ok:
        successes += 1
        raw.update(aave_data)
    else:
        raw.update({"aave_collateral": None, "aave_debt": None, "health_factor": None})

    for label, key, fetcher in fetches:
        value, ok = safe_fetch(label, fetcher)
        raw[key] = value
        successes += 1 if ok else 0

    return raw, successes


def main() -> int:
    print("Fetching on-chain data...")
    timestamp = datetime.now().astimezone().isoformat(timespec="seconds")

    try:
        raw, successes = fetch_all()
    except ValueError as exc:
        print(f"Error: {exc}")
        print("Replace MAIN_WALLET and LP_WALLET in tracker.py before first run.")
        return 1

    if successes == 0:
        print("Error: all RPC calls failed. No database row written.")
        return 1

    snapshot = compute_snapshot(raw, timestamp)
    print(
        "Summary: "
        f"ETH price {money(snapshot.get('eth_price'))}, "
        f"HF {number(snapshot.get('health_factor'), 3)}, "
        f"equity {money(snapshot.get('total_equity'))}"
    )

    init_db()
    insert_snapshot(snapshot)
    history = get_history(30)
    generate_dashboard(snapshot, history)

    print("Dashboard generated: dashboard.html")
    webbrowser.open(DASHBOARD_PATH.resolve().as_uri())
    return 0


if __name__ == "__main__":
    sys.exit(main())
