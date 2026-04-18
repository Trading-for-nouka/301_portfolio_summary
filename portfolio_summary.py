import pandas as pd
import os
import json
import requests
import yfinance as yf
from datetime import datetime, timedelta, timezone

PAT_TOKEN        = os.environ.get("PAT_TOKEN")
DISCORD_WEBHOOK  = os.environ.get("DISCORD_WEBHOOK")

# 各戦略のリポジトリと表示ラベル
STRATEGY_REPOS = {
    "breakout": "trading-for-nouka/201_breakout",
    "dip":      "trading-for-nouka/202_dip",
    "nr4":      "trading-for-nouka/203_nr4",
    "rebound":  "trading-for-nouka/204_rebound",
}

STRATEGY_LABELS = {
    "breakout": "🚀 ブレイクアウト",
    "dip":      "📉 押し目",
    "nr4":      "📦 NR4",
    "rebound":  "🔄 リバウンド",
}


def fetch_positions(repo: str) -> list:
    """PAT_TOKEN経由で各戦略リポジトリの positions.json を取得"""
    url = f"https://api.github.com/repos/{repo}/contents/positions.json"
    headers = {
        "Authorization": f"token {PAT_TOKEN}",
        "Accept": "application/vnd.github.v3.raw"
    }
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            return data if isinstance(data, list) else []
        elif resp.status_code == 404:
            print(f"  {repo}: positions.json なし")
            return []
        else:
            print(f"  {repo}: HTTP {resp.status_code}")
            return []
    except Exception as e:
        print(f"  取得失敗 {repo}: {e}")
        return []


def get_current_price(ticker: str) -> float | None:
    """yfinanceで現在値を取得"""
    try:
        df = yf.download(ticker, period="5d", progress=False)
        if df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return float(df["Close"].iloc[-1])
    except:
        return None


def main():
    jst = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=9)))
    today_str = jst.strftime("%Y-%m-%d")

    print(f"📊 ポートフォリオサマリー開始: {today_str}")

    # 全戦略のポジションを取得
    all_positions: dict[str, list] = {}
    total_count = 0

    for strategy, repo in STRATEGY_REPOS.items():
        positions = fetch_positions(repo)
        for p in positions:
            p.setdefault("strategy", strategy)  # strategyフィールドない場合は補完
        all_positions[strategy] = positions
        total_count += len(positions)
        print(f"  {strategy}: {len(positions)}件")

    if total_count == 0:
        msg = (
            f"📊 **週刊ポートフォリオサマリー — {today_str}**\n"
            f"保有ポジションなし\n"
            f"🕒 {jst.strftime('%Y/%m/%d %H:%M')} JST"
        )
        if DISCORD_WEBHOOK:
            requests.post(DISCORD_WEBHOOK, json={"content": msg})
        print(msg)
        return

    # 現在値取得・損益計算
    msg_sections = []
    total_profit_sum = 0.0
    total_pos_count  = 0

    for strategy, positions in all_positions.items():
        label = STRATEGY_LABELS.get(strategy, strategy)

        if not positions:
            msg_sections.append(f"{label} （0件）")
            continue

        lines = []
        for p in positions:
            try:
                ticker      = p["ticker"]
                name        = p.get("name", ticker)
                entry_price = float(p["entry_price"])
            except (KeyError, ValueError) as e:
                print(f"  スキップ（不正データ）: {e}")
                continue
            entry_date  = p.get("entry_date", "")

            current_price = get_current_price(ticker)
            if current_price is None:
                lines.append(f"　❓ {name}（{ticker}）— データ取得失敗")
                continue

            profit_pct = (current_price - entry_price) / entry_price * 100

            try:
                entry_dt  = datetime.strptime(entry_date, "%Y-%m-%d")
                days_held = (datetime.now() - entry_dt).days
            except:
                days_held = 0

            icon = "🚀" if profit_pct > 5 else "✅" if profit_pct > 0 else "⚠️"
            lines.append(
                f"　{icon} {name}（{ticker}）  {profit_pct:+.1f}%  /  {days_held}日目"
            )
            total_profit_sum += profit_pct
            total_pos_count  += 1

        msg_sections.append(
            f"**{label} ({len(positions)}件)**\n" + "\n".join(lines)
        )

    avg_profit = total_profit_sum / total_pos_count if total_pos_count > 0 else 0.0
    profit_icon = "💰" if avg_profit >= 0 else "📉"

    msg  = f"📊 **週刊ポートフォリオサマリー — {today_str}**\n"
    msg += "━" * 20 + "\n"
    msg += "\n\n".join(msg_sections)
    msg += "\n" + "━" * 20 + "\n"
    msg += f"{profit_icon} **全体平均損益: {avg_profit:+.1f}%**（{total_pos_count}件保有）\n"
    msg += f"🕒 {jst.strftime('%Y/%m/%d %H:%M')} JST"

    if DISCORD_WEBHOOK:
        requests.post(DISCORD_WEBHOOK, json={"content": msg})
    print(msg)


if __name__ == "__main__":
    main()
