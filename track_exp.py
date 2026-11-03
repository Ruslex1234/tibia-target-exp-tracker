#!/usr/bin/env python3
"""
Tibia Experience Tracker
Tracks player experience from TibiaData API and sends Discord notifications on changes.
Two lists are tracked: alerts (one message per character to WEBHOOK) and trolls
(one summary message per run to WEBHOOK_TROLL). frags.json mirrors the troll
deaths from the last 30 days where FRAG_KILLER was the 1st or 2nd killer.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Dict, List, Optional
from pathlib import Path


# Configuration
CONFIG_BASE_URL = "https://raw.githubusercontent.com/Ruslex1234/tibia-ops-config/refs/heads/main/.configs"
ALERTS_URL = f"{CONFIG_BASE_URL}/alerts.json"
TROLLS_URL = f"{CONFIG_BASE_URL}/trolls.json"
TIBIADATA_API_BASE = "https://api.tibiadata.com/v5"
EXP_JSON_PATH = "exp.json"
TROLLS_EXP_JSON_PATH = "trolls_exp.json"
FRAGS_JSON_PATH = "frags.json"
FRAG_KILLER = "Ohellnaw"
DISCORD_WEBHOOK_URL = os.environ.get("WEBHOOK", "")
TROLL_WEBHOOK_URL = os.environ.get("WEBHOOK_TROLL", "")
HEADERS = {
    'User-Agent': 'TibiaExpTracker/1.0 (GitHub Actions Bot)',
    'Accept': 'application/json'
}
# Waits between retries of a failed GET (TibiaData answers 502/503 now and then)
RETRY_DELAYS = (2, 5)


def http_json(url: str, payload: Optional[Dict] = None, timeout: int = 10):
    """GET (or POST when payload is given) using only the standard library.

    Raises urllib.error.HTTPError on non-2xx responses, like raise_for_status().
    GETs are retried on 429, 5xx and network errors; POSTs are sent once so a
    Discord message is never posted twice.
    """
    headers = dict(HEADERS)
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    delays = RETRY_DELAYS if payload is None else ()

    for attempt in range(len(delays) + 1):
        req = urllib.request.Request(url, data=data, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                body = response.read()
            return json.loads(body) if body else None
        except urllib.error.HTTPError as e:
            if attempt == len(delays) or not (e.code == 429 or e.code >= 500):
                raise
            print(f"  ↻ HTTP {e.code}, retrying in {delays[attempt]}s")
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt == len(delays):
                raise
            print(f"  ↻ {getattr(e, 'reason', e)}, retrying in {delays[attempt]}s")
        time.sleep(delays[attempt])


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


# lower requested name -> TibiaData "character" object (character info + deaths).
# Filled by get_character_info so the frag list needs no extra requests.
_character_cache: Dict = {}

# world -> {"entries": {lower name: entry}, "next_page": int, "total_pages": int|None}
# Shared by every list so a world's pages are fetched at most once per run.
_highscore_cache: Dict = {}


def get_character_info(character_name: str) -> Optional[Dict]:
    """Get the canonical name, world and vocation from the character API."""
    try:
        encoded_name = urllib.parse.quote(character_name)
        data = http_json(f"{TIBIADATA_API_BASE}/character/{encoded_name}")
        _character_cache[character_name.lower()] = (data or {}).get("character", {})
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


def find_in_highscores(character_name: str, world: str) -> Optional[Dict]:
    """Look up a character in a world's experience highscores.

    Pages are fetched lazily and cached, so later lookups in the same
    world reuse what earlier ones already downloaded.
    """
    state = _highscore_cache.setdefault(world, {"entries": {}, "next_page": 1, "total_pages": None})
    wanted = character_name.lower()

    while wanted not in state["entries"]:
        page = state["next_page"]
        if state["total_pages"] is not None and page > state["total_pages"]:
            break
        try:
            url = f"{TIBIADATA_API_BASE}/highscores/{urllib.parse.quote(world)}/experience/all/{page}"
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
        print(f"  ✗ Character not found in highscores (searched {state['next_page'] - 1} pages)")
        return None

    print(f"  ✓ Found in highscores (rank {entry.get('rank')})")
    return {
        "name": entry.get("name", character_name),
        "world": entry.get("world", world),
        "experience": entry.get("value", 0),
        "level": entry.get("level", 0),
        "vocation": entry.get("vocation", "Unknown"),
        "rank": entry.get("rank", 0),
    }


def get_character_data(character_name: str) -> Optional[Dict]:
    """Fetch character data from TibiaData API using highscores."""
    try:
        info = get_character_info(character_name)
        if not info:
            print(f"  ✗ Could not determine world for '{character_name}'")
            return None

        return find_in_highscores(info["name"], info["world"])

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


def iso_to_unix(value: str) -> Optional[int]:
    """'2026-11-01T10:00:00Z' -> 1761991200, None if unparseable."""
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
    except (AttributeError, ValueError):
        return None


def build_frag_list(trolls: List[str], previous: Dict) -> Optional[Dict]:
    """Rebuild the frag list from scratch, mirroring tibia.com's 30 day deaths.

    A death counts when FRAG_KILLER is the 1st or 2nd entry in the killers
    list (assists don't count) and the victim is a troll on FRAG_KILLER's
    world. Uses the character pages already fetched this run. A troll whose
    page failed to load keeps its entries from the previous list, so an API
    hiccup can't wipe real deaths. Returns None if FRAG_KILLER can't be
    looked up, in which case the previous list should be kept as is.
    """
    if FRAG_KILLER.lower() not in _character_cache:
        get_character_info(FRAG_KILLER)
    killer = _character_cache.get(FRAG_KILLER.lower(), {}).get("character") or {}
    if not killer.get("world"):
        return None
    killer_name, world = killer["name"], killer["world"]

    deaths, failed = [], set()
    for troll in trolls:
        if troll.lower() not in _character_cache:
            failed.add(troll.lower())
            continue
        cached = _character_cache[troll.lower()]
        victim = cached.get("character") or {}
        if victim.get("world") != world:
            continue
        for death in cached.get("deaths") or []:
            killers = death.get("killers") or []
            position = next((i for i, k in enumerate(killers[:2], start=1)
                             if k.get("player") and (k.get("name") or "").lower() == killer_name.lower()), None)
            if position:
                deaths.append({
                    "victim": victim["name"],
                    "victim_level": death.get("level", 0),
                    "position": position,
                    "time": death.get("time", ""),
                    "time_unix": iso_to_unix(death.get("time", "")),
                    "killers": [k.get("name", "") for k in killers],
                    "reason": death.get("reason", ""),
                })

    deaths += [d for d in previous.get("deaths", []) if d.get("victim", "").lower() in failed]
    deaths.sort(key=lambda d: d.get("time_unix") or 0, reverse=True)
    return {
        "killer": killer_name,
        "world": world,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "deaths": deaths,
    }


def character_link(name: str) -> str:
    """Bold Discord markdown link to the character's tibia.com page."""
    url = f"https://www.tibia.com/community/?subtopic=characters&name={urllib.parse.quote_plus(name)}"
    return f"[**{name}**]({url})"


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
            description = f"Started tracking {character_link(character_name)}"
            color = 3447003  # Blue
        else:  # update
            title = "📈 Experience Gained"
            old_exp = old_data.get("experience", 0) if old_data else 0
            new_exp = char_data.get("experience", 0)
            exp_gained = new_exp - old_exp
            description = f"{character_link(character_name)} gained **{exp_gained:,}** experience!"
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
        # One line per character; a level change shows in place of the level
        old_level = old_data.get("level", char_data["level"])
        level = char_data["level"] if old_level == char_data["level"] else f"{old_level} → {char_data['level']}"
        lines.append(
            f"{icon} {character_link(char_data['name'])} · {voc} {level} · "
            f"{char_data['world']} · **{diff:+,}** exp"
        )

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
        elif player_name in exp_data:
            # Keep the last known data so an API hiccup doesn't wipe history
            updated_data[player_name] = exp_data[player_name]
            print(f"  ↺ Lookup failed, keeping last known data")

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

    # ---- Frags: rebuilt every run from the trolls' current death lists ----
    frag_list = None
    if trolls is not None:
        frag_list = build_frag_list(trolls, load_exp_data(FRAGS_JSON_PATH))
        if frag_list is None:
            print(f"\n⚠ Could not look up {FRAG_KILLER}, keeping the previous frag list")
        else:
            print(f"\n⚔ {len(frag_list['deaths'])} troll death(s) with {frag_list['killer']} as 1st/2nd killer")
            save_exp_data(frag_list, FRAGS_JSON_PATH)

    print(f"\n{'=' * 60}")
    print(f"✓ Tracking complete!")
    print(f"  Alert characters tracked: {len(updated_data)}")
    print(f"  New alert characters added: {new_characters}")
    print(f"  Alert experience changes: {len(exp_changes)}")
    print(f"  Discord notifications sent: {notifications_sent}")
    if trolls is not None:
        print(f"  Troll characters tracked: {len(troll_updated)} of {len(trolls)}")
        print(f"  Troll experience changes: {len(troll_changes)}")
        if frag_list is not None:
            print(f"  Frags listed for {frag_list['killer']}: {len(frag_list['deaths'])}")
    print("=" * 60)


if __name__ == "__main__":
    main()
