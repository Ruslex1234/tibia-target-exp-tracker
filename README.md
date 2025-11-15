# Tibia Target Experience Tracker

An automated experience tracker for Tibia characters using the TibiaData API. This tool monitors player experience levels and sends Discord notifications when new characters are added to tracking.

## Features

- **Automatic Tracking**: Monitors multiple Tibia characters automatically
- **TibiaData Integration**: Uses the official TibiaData API v4 for accurate data
- **Discord Notifications**: Sends notifications when new characters are tracked
- **GitHub Actions**: Runs automatically on a schedule via GitHub Actions
- **JSON Storage**: Stores experience data in a simple JSON format

## How It Works

1. **Fetches Player List**: Retrieves the list of players from the configured alerts.json
2. **Queries TibiaData API**: For each player, fetches their character data including:
   - Character name
   - World
   - Current experience
   - Level
3. **Stores Data**: Saves the data to `exp.json`
4. **Discord Notifications**: Sends a Discord webhook notification for newly tracked characters
5. **Auto-Commits**: Updates the `exp.json` file in the repository automatically

## Configuration

### Player List

Players to track are fetched from:
```
https://raw.githubusercontent.com/Ruslex1234/tibia-ops-config/refs/heads/main/.configs/alerts.json
```

### Discord Webhook

The Discord webhook URL must be configured as a repository secret:
- **Secret Name**: `WEBHOOK`
- **Location**: Repository Settings → Secrets and variables → Actions

## Files

- **`track_exp.py`**: Main Python script that handles tracking
- **`exp.json`**: JSON file storing current experience data for all tracked characters
- **`requirements.txt`**: Python dependencies
- **`.github/workflows/track-exp.yml`**: GitHub Actions workflow configuration

## Workflow Schedule

The tracker runs automatically:
- **Every 30 minutes** (at :00 and :30 of each hour)
- **Manual trigger** available via GitHub Actions UI

## Data Format

### exp.json Structure

```json
{
  "Character Name": {
    "name": "Character Name",
    "world": "World Name",
    "experience": 12345678,
    "level": 123,
    "last_updated": "2025-11-15 12:00:00 UTC"
  }
}
```

## Manual Execution

To run the tracker manually locally:

```bash
# Install dependencies
pip install -r requirements.txt

# Set Discord webhook (optional)
export WEBHOOK="your_discord_webhook_url"

# Run the tracker
python track_exp.py
```

**Note**: The TibiaData API may block requests from certain IP addresses or environments due to anti-bot protection. If you encounter 403 errors when running locally, this is expected. The script will work correctly when running via GitHub Actions.

## GitHub Actions Setup

The workflow is automatically configured and will:
1. Check out the repository
2. Set up Python 3.11
3. Install dependencies
4. Run the tracker script
5. Commit and push any changes to `exp.json`

## Permissions

The GitHub Actions workflow requires:
- **contents: write** - To commit and push exp.json updates

## API Reference

This project uses the TibiaData API v4:
- **Base URL**: `https://api.tibiadata.com/v4`
- **Endpoint**: `/character/{name}`
- **Documentation**: [TibiaData.com](https://tibiadata.com)

## License

This project is provided as-is for tracking Tibia character experience.