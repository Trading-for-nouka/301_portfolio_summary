import json, os, base64, requests
from datetime import datetime, timezone, timedelta

DISCORD_BOT_TOKEN  = os.environ["DISCORD_BOT_TOKEN"]
DISCORD_CHANNEL_ID = os.environ["DISCORD_CHANNEL_ID"]
PAT_TOKEN          = os.environ["PAT_TOKEN"]
PROCESSED_FILE     = "processed_ids.json"
REACTION_EMOJI     = "\U0001f6d2"  # 🛒

STRATEGY_REPOS = {
    "breakout": "trading-for-nouka/201_breakout",
    "dip":      "trading-for-nouka/202_dip",
    "nr4":      "trading-for-nouka/203_nr4",
    "rebound":  "trading-for-nouka/204_rebound",
    "rs":       "trading-for-nouka/211_rs",
}

DH = {"Authorization": f"Bot {DISCORD_BOT_TOKEN}"}
GH = {"Authorization": f"token {PAT_TOKEN}", "Accept": "application/vnd.github.v3+json"}


def load_processed():
    if os.path.exists(PROCESSED_FILE):
        with open(PROCESSED_FILE) as f:
            return set(json.load(f))
    return set()


def save_processed(ids):
    # Discord snowflake IDs are sortable by time; keep newest 300
    sorted_ids = sorted(ids, reverse=True)[:300]
    with open(PROCESSED_FILE, "w") as f:
        json.dump(sorted_ids, f)


def get_messages():
    url = f"https://discord.com/api/v10/channels/{DISCORD_CHANNEL_ID}/messages?limit=50"
    r = requests.get(url, headers=DH, timeout=10)
    print(f"Messages API status: {r.status_code}")
    print(f"Messages API response: {r.text[:300]}")
    return r.json() if r.status_code == 200 else []


def has_reaction(message_id):
    encoded = requests.utils.quote(REACTION_EMOJI)
    url = f"https://discord.com/api/v10/channels/{DISCORD_CHANNEL_ID}/messages/{message_id}/reactions/{encoded}"
    r = requests.get(url, headers=DH, timeout=10)
    return r.status_code == 200 and len(r.json()) > 0


def parse_data_line(content):
    """\U0001f4ce ticker|strategy|entry_price|stop_loss|name \u3092\u89e3\u6790"""
    for line in content.split("\n"):
        line = line.strip()
        if line.startswith("\U0001f4ce "):
            parts = line[2:].strip().split("|")
            if len(parts) >= 5:
                return {
                    "ticker":      parts[0].strip(),
                    "strategy":    parts[1].strip(),
                    "entry_price": float(parts[2].strip()),
                    "stop_loss":   float(parts[3].strip()),
                    "name":        "|".join(parts[4:]).strip(),
                }
    return None


def get_github_positions(repo):
    url = f"https://api.github.com/repos/{repo}/contents/positions.json"
    r = requests.get(url, headers=GH, timeout=10)
    if r.status_code == 200:
        d = r.json()
        content = json.loads(base64.b64decode(d["content"]).decode())
        return content, d["sha"]
    return [], None


def put_github_positions(repo, positions, sha, commit_msg):
    url = f"https://api.github.com/repos/{repo}/contents/positions.json"
    encoded = base64.b64encode(
        json.dumps(positions, ensure_ascii=False, indent=2).encode()
    ).decode()
    payload = {"message": commit_msg, "content": encoded}
    if sha:
        payload["sha"] = sha
    r = requests.put(url, headers=GH, json=payload, timeout=10)
    return r.status_code in (200, 201)

def send_discord_message(content):
    url = f"https://discord.com/api/v10/channels/{DISCORD_CHANNEL_ID}/messages"
    requests.post(url, headers=DH, json={"content": content}, timeout=10)

def main():
    
    # ↓ デバッグ用（確認後削除）
    messages = get_messages()
    print(f"取得メッセージ数: {len(messages)}")
    for msg in messages:
        content = msg.get("content", "")
        if "📎" in content or "🛒" in content:
            mid = msg["id"]
            print(f"\n--- メッセージID: {mid} ---")
            print(f"内容: {content[:100]}")
            # リアクション確認
            encoded = requests.utils.quote("\U0001f6d2")
            url = f"<https://discord.com/api/v10/channels/{DISCORD_CHANNEL_ID}/messages/{mid}/reactions/{encoded}>"
            r = requests.get(url, headers=DH, timeout=10)
            print(f"リアクションAPI status: {r.status_code}")
            print(f"リアクション内容: {r.text[:200]}")
    return
    # ↑ ここまでデバッグ用
    
    processed = load_processed()
    messages  = get_messages()
    new_ids   = set(processed)
    added     = 0

    for msg in messages:
        mid     = msg["id"]
        content = msg.get("content", "")

        if "\U0001f4ce" not in content:
            new_ids.add(mid)
            continue

        if mid in processed:
            continue

        if not has_reaction(mid):
            continue

        data = parse_data_line(content)
        if not data:
            print(f"  \u26a0\ufe0f \u30d1\u30fc\u30b9\u5931\u6557: {mid}")
            new_ids.add(mid)
            continue

        repo = STRATEGY_REPOS.get(data["strategy"])
        if not repo:
            print(f"  \u26a0\ufe0f \u4e0d\u660e\u306a\u6226\u7565: {data['strategy']}")
            new_ids.add(mid)
            continue

        positions, sha = get_github_positions(repo)
        existing = {p["ticker"] for p in positions}

        if data["ticker"] in existing:
            print(f"  \u26a0\ufe0f \u767b\u9332\u6e08\u307f: {data['ticker']}")
            new_ids.add(mid)
            continue

        jst = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=9)))
        new_pos = {
            "ticker":        data["ticker"],
            "name":          data["name"],
            "entry_date":    jst.strftime("%Y-%m-%d"),
            "entry_price":   data["entry_price"],
            "highest_price": data["entry_price"],
            "stop_loss":     data["stop_loss"],
            "strategy":      data["strategy"],
        }
        positions.append(new_pos)

        ok = put_github_positions(
            repo, positions, sha,
            f"Add position: {data['ticker']} [{data['strategy']}]"
        )
        if ok:
            print(f"  ✅ 追加: {data['ticker']} → {repo}")
            added += 1
            send_discord_message(
                f"✅ **{data['name']}（{data['ticker']}）** を {data['strategy']} に記録しました\n"
                f"　 📌 エントリー: {data['entry_price']}円 | 🛑 損切: {data['stop_loss']}円"
            )
        else:
            print(f"  \u274c \u66f8\u304d\u8fbc\u307f\u5931\u6557: {data['ticker']}")

        new_ids.add(mid)

    save_processed(new_ids)
    print(f"\n\u5b8c\u4e86: {added}\u4ef6\u8ffd\u52a0")


if __name__ == "__main__":
    main()
