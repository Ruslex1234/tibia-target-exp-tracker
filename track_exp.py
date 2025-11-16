#!/usr/bin/env python3
"""
Tibia Experience Tracker
Tracks player experience from TibiaData API and sends Discord notifications for new players.
"""

import json
import os
import sys
import time
import requests
from typing import Dict, List, Optional
from pathlib import Path


# Configuration
ALERTS_URL = "https://raw.githubusercontent.com/Ruslex1234/tibia-ops-config/refs/heads/main/.configs/alerts.json"
TIBIADATA_API_BASE = "https://api.tibiadata.com/v4"
EXP_JSON_PATH = "exp.json"
DISCORD_WEBHOOK_URL = os.environ.get("WEBHOOK", "")


def fetch_player_list() -> List[str]:
    """Fetch the list of players to track from the alerts.json file."""
    try:
        headers = {
            'User-Agent': 'TibiaExpTracker/1.0 (GitHub Actions Bot)',
            'Accept': 'application/json'
        }
        response = requests.get(ALERTS_URL, headers=headers, timeout=10)
        response.raise_for_status()
        players = response.json()
        print(f"✓ Fetched {len(players)} players to track")
        return players
    except Exception as e:
        print(f"✗ Error fetching player list: {e}")
        sys.exit(1)


def get_character_world(character_name: str) -> Optional[str]:
    """Get the world a character belongs to from character API."""
    try:
        encoded_name = requests.utils.quote(character_name)
        url = f"{TIBIADATA_API_BASE}/character/{encoded_name}"

        headers = {
            'User-Agent': 'TibiaExpTracker/1.0 (GitHub Actions Bot)',
            'Accept': 'application/json'
        }

        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()

        if "character" in data and "character" in data["character"]:
            world = data["character"]["character"].get("world")
            if world:
                print(f"  Found world: {world}")
                return world

        return None
    except Exception as e:
        print(f"  ⚠ Could not get world from character API: {e}")
        return None


def search_highscores_for_character(character_name: str, world: str) -> Optional[Dict]:
    """Search highscores API to find character and get experience data."""
    try:
        headers = {
            'User-Agent': 'TibiaExpTracker/1.0 (GitHub Actions Bot)',
            'Accept': 'application/json'
        }

        # Start from page 1 and search through pages
        page = 1
        max_pages = 20  # TibiaData typically has ~20 pages in highscores

        while page <= max_pages:
            url = f"{TIBIADATA_API_BASE}/highscores/{world}/experience/all/{page}"

            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()

            if "highscores" not in data:
                print(f"  ✗ Invalid highscores response")
                return None

            highscores = data["highscores"]
            highscore_list = highscores.get("highscore_list", [])

            # Search for character in current page
            for entry in highscore_list:
                if entry.get("name", "").lower() == character_name.lower():
                    print(f"  ✓ Found in highscores (page {page}, rank {entry.get('rank')})")
                    return {
                        "name": entry.get("name", character_name),
                        "world": entry.get("world", world),
                        "experience": entry.get("value", 0),
                        "level": entry.get("level", 0),
                        "vocation": entry.get("vocation", "Unknown"),
                        "rank": entry.get("rank", 0)
                    }

            # Check if we should continue to next page
            page_info = highscores.get("highscore_page", {})
            total_pages = page_info.get("total_pages", 0)

            if page >= total_pages:
                break

            page += 1
            time.sleep(0.3)  # Small delay between page requests

        print(f"  ✗ Character not found in highscores (searched {page-1} pages)")
        return None

    except Exception as e:
        print(f"  ✗ Error searching highscores: {e}")
        return None


def get_character_data(character_name: str) -> Optional[Dict]:
    """Fetch character data from TibiaData API using highscores."""
    try:
        # Step 1: Get the character's world
        world = get_character_world(character_name)

        if not world:
            print(f"  ✗ Could not determine world for '{character_name}'")
            return None

        # Step 2: Search highscores for the character to get accurate experience
        char_data = search_highscores_for_character(character_name, world)

        return char_data

    except Exception as e:
        print(f"✗ Error fetching data for '{character_name}': {e}")
        return None


def load_exp_data() -> Dict:
    """Load existing exp.json data."""
    if not Path(EXP_JSON_PATH).exists():
        return {}

    try:
        with open(EXP_JSON_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"✗ Error loading exp.json: {e}")
        return {}


def save_exp_data(data: Dict):
    """Save exp data to exp.json."""
    try:
        with open(EXP_JSON_PATH, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"✓ Saved exp data to {EXP_JSON_PATH}")
    except Exception as e:
        print(f"✗ Error saving exp.json: {e}")
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
            if notification_type == "update" and old_data and "rank" in old_data:
                old_rank = old_data["rank"]
                new_rank = char_data["rank"]
                if old_rank != new_rank:
                    rank_diff = old_rank - new_rank  # Positive if rank improved
                    if rank_diff > 0:
                        rank_text = f"#{new_rank} (↑{rank_diff})"
                    else:
                        rank_text = f"#{new_rank} (↓{abs(rank_diff)})"

            fields.append({
                "name": "Highscore Rank",
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

        response = requests.post(
            DISCORD_WEBHOOK_URL,
            json=payload,
            timeout=10
        )
        response.raise_for_status()
        print(f"✓ Sent Discord notification for '{character_name}' ({notification_type})")
    except Exception as e:
        print(f"✗ Error sending Discord notification: {e}")


def main():
    """Main execution function."""
    print("=" * 60)
    print("Tibia Experience Tracker")
    print("=" * 60)

    # Fetch player list
    players = fetch_player_list()

    # Load existing exp data
    exp_data = load_exp_data()
    print(f"✓ Loaded existing data for {len(exp_data)} characters")

    # Track each player
    new_characters = 0
    exp_changes = []
    updated_data = {}

    for player_name in players:
        print(f"\nProcessing: {player_name}")

        # Fetch character data
        char_data = get_character_data(player_name)

        if char_data:
            # Check if this is a new character or an update
            is_new = player_name not in exp_data
            old_data = exp_data.get(player_name, {})

            # Store the data
            updated_data[player_name] = {
                "name": char_data["name"],
                "world": char_data["world"],
                "experience": char_data["experience"],
                "level": char_data["level"],
                "vocation": char_data.get("vocation", "Unknown"),
                "rank": char_data.get("rank", 0),
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
                # Check if experience has changed
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

    # Save updated data
    save_exp_data(updated_data)

    # Send Discord notifications for experience changes only
    notifications_sent = 0

    if exp_changes:
        print(f"\n{'=' * 60}")
        print(f"Sending notifications for {len(exp_changes)} experience change(s)")
        print("=" * 60)
        for char_name, char_data, old_data in exp_changes:
            send_discord_notification(char_name, char_data, notification_type="update", old_data=old_data)
            notifications_sent += 1
            time.sleep(1)  # Delay between notifications

    print(f"\n{'=' * 60}")
    print(f"✓ Tracking complete!")
    print(f"  Total characters tracked: {len(updated_data)}")
    print(f"  New characters added: {new_characters}")
    print(f"  Experience changes: {len(exp_changes)}")
    print(f"  Discord notifications sent: {notifications_sent}")
    print("=" * 60)


if __name__ == "__main__":
    main()
