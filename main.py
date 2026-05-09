import os
import time
import json
import asyncio
import aiohttp
import aiofiles
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ─── Config ───────────────────────────────────────────────────────────────────

LOG_FILE = Path(os.getenv("LOG_FILE", "log.txt"))
FETCH_DELAY = int(os.getenv("FETCH_DELAY", "5"))  # seconds between posts
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "30"))

# Discord
DISCORD_ENABLED = os.getenv("DISCORD_ENABLED", "false").lower() == "true"
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
DISCORD_ROLE_ID = os.getenv("DISCORD_ROLE_ID", "")

# ─── GraphQL Query ─────────────────────────────────────────────────────────────

HACKERONE_URL = "https://hackerone.com/graphql"

GRAPHQL_QUERY = """
query HacktivitySearchQuery($queryString: String!, $from: Int, $size: Int, $sort: SortInput!) {
  me { id __typename }
  search(
    index: CompleteHacktivityReportIndex
    query_string: $queryString
    from: $from
    size: $size
    sort: $sort
  ) {
    __typename
    total_count
    nodes {
      __typename
      ... on HacktivityDocument {
        id
        _id
        reporter { id username name __typename }
        cve_ids
        cwe
        severity_rating
        upvoted: upvoted_by_current_user
        public
        report {
          id
          databaseId: _id
          title
          substate
          url
          disclosed_at
          report_generated_content {
            id
            hacktivity_summary
            __typename
          }
          __typename
        }
        votes
        team {
          id handle name
          medium_profile_picture: profile_picture(size: medium)
          url currency __typename
        }
        total_awarded_amount
        latest_disclosable_action
        latest_disclosable_activity_at
        submitted_at
        disclosed
        has_collaboration
        __typename
      }
    }
  }
}
"""

# ─── Helpers ───────────────────────────────────────────────────────────────────

SEVERITY_COLORS = {
    "None": 0xE7E7E8,
    "Low": 0x78BB59,
    "Medium": 0xFDD835,
    "High": 0xF48A3C,
    "Critical": 0xDD4B39,
}

SEVERITY_ICONS = {
    "None": "⚪ Info",
    "Low": "🟢 Low",
    "Medium": "🟡 Medium",
    "High": "🟠 High",
    "Critical": "🔴 Critical",
}

SEVERITY_EMOJI = {
    "None": "⚪",
    "Low": "🟢",
    "Medium": "🟡",
    "High": "🟠",
    "Critical": "🔴",
}


def get_severity_label(severity: str) -> str:
    return "Info" if severity == "None" else severity


def format_bounty(amount: float, currency: str) -> str:
    try:
        formatted = f"{amount:,.2f}"
        symbols = {"USD": "$", "EUR": "€", "GBP": "£"}
        symbol = symbols.get(currency, currency + " ")
        return f"💰 {symbol}{formatted}"
    except Exception:
        return f"💰 {amount} {currency}"


def get_summary(report_generated_content) -> str:
    if not report_generated_content:
        return ""
    return report_generated_content.get("hacktivity_summary", "")


# ─── Log File ──────────────────────────────────────────────────────────────────


async def load_log() -> set[str]:
    if not LOG_FILE.exists():
        LOG_FILE.touch()
        return set()
    async with aiofiles.open(LOG_FILE, "r") as f:
        content = await f.read()
    return set(line.strip() for line in content.splitlines() if line.strip())


async def save_id(report_id: str) -> None:
    async with aiofiles.open(LOG_FILE, "a") as f:
        await f.write(f"{report_id}\n")


# ─── HackerOne Fetch ───────────────────────────────────────────────────────────


async def fetch_hacktivity(session: aiohttp.ClientSession) -> list[dict]:
    payload = {
        "operationName": "HacktivitySearchQuery",
        "variables": {"queryString": "disclosed:true", "size": 25, "from": 0, "sort": {"field": "latest_disclosable_activity_at", "direction": "DESC"}},
        "query": GRAPHQL_QUERY,
    }

    headers = {
        "accept": "*/*",
        "cache-control": "no-cache",
        "content-type": "application/json",
        "pragma": "no-cache",
        "x-product-area": "hacktivity",
        "x-product-feature": "overview",
        "Referer": "https://hackerone.com/hacktivity/overview",
        "Referrer-Policy": "origin-when-cross-origin",
    }

    async with session.post(HACKERONE_URL, json=payload, headers=headers) as resp:
        resp.raise_for_status()
        data = await resp.json()

    return data["data"]["search"]["nodes"]


# ─── Discord ───────────────────────────────────────────────────────────────────


def build_discord_payload(node: dict) -> dict:
    report = node["report"]
    generated = report.get("report_generated_content")
    team = node["team"]
    severity = node.get("severity_rating", "")
    reporter = node["reporter"]["username"]

    summary = get_summary(generated)
    description = f"📝 Disclosed by [**@{reporter}**](https://hackerone.com/{reporter}) " f"to [**{team['name']}**](https://hackerone.com/{team['handle']})"
    if summary:
        description += f"\n\n{summary}"

    color = SEVERITY_COLORS.get(severity, 0xAAAAAA)

    payload = {
        "content": f"<@&{DISCORD_ROLE_ID}>" if DISCORD_ROLE_ID else None,
        "embeds": [
            {
                "title": report["title"],
                "description": description,
                "url": report["url"],
                "color": color,
                "fields": [
                    {"name": "Severity", "value": SEVERITY_ICONS.get(severity, "— "), "inline": True},
                    {"name": "Bounty", "value": format_bounty(node.get("total_awarded_amount", 0), team.get("currency", "USD")), "inline": True},
                ],
            }
        ],
        "attachments": [],
    }

    return payload


async def send_discord(session: aiohttp.ClientSession, node: dict) -> bool:
    if not DISCORD_ENABLED or not DISCORD_WEBHOOK_URL:
        return True  # silently skip if disabled

    payload = build_discord_payload(node)
    async with session.post(DISCORD_WEBHOOK_URL, json=payload, headers={"Content-Type": "application/json"}) as resp:
        if resp.status in (200, 204):
            return True
        text = await resp.text()
        print(f"  [Discord] ❌ HTTP {resp.status}: {text}")
        return False


# ─── Main ──────────────────────────────────────────────────────────────────────


POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "300"))


async def main():
    print("─" * 50)
    print(f"  Discord  : {'✅ enabled' if DISCORD_ENABLED else '❌ disabled'}")
    print(f"  Interval : {POLL_INTERVAL}s")
    print("─" * 50)

    if not DISCORD_ENABLED:
        print("⚠️  No platform enabled! Set DISCORD_ENABLED=true in .env")
        return

    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)

    while True:
        try:
            seen_ids = await load_log()
            print(f"\n🔄 Checking... ({len(seen_ids)} already sent)")

            async with aiohttp.ClientSession(timeout=timeout) as session:
                nodes = await fetch_hacktivity(session)
                print(f"📦 Got {len(nodes)} reports")

                new_count = 0
                for node in nodes:
                    report_id = node["report"]["databaseId"]
                    title = node["report"]["title"]

                    if report_id in seen_ids:
                        continue

                    print(f"  📨 [{report_id}] {title[:60]}...")
                    discord_ok = await send_discord(session, node)

                    if discord_ok:
                        print(f"     ✅ Discord sent")
                        await save_id(report_id)
                        seen_ids.add(report_id)
                        new_count += 1
                        await asyncio.sleep(FETCH_DELAY)

                print(f"✅ Done — {new_count} new report(s) sent")

        except Exception as e:
            print(f"❌ Error: {e}")

        print(f"⏳ Sleeping {POLL_INTERVAL}s...\n")
        await asyncio.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
