# Quick Setup Guide

## For New Installations

### 1. Clone Repository
```bash
git clone https://github.com/f-heleb/reality-watcher.git
cd reality-watcher
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Create Environment File
Create `.env` file in project root:
```env
# Sreality Bot (required)
SLACK_BOT_TOKEN=xoxb-your-token-here
SLACK_APP_TOKEN=xapp-your-token-here

# Bezrealitky Bot (optional)
BEZ_SLACK_BOT_TOKEN=xoxb-your-token-here
BEZ_SLACK_APP_TOKEN=xapp-your-token-here

# OpenAI (optional, for AI analysis)
OPENAI_API_KEY=sk-your-key-here

# Configuration (optional, defaults shown)
DEFAULT_INTERVAL_SEC=60
```

### 4. Initialize Config Directory
The `config/` folder will be created automatically with default JSON files when you first run the bot.

### 5. Run the Bot
**Sreality:**
```bash
python run_manager.py
```

**Bezrealitky (optional):**
```bash
python run_bez_manager.py
```

---

## For Existing Installations (Upgrade)

### 1. Backup Your Data
```bash
# Backup your JSON configuration files
cp watchers.json watchers.json.backup
cp seen_state.json seen_state.json.backup
cp bez_watchers.json bez_watchers.json.backup 2>/dev/null
cp bez_seen_state.json bez_seen_state.json.backup 2>/dev/null
```

### 2. Pull Changes
```bash
git pull origin main
```

### 3. Install New Dependencies
```bash
pip install -r requirements.txt
```

### 4. Migrate Configuration Files
```bash
# Move JSON files to config/ folder
mv watchers.json config/watchers.json
mv seen_state.json config/seen_state.json
mv bez_watchers.json config/bez_watchers.json 2>/dev/null
mv bez_seen_state.json config/bez_seen_state.json 2>/dev/null
```

### 5. Verify Structure
```bash
# Check that files are in the right place
ls config/
ls src/
```

### 6. Restart Bots
```bash
# Stop old processes (Ctrl+C or kill)
# Start new ones:
python run_manager.py
```

---

## Verification

After starting the bot, you should see:
```
BOT= xoxb-...
APP= xapp-...
[boot] Using watchers file: config/watchers.json
[boot] Using seen-state file: config/seen_state.json
[config] DEFAULT_INTERVAL_SEC = 60 | CONFIG_PATH = config/watchers.json | STATE_PATH = config/seen_state.json
✅ Sreality Manager running. Type 'ping' in any channel to test events.
```

Test in Slack:
1. Send `ping` in any channel → Should receive `pong`
2. Send `@BotName help` → Should receive help message

---

## Troubleshooting

### Import Errors
**Error:** `ModuleNotFoundError: No module named 'src'`

**Solution:** Make sure you're running from the project root:
```bash
cd reality-watcher
python run_manager.py
```

### Missing Config Files
**Error:** `FileNotFoundError: config/watchers.json`

**Solution:** The file will be created automatically. Ensure `config/` folder exists:
```bash
mkdir config
```

### Slack Connection Issues
**Error:** `Missing required environment variables`

**Solution:** Check your `.env` file has the correct tokens:
```bash
cat .env
```

---

## Directory Structure Check

Your project should look like this:
```
reality-watcher/
├── src/
│   ├── core/
│   ├── utils/
│   ├── sreality/
│   └── bezrealitky/
├── config/
├── logs/
├── run_manager.py
├── .env
└── README.md
```

If not, re-run the installation steps.

---

**Need help?** Check the full README.md or open an issue on GitHub.
