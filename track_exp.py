#!/usr/bin/env python3
"""
Tibia Experience Tracker
Tracks player experience from TibiaData API and sends Discord notifications on changes.
Two lists are tracked: alerts (one message per character to WEBHOOK) and trolls
(one summary message per run to WEBHOOK_TROLL).
"""

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from typing import Dict, List, Optional
from pathlib import Path


# Configuration
CONFIG_BASE_URL = "https://raw.githubusercontent.com/Ruslex1234/tibia-ops-config/refs/heads/main/.configs"
ALERTS_URL = f"{CONFIG_BASE_URL}/alerts.json"
TROLLS_URL = f"{CONFIG_BASE_URL}/trolls.json"
TIBIADATA_API_BASE = "https://api.tibiadata.com/v4"
EXP_JSON_PATH = "exp.json"
TROLLS_EXP_JSON_PATH = "trolls_exp.json"
DISCORD_WEBHOOK_URL = os.environ.get("WEBHOOK", "")
TROLL_WEBHOOK_URL = os.environ.get("WEBHOOK_TROLL", "")
HEADERS = {
    'User-Agent': 'TibiaExpTracker/1.0 (GitHub Actions Bot)',
    'Accept': 'application/json'
}


def http_json(url: str, payload: Optional[Dict] = None, timeout: int = 10):
    """GET (or POST when payload is given) using only the standard library.

    Raises urllib.error.HTTPError on non-2xx responses, like raise_for_status().
    """
    headers = dict(HEADERS)
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        body = response.read()
    return json.loads(body) if body else None


def fetch_player_list(url: str, label: str) -> Optional[List[str]]:
    """Fetch a list of player names, deduplicated case-insensitively. None on failure."""
    try:
        players = http_json(url)
        if not isinstance(players, list):
            raise ValueError(f"expected a JSON list, got {type(players).__name__}")
        unique, seen = [], set()
        for name in players:
            if isinstance(name, str) and name.strip() and name.strip().lower() not in seen:
                seen.add(name.strip().lower())
                unique.append(name.strip())
        print(f"✓ Fetched {len(unique)} {label} players to track")
        return unique
    except Exception as e:
        print(f"✗ Error fetching {label} player list: {e}")
        return None


# Character API vocation -> highscores vocation filter. Filtering by vocation
# lets lower level characters show up, since each filter has its own top list.
VOCATION_FILTERS = {
    "knight": "knights", "elite knight": "knights",
    "paladin": "paladins", "royal paladin": "paladins",
    "sorcerer": "sorcerers", "master sorcerer": "sorcerers",
    "druid": "druids", "elder druid": "druids",
    "monk": "monks", "exalted monk": "monks",
    "none": "none",
}

# (world, vocation filter) -> {"entries": {lower name: entry}, "next_page": int, "total_pages": int|None}
# Shared by every list so a world's pages are fetched at most once per run.
_highscore_cache: Dict = {}


def get_character_info(character_name: str) -> Optional[Dict]:
    """Get the canonical name, world and vocation from the character API."""
    try:
        encoded_name = urllib.parse.quote(character_name)
        data = http_json(f"{TIBIADATA_API_BASE}/character/{encoded_name}")
        character = (data or {}).get("character", {}).get("character", {})
        world = character.get("world")
        if not world:
            return None
        info = {
            "name": character.get("name", character_name),
            "world": world,
            "vocation": character.get("vocation", "Unknown"),
        }
        print(f"  Found world: {world} ({info['vocation']})")
        return info
    except Exception as e:
        print(f"  ⚠ Could not get character info: {e}")
        return None


def find_in_highscores(character_name: str, world: str, voc_filter: str) -> Optional[Dict]:
    """Look up a character in a world's experience highscores for one vocation.

    Pages are fetched lazily and cached, so later lookups in the same
    world and vocation reuse what earlier ones already downloaded.
    """
    key = (world, voc_filter)
    state = _highscore_cache.setdefault(key, {"entries": {}, "next_page": 1, "total_pages": None})
    wanted = character_name.lower()

    while wanted not in state["entries"]:
        page = state["next_page"]
        if state["total_pages"] is not None and page > state["total_pages"]:
            break
        try:
            url = f"{TIBIADATA_API_BASE}/highscores/{urllib.parse.quote(world)}/experience/{voc_filter}/{page}"
            highscores = (http_json(url) or {}).get("highscores")
        except Exception as e:
            print(f"  ✗ Error fetching highscores page {page}: {e}")
            return None
        if not highscores:
            print(f"  ✗ Invalid highscores response")
            return None

        for entry in highscores.get("highscore_list") or []:
            state["entries"][entry.get("name", "").lower()] = entry
        state["total_pages"] = highscores.get("highscore_page", {}).get("total_pages", 0)
        state["next_page"] = page + 1
        time.sleep(0.3)  # Small delay between page requests

    entry = state["entries"].get(wanted)
    if not entry:
        print(f"  ✗ Character not found in {voc_filter} highscores (searched {state['next_page'] - 1} pages)")
        return None

    print(f"  ✓ Found in {voc_filter} highscores (rank {entry.get('rank')})")
    return {
        "name": entry.get("name", character_name),
        "world": entry.get("world", world),
        "experience": entry.get("value", 0),
        "level": entry.get("level", 0),
        "vocation": entry.get("vocation", "Unknown"),
        "rank": entry.get("rank", 0),
        "rank_scope": voc_filter,
    }


def get_character_data(character_name: str) -> Optional[Dict]:
    """Fetch character data from TibiaData API using vocation filtered highscores."""
    try:
        info = get_character_info(character_name)
        if not info:
            print(f"  ✗ Could not determine world for '{character_name}'")
            return None

        voc_filter = VOCATION_FILTERS.get(info["vocation"].lower(), "all")
        return find_in_highscores(info["name"], info["world"], voc_filter)

    except Exception as e:
        print(f"✗ Error fetching data for '{character_name}': {e}")
        return None


def load_exp_data(path: str) -> Dict:
    """Load existing exp data from a JSON file."""
    if not Path(path).exists():
        return {}

    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"✗ Error loading {path}: {e}")
        return {}


def save_exp_data(data: Dict, path: str):
    """Save exp data to a JSON file."""
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"✓ Saved exp data to {path}")
    except Exception as e:
        print(f"✗ Error saving {path}: {e}")
        sys.exit(1)


def send_discord_notification(character_name: str, char_data: Dict, notification_type: str = "new", old_data: Optional[Dict] = None):
    """Send Discord webhook notification for character updates.

    Args:
        character_name: Name of the character
        char_data: Current character data
        notification_type: "new" for new character, "update" for experience change
        old_data: Previous character data (for updates)
    """
    if not DISCORD_WEBHOOK_URL:
        print("⚠ No Discord webhook URL configured, skipping notification")
        return

    try:
        if notification_type == "new":
            title = "🆕 New Character Tracked"
            description = f"Started tracking **{character_name}**"
            color = 3447003  # Blue
        else:  # update
            title = "📈 Experience Gained"
            old_exp = old_data.get("experience", 0) if old_data else 0
            new_exp = char_data.get("experience", 0)
            exp_gained = new_exp - old_exp
            description = f"**{character_name}** gained **{exp_gained:,}** experience!"
            color = 5763719  # Green

        fields = [
            {
                "name": "World",
                "value": char_data.get("world", "Unknown"),
                "inline": True
            },
            {
                "name": "Level",
                "value": str(char_data.get("level", "Unknown")),
                "inline": True
            },
            {
                "name": "Vocation",
                "value": char_data.get("vocation", "Unknown"),
                "inline": True
            }
        ]

        # For updates, show old and new experience
        if notification_type == "update" and old_data:
            old_exp = old_data.get("experience", 0)
            new_exp = char_data.get("experience", 0)
            exp_gained = new_exp - old_exp

            fields.append({
                "name": "Experience Change",
                "value": f"{old_exp:,} → {new_exp:,} (+{exp_gained:,})",
                "inline": False
            })

            # Show level change if applicable
            old_level = old_data.get("level", 0)
            new_level = char_data.get("level", 0)
            if old_level != new_level:
                level_gained = new_level - old_level
                fields.append({
                    "name": "Level Up!",
                    "value": f"Level {old_level} → {new_level} (+{level_gained})",
                    "inline": True
                })
        else:
            # For new characters, just show current experience
            fields.append({
                "name": "Experience",
                "value": f"{char_data.get('experience', 0):,}",
                "inline": False
            })

        # Add rank if available
        if "rank" in char_data and char_data["rank"] > 0:
            rank_text = f"#{char_data['rank']}"

            # Show rank change for updates
            same_scope = old_data and old_data.get("rank_scope") == char_data.get("rank_scope")
            if notification_type == "update" and same_scope and "rank" in old_data:
                old_rank = old_data["rank"]
                new_rank = char_data["rank"]
                if old_rank != new_rank:
                    rank_diff = old_rank - new_rank  # Positive if rank improved
                    if rank_diff > 0:
                        rank_text = f"#{new_rank} (↑{rank_diff})"
                    else:
                        rank_text = f"#{new_rank} (↓{abs(rank_diff)})"

            fields.append({
                "name": f"Highscore Rank ({char_data.get('rank_scope', 'all')})",
                "value": rank_text,
                "inline": True
            })

        embed = {
            "title": title,
            "description": description,
            "color": color,
            "fields": fields,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
        }

        payload = {
            "embeds": [embed]
        }

        http_json(DISCORD_WEBHOOK_URL, payload=payload)
        print(f"✓ Sent Discord notification for '{character_name}' ({notification_type})")
    except Exception as e:
        print(f"✗ Error sending Discord notification: {e}")


VOCATION_SHORT = {
    "elite knight": "EK", "knight": "K",
    "royal paladin": "RP", "paladin": "P",
    "master sorcerer": "MS", "sorcerer": "S",
    "elder druid": "ED", "druid": "D",
    "exalted monk": "EM", "monk": "M",
}


def send_troll_summary(changes: List):
    """Send one summary of every troll whose experience changed this run.

    Splits across embeds and messages to stay inside Discord limits
    (4096 chars per embed description, 6000 chars and 10 embeds per message).
    """
    if not TROLL_WEBHOOK_URL:
        print("⚠ No WEBHOOK_TROLL configured, skipping troll summary")
        return

    # Biggest gains first, losses (deaths) at the bottom
    changes = sorted(changes, key=lambda c: c[1]["experience"] - c[2].get("experience", 0), reverse=True)

    lines = []
    for char_name, char_data, old_data in changes:
        diff = char_data["experience"] - old_data.get("experience", 0)
        voc = VOCATION_SHORT.get(char_data.get("vocation", "").lower(), char_data.get("vocation", "?"))
        icon = "📈" if diff > 0 else "💀"
        line = f"{icon} **{char_data['name']}** · {voc} {char_data['level']} · {char_data['world']}\n"
        line += f"\u2003{diff:+,} exp"
        old_level = old_data.get("level", char_data["level"])
        if old_level != char_data["level"]:
            line += f" · Lvl {old_level} → {char_data['level']}"
        lines.append(line)

    descriptions, current = [], ""
    for line in lines:
        if current and len(current) + len(line) + 1 > 3900:
            descriptions.append(current)
            current = ""
        current = f"{current}\n{line}" if current else line
    if current:
        descriptions.append(current)

    timestamp = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    embeds = []
    for idx, description in enumerate(descriptions):
        embed = {"description": description, "color": 15548997, "timestamp": timestamp}  # Red
        if idx == 0:
            embed["title"] = f"👹 Troll activity: {len(changes)} character(s) changed"
        embeds.append(embed)

    # One embed per message keeps every message under the 6000 char total
    for idx, embed in enumerate(embeds):
        try:
            http_json(TROLL_WEBHOOK_URL, payload={"embeds": [embed]})
            print(f"✓ Sent troll summary part {idx + 1}/{len(embeds)}")
        except Exception as e:
            print(f"✗ Error sending troll summary: {e}")
        time.sleep(1)


def track_players(players: List[str], exp_data: Dict):
    """Fetch every player and diff against stored data.

    Returns (updated_data, exp_changes, new_characters).
    """
    new_characters = 0
    exp_changes = []
    updated_data = {}

    for player_name in players:
        print(f"\nProcessing: {player_name}")

        char_data = get_character_data(player_name)

        if char_data:
            is_new = player_name not in exp_data
            old_data = exp_data.get(player_name, {})

            updated_data[player_name] = {
                "name": char_data["name"],
                "world": char_data["world"],
                "experience": char_data["experience"],
                "level": char_data["level"],
                "vocation": char_data.get("vocation", "Unknown"),
                "rank": char_data.get("rank", 0),
                "rank_scope": char_data.get("rank_scope", "all"),
                "last_updated": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
            }

            print(f"  World: {char_data['world']}")
            print(f"  Level: {char_data['level']}")
            print(f"  Vocation: {char_data.get('vocation', 'Unknown')}")
            print(f"  Experience: {char_data['experience']:,}")
            print(f"  Rank: #{char_data.get('rank', 'N/A')}")

            if is_new:
                print(f"  ⭐ New character detected (no notification sent)")
                new_characters += 1
            else:
                old_exp = old_data.get("experience", 0)
                new_exp = char_data["experience"]

                if old_exp != new_exp:
                    exp_gained = new_exp - old_exp
                    print(f"  📈 Experience changed: {old_exp:,} → {new_exp:,} ({exp_gained:+,})")
                    exp_changes.append((player_name, char_data, old_data))
                else:
                    print(f"  ✓ No experience change")

        # Add delay to avoid rate limiting
        time.sleep(0.5)

    return updated_data, exp_changes, new_characters


def main():
    """Main execution function."""
    print("=" * 60)
    print("Tibia Experience Tracker")
    print("=" * 60)

    # Alerts are required; trolls are best effort so a bad trolls.json never blocks alerts
    alerts = fetch_player_list(ALERTS_URL, "alerts")
    if alerts is None:
        sys.exit(1)
    trolls = fetch_player_list(TROLLS_URL, "trolls")

    # ---- Alerts: one notification per character ----
    exp_data = load_exp_data(EXP_JSON_PATH)
    print(f"✓ Loaded existing data for {len(exp_data)} alert characters")

    updated_data, exp_changes, new_characters = track_players(alerts, exp_data)
    save_exp_data(updated_data, EXP_JSON_PATH)

    notifications_sent = 0
    if exp_changes:
        print(f"\n{'=' * 60}")
        print(f"Sending notifications for {len(exp_changes)} experience change(s)")
        print("=" * 60)
        for char_name, char_data, old_data in exp_changes:
            send_discord_notification(char_name, char_data, notification_type="update", old_data=old_data)
            notifications_sent += 1
            time.sleep(1)  # Delay between notifications

    # ---- Trolls: one summary per run; alerts win on overlap ----
    troll_updated, troll_changes = {}, []
    if trolls is not None:
        alert_names = {name.lower() for name in alerts}
        trolls = [name for name in trolls if name.lower() not in alert_names]

        troll_data = load_exp_data(TROLLS_EXP_JSON_PATH)
        print(f"\n✓ Loaded existing data for {len(troll_data)} troll characters")

        troll_updated, troll_changes, _ = track_players(trolls, troll_data)
        save_exp_data(troll_updated, TROLLS_EXP_JSON_PATH)

        if troll_changes:
            print(f"\nSending troll summary for {len(troll_changes)} change(s)")
            send_troll_summary(troll_changes)

    print(f"\n{'=' * 60}")
    print(f"✓ Tracking complete!")
    print(f"  Alert characters tracked: {len(updated_data)}")
    print(f"  New alert characters added: {new_characters}")
    print(f"  Alert experience changes: {len(exp_changes)}")
    print(f"  Discord notifications sent: {notifications_sent}")
    if trolls is not None:
        print(f"  Troll characters tracked: {len(troll_updated)} of {len(trolls)}")
        print(f"  Troll experience changes: {len(troll_changes)}")
    print("=" * 60)


if __name__ == "__main__":
    main()
