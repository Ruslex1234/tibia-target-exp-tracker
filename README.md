# Tibia Target Experience Tracker

An automated experience tracker for Tibia characters using the TibiaData API. This tool monitors player experience levels and sends Discord notifications when experience changes are detected.

## Features

- **Automatic Tracking**: Monitors multiple Tibia characters automatically
- **TibiaData Integration**: Uses the official TibiaData API v5 for accurate data
- **Discord Notifications**: Sends notifications only when experience changes, showing:
  - Experience changes (gain/loss)
  - Level changes
  - Rank changes in highscores
- **GitHub Actions**: Runs via GitHub Actions, triggered externally every 20 minutes
- **JSON Storage**: Stores experience data in a simple JSON format

## How It Works

1. **Fetches Player List**: Retrieves the list of players from the configured alerts.json
2. **Queries TibiaData API**: For each player:
   - Gets their world from the character API
   - Searches through highscores pages to find the character
   - Extracts accurate experience data including:
     - Character name
     - World
     - Current experience (from highscores "value" field)
     - Level
     - Vocation
     - Highscore rank
3. **Detects Changes**: Compares new data with stored data in `exp.json` to detect:
   - New characters being tracked for the first time
   - Experience changes (gains or losses)
   - Level changes
   - Rank changes
4. **Discord Notifications**: Sends webhook notifications only when experience changes are detected (green notification with gain/loss details)
5. **Stores Data**: Saves the updated data to `exp.json`
6. **Auto-Commits**: Updates the `exp.json` file in the repository automatically

## Configuration

### Player List

Players to track are fetched from:
```
https://raw.githubusercontent.com/Ruslex1234/tibia-ops-config/refs/heads/main/.configs/alerts.json
```

### Troll List

A second, larger list is fetched from:
```
https://raw.githubusercontent.com/Ruslex1234/tibia-ops-config/refs/heads/main/.configs/trolls.json
```

- State is stored separately in `trolls_exp.json`
- Instead of one message per character, each run sends **one summary** to the `WEBHOOK_TROLL` secret, listing every troll whose exp changed (biggest gains first, deaths at the bottom)
- Names that also appear in `alerts.json` are tracked only as alerts
- Duplicate names are ignored; characters not on their world's highscores are skipped
- If `trolls.json` can't be fetched, alerts still run normally

### Frag List

Each run rebuilds `frags.json` from scratch, with one list per character in `alerts.json`: every death from the last 30 days (what tibia.com keeps) of a troll on that character's world where **the alert character appears as a killer or an assist**. A death is marked `"frag": true` only when the alert character is the **1st or 2nd killer**; lower killer positions and assists are listed but don't count. Deaths that age out on tibia.com disappear from the list on the next run.

- No extra API requests: it reuses the character pages already fetched for exp tracking
- If a troll's page fails to load, that troll keeps its previous entries; if an alert character can't be looked up, their previous list is kept as is
- `position` is the alert character's place in the killers list (`null` if they only assisted); `assist` says whether they are in the assists list
- Times are UTC in two forms: `time` (ISO 8601) and `time_unix` (seconds), newest first

```json
{
  "updated_at": "2026-11-03T17:07:40Z",
  "characters": [
    {
      "killer": "Ohellnaw",
      "world": "Firmera",
      "deaths": [
        {
          "victim": "Some Troll",
          "victim_level": 402,
          "frag": true,
          "position": 2,
          "assist": false,
          "time": "2026-11-03T09:00:00Z",
          "time_unix": 1793696400,
          "killers": [{"name": "Someone", "player": true}, {"name": "Ohellnaw", "player": true}],
          "assists": [],
          "reason": "Killed at Level 402 by Someone and Ohellnaw."
        }
      ]
    }
  ]
}
```

`frags.html` shows this in the style of tibia.com's tables, with every time converted to the viewer's own timezone. Opened as is, it lists every alert character with how many frags they have left today, this week and this month before reaching the red skull limits (3 in 24 hours, 5 in 7 days, 10 in 30 days), counted back from the moment the page is opened and shown in red at 0; each name opens that character's sub page (`frags.html?char=Ohellnaw`) with Date, Character, Death and Frag columns. It loads `frags.json` from the repo each time it opens, so it never needs rebuilding. Serve it with GitHub Pages (Settings, Pages, deploy from `main`, root).

### Highscore Lookup

Each character's world comes from the character API, then the tracker finds them in that world's experience highscores (top 1000). Pages are cached per world, so each page is downloaded at most once per run no matter how many tracked characters share a world. If a lookup fails, the last known data is kept instead of being dropped.

### Discord Webhook

The Discord webhook URL must be configured as a repository secret:
- **Secret Name**: `WEBHOOK`
- **Location**: Repository Settings → Secrets and variables → Actions

#### Notification Behavior

**Experience Change Notifications** (Green)
- Sent **only** when experience changes are detected
- Shows:
  - World, Level, Vocation
  - Experience change (old → new with gain/loss amount)
  - Level changes (if applicable)
  - Rank changes with ↑/↓ indicators (if applicable)
- **Not sent** for new characters being added to tracking
- Only triggers when experience value actually changes between checks

## Files

- **`track_exp.py`**: Main Python script that handles tracking
- **`exp.json`**: JSON file storing current experience data for all tracked characters
- **`trolls_exp.json`**: Experience data for the troll list
- **`frags.json`**: Troll deaths (last 30 days) involving each alert character, with frags (1st or 2nd killer) marked
- **`frags.html`**: Page that shows `frags.json` in the viewer's local time, with a sub page per alert character
- **`.github/workflows/track-exp.yml`**: GitHub Actions workflow configuration

## Workflow Schedule

The workflow has only a `workflow_dispatch` trigger. An external scheduler calls it every 20 minutes (:07, :27, :47), and it can also be run by hand from the Actions tab. There is no `schedule:` cron on purpose: a second trigger only produced runs that queued behind the concurrency lock and started from stale data.

Reliability:
- Each run checks out the latest commit on the branch, so it always compares against the data the previous run saved
- TibiaData requests are retried on 429/5xx/network errors (waits of 2s and 5s); Discord posts are never retried, so nothing is sent twice
- The data commit is pushed with up to 4 attempts; each attempt starts from the remote tip and writes this run's data files on top whole, so JSON is never line merged

## Data Format

### exp.json Structure

```json
{
  "Character Name": {
    "name": "Character Name",
    "world": "World Name",
    "experience": 12345678,
    "level": 123,
    "vocation": "Elite Knight",
    "rank": 42,
    "last_updated": "2025-11-15 12:00:00 UTC"
  }
}
```

**Fields:**
- `name`: Character's display name
- `world`: Game world/server the character belongs to
- `experience`: Total experience points (from highscores API)
- `level`: Current character level
- `vocation`: Character's vocation (e.g., "Elite Knight", "Royal Paladin", etc.)
- `rank`: Position in the world's experience highscores
- `last_updated`: Timestamp of last data update (UTC)

## Manual Execution

To run the tracker manually locally:

```bash
# No dependencies to install: only the Python 3 standard library is used

# Set Discord webhook (optional)
export WEBHOOK="your_discord_webhook_url"

# Run the tracker
python3 track_exp.py
```

**Note**: The TibiaData API may block requests from certain IP addresses or environments due to anti-bot protection. If you encounter 403 errors when running locally, this is expected. The script will work correctly when running via GitHub Actions.

## GitHub Actions Setup

The workflow is automatically configured and will:
1. Check out the repository
2. Run the tracker script with the runner's preinstalled `python3` (no setup or install steps)
3. Commit and push any changes to `exp.json`

Runs never overlap: a `concurrency` group queues a new run until the previous one finishes.

## Permissions

The GitHub Actions workflow requires:
- **contents: write** - To commit and push exp.json updates

## API Reference

This project uses the TibiaData API v5:
- **Base URL**: `https://api.tibiadata.com/v5`
- **Character Endpoint**: `/character/{name}` - Used to get character's world
- **Highscores Endpoint**: `/highscores/{world}/experience/all/{page}` - Used to get accurate experience data
- **Documentation**: [TibiaData.com](https://tibiadata.com)

The tracker first queries the character endpoint to determine which world the character belongs to, then searches through the highscores pages for that world to find the character's accurate experience value.

## License

This project is provided as-is for tracking Tibia character experience.