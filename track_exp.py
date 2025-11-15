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


def get_character_data(character_name: str) -> Optional[Dict]:
    """Fetch character data from TibiaData API."""
    try:
        # URL encode the character name
        encoded_name = requests.utils.quote(character_name)
        url = f"{TIBIADATA_API_BASE}/character/{encoded_name}"

        # Add User-Agent header to avoid 403 errors
        headers = {
            'User-Agent': 'TibiaExpTracker/1.0 (GitHub Actions Bot)',
            'Accept': 'application/json'
        }

        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()

        # Check if character exists
        if "character" not in data or "character" not in data["character"]:
            print(f"✗ Character '{character_name}' not found")
            return None

        char_info = data["character"]["character"]

        return {
            "name": char_info.get("name", character_name),
            "world": char_info.get("world", "Unknown"),
            "experience": char_info.get("experience", 0),
            "level": char_info.get("level", 0)
        }
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


def send_discord_notification(character_name: str, char_data: Dict):
    """Send Discord webhook notification for new character."""
    if not DISCORD_WEBHOOK_URL:
        print("⚠ No Discord webhook URL configured, skipping notification")
        return

    try:
        embed = {
            "title": "🆕 New Character Tracked",
            "description": f"Started tracking **{character_name}**",
            "color": 3447003,  # Blue color
            "fields": [
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
                    "name": "Experience",
                    "value": f"{char_data.get('experience', 0):,}",
                    "inline": False
                }
            ],
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
        print(f"✓ Sent Discord notification for '{character_name}'")
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
    new_characters = []
    updated_data = {}

    for player_name in players:
        print(f"\nProcessing: {player_name}")

        # Fetch character data
        char_data = get_character_data(player_name)

        if char_data:
            # Check if this is a new character
            is_new = player_name not in exp_data

            # Store the data
            updated_data[player_name] = {
                "name": char_data["name"],
                "world": char_data["world"],
                "experience": char_data["experience"],
                "level": char_data["level"],
                "last_updated": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
            }

            print(f"  World: {char_data['world']}")
            print(f"  Level: {char_data['level']}")
            print(f"  Experience: {char_data['experience']:,}")

            if is_new:
                print(f"  ⭐ New character detected!")
                new_characters.append((player_name, char_data))

        # Add delay to avoid rate limiting
        time.sleep(0.5)

    # Save updated data
    save_exp_data(updated_data)

    # Send Discord notifications for new characters
    if new_characters:
        print(f"\n{'=' * 60}")
        print(f"Sending notifications for {len(new_characters)} new character(s)")
        print("=" * 60)
        for char_name, char_data in new_characters:
            send_discord_notification(char_name, char_data)
            time.sleep(1)  # Delay between notifications

    print(f"\n{'=' * 60}")
    print(f"✓ Tracking complete!")
    print(f"  Total characters tracked: {len(updated_data)}")
    print(f"  New characters: {len(new_characters)}")
    print("=" * 60)


if __name__ == "__main__":
    main()
