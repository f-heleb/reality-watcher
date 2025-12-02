# Reality Watcher 🏠

**Reality Watcher** is an intelligent, automated Czech real estate monitoring system that tracks property listings from **Sreality.cz** and **Bezrealitky.cz**, delivering real-time notifications to Slack with optional AI-powered analysis.

---

## 📋 Table of Contents

- [Overview](#overview)
- [Key Features](#key-features)
- [Architecture](#architecture)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [Commands](#commands)
- [AI Analysis](#ai-analysis)
- [Project Structure](#project-structure)
- [How It Works](#how-it-works)
- [Development](#development)

---

## 🎯 Overview

Reality Watcher is a Slack-integrated bot that:
- **Monitors** property search URLs from Sreality and Bezrealitky
- **Detects** new listings automatically based on customizable intervals
- **Notifies** you in dedicated Slack channels with formatted property details
- **Analyzes** listings using AI (OpenAI GPT) to assess value, identify red flags, and provide viewing checklists
- **Tracks** seen listings with TTL (time-to-live) logic to avoid duplicate notifications

Perfect for real estate investors, homebuyers, or anyone tracking the Czech property market.

---

## ✨ Key Features

### 🔍 Dual Platform Support
- **Sreality.cz** - Full scraping with detailed descriptions
- **Bezrealitky.cz** - Robust best-effort extraction

### 🤖 Slack Bot Integration
- Create dedicated channels for each property search
- Real-time notifications with rich formatting
- Interactive commands via Slack mentions
- Direct message AI analysis

### 🧠 AI-Powered Analysis
- Price assessment (undervalued/overvalued/fair)
- Red flag detection (severity ratings)
- Missing information identification
- Market comparison and positioning
- Viewing checklist generation

### 📊 Smart Tracking
- State persistence with JSON storage
- Automatic TTL-based cleanup (3-day default)
- Duplicate detection by (ID, price) pairs
- Handles price changes as new listings

### ⚙️ Flexible Configuration
- Customizable polling intervals
- Adjustable scan limits and burst rates
- User invitations to watcher channels
- Channel archiving and renaming

---

## 🏗️ Architecture

```
┌─────────────────┐
│  Slack Socket   │
│   Mode Client   │
└────────┬────────┘
         │
    ┌────▼────┐
    │   Bot   │
    │ Manager │
    └────┬────┘
         │
    ┌────▼─────────────────┐
    │   Watcher Threads    │
    │ ┌──────┐  ┌────────┐ │
    │ │Sreal-│  │Bezreal-│ │
    │ │ity   │  │itky    │ │
    │ └───┬──┘  └───┬────┘ │
    └─────┼─────────┼──────┘
          │         │
    ┌─────▼─────────▼─────┐
    │   HTML Parsers      │
    │  (BeautifulSoup)    │
    └─────────┬───────────┘
              │
    ┌─────────▼───────────┐
    │  State Persistence  │
    │  (JSON + TTL logic) │
    └─────────────────────┘
```

### Components

1. **Bot Manager** (`manager.py`, `bez_manager.py`) - Handles Slack commands and watcher lifecycle
2. **Watcher Threads** (`watcher.py`, `bez_watcher.py`) - Background polling workers
3. **Parsers** (`sreality_parser.py`, `bez_parser.py`) - Extract listing data from HTML
4. **Formatters** (`bez_formatter.py`) - Format listings for Slack Block Kit
5. **AI Analysis** (`ai_analysis.py`) - OpenAI GPT integration for property analysis
6. **State Management** (`JsonStateRepo`) - Persistent seen-state with TTL
7. **Stats Utils** (`stats_utils.py`) - Logging and statistics

---

## 📦 Installation

### Prerequisites
- Python 3.9+
- Slack workspace with bot permissions
- OpenAI API key (for AI analysis)

### Steps

1. **Clone the repository**
```bash
git clone https://github.com/f-heleb/reality-watcher.git
cd reality-watcher
```

2. **Install dependencies**
```bash
pip install -r requirements.txt
```

Required packages:
- `slack-sdk` - Slack API and Socket Mode
- `beautifulsoup4` - HTML parsing
- `lxml` - Fast HTML parser
- `requests` - HTTP client
- `openai` - OpenAI API client
- `python-dotenv` - Environment variable management

3. **Create Slack App**
- Go to [api.slack.com/apps](https://api.slack.com/apps)
- Create new app from manifest or scratch
- Enable Socket Mode
- Add Bot Token Scopes:
  - `app_mentions:read`
  - `channels:manage`
  - `channels:read`
  - `chat:write`
  - `im:write`
  - `users:read`
- Install app to workspace

4. **Set up environment variables**

Create `.env` file:
```env
# Slack credentials (required)
SLACK_BOT_TOKEN=xoxb-your-bot-token
SLACK_APP_TOKEN=xapp-your-app-token

# OpenAI API key (optional, for AI analysis)
OPENAI_API_KEY=sk-your-openai-key

# Optional configuration
DEFAULT_INTERVAL_SEC=60
WATCHERS_JSON=watchers.json
SEEN_STATE_JSON=seen_state.json
BEZ_AI_ANALYSIS_ENABLED=0
```

---

## ⚙️ Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `SLACK_BOT_TOKEN` | Bot user OAuth token | *required* |
| `SLACK_APP_TOKEN` | App-level token for Socket Mode | *required* |
| `OPENAI_API_KEY` | OpenAI API key for AI analysis | *optional* |
| `DEFAULT_INTERVAL_SEC` | Default polling interval in seconds | `60` |
| `WATCHERS_JSON` | Path to watchers configuration | `watchers.json` |
| `SEEN_STATE_JSON` | Path to seen state storage | `seen_state.json` |
| `BEZ_AI_ANALYSIS_ENABLED` | Enable AI for Bezrealitky (1/0) | `0` |

### Watcher Configuration

Stored in `watchers.json`:
```json
{
  "mywatch": {
    "channel_id": "C0123456789",
    "url": "https://www.sreality.cz/...",
    "interval": 60
  }
}
```

### Seen State

Stored in `seen_state.json` with timestamps:
```json
{
  "C0123456789": {
    "3713540940:5500000": 1731600000.0,
    "3713540941:4800000": 1731686400.0
  }
}
```

Format: `"<listing_id>:<price>": <last_seen_timestamp>`

---

## 🚀 Usage

### Starting the Bot

```bash
python run_manager.py
```

The bot will:
1. Load existing watchers from `watchers.json`
2. Restore seen state from `seen_state.json`
3. Start watcher threads for active channels
4. Connect to Slack via Socket Mode
5. Listen for commands and events

### Testing Connection

In any Slack channel:
```
ping
```
Response: `pong`

---

## 💬 Commands

Mention the bot (`@RealityWatcher`) followed by a command:

### Adding Watchers

**Create new channel with watcher:**
```
@RealityWatcher add mywatch https://www.sreality.cz/... --interval 60 @user1 @user2
```

**Add watcher to current channel:**
```
@RealityWatcher add_here mywatch https://www.sreality.cz/... --interval 90
```

### Managing Watchers

**List all watchers:**
```
@RealityWatcher list
```

**Change polling interval:**
```
@RealityWatcher interval mywatch 120
```

**Remove watcher:**
```
@RealityWatcher remove mywatch
```
*Note: Keeps the channel active*

**Rename watcher and channel:**
```
@RealityWatcher rename mywatch newname
```

**Archive watcher and channel:**
```
@RealityWatcher archive mywatch
```

### Statistics

**Last N listings:**
```
@RealityWatcher stats last 10
```

**Time window statistics:**
```
@RealityWatcher stats window 2025-01-01 to 2025-01-31
```

### AI Analysis

**Analyze specific listing:**
```
@RealityWatcher analyze https://www.sreality.cz/detail/...
```

The bot will:
1. Fetch listing details
2. Run AI analysis
3. Send results to your DM

---

## 🧠 AI Analysis

The AI analysis feature uses OpenAI GPT-4 to provide:

### Price Assessment
- **Verdict**: Undervalued / Fair / Overvalued / Cannot assess
- **Confidence**: 1-5 rating
- **Expected price range** per m²

### Red Flags
- **Severity**: 1-5 rating
- **Source**: Text analysis / Location estimate / Missing info
- Examples:
  - High price per m² for area
  - Missing elevator on high floor
  - Vague or suspicious descriptions

### Missing Critical Information
- **Importance**: 1-5 rating
- Highlights what to ask during viewing:
  - Building type (panel/brick/new)
  - Floor number
  - Elevator availability
  - Parking situation

### Market Comparison
- Segment positioning
- Key pros and cons
- Similar property benchmarking

### Viewing Checklist
- Practical points to verify
- Questions to ask the agent
- Things to inspect carefully

### Example Analysis Output

```
*Analýza inzerátu:* <url|2+kk, Praha 9>

*Shrnutí:* Standardní byt v rozvojové lokalitě s rozumnou cenou. 
Chybí několik klíčových informací o stavu a typu stavby.

*Cena:* odpovídající (confidence 4/5)
_Komentář:_ Cena 85 000 Kč/m² je v normě pro Prahu 9, 
novostavby v této lokalitě...

*Red flags:*
• (4/5) *Chybí informace o patře* – Může být vysoké podlaží bez výtahu
• (3/5) *Vágní popis vybavení* – Nejasné, co je součástí ceny

*Chybějící zásadní informace:*
• (5/5) *Typ stavby* – Zásadní pro posouzení kvality a životnosti
• (4/5) *Podlaží* – Ovlivňuje komfort a hodnotu

*Checklist na prohlídku:*
• Ověřit skutečné podlaží a dostupnost výtahu
• Zkontrolovat kvalitu oken a izolace
• Zeptat se na stáří a typ topení
```

---

## 📁 Project Structure

```
reality-watcher/
├── config.py                 # Centralized configuration
├── run_manager.py           # Main entry point
│
├── manager.py               # Sreality bot manager
├── watcher.py              # Sreality watcher thread
├── sreality_parser.py      # Sreality HTML parser
│
├── bez_manager.py          # Bezrealitky bot manager  
├── bez_watcher.py          # Bezrealitky watcher thread
├── bez_parser.py           # Bezrealitky HTML parser
├── bez_formatter.py        # Bezrealitky Slack formatter
│
├── listing_parser.py       # Unified listing parser
├── slack_utils.py          # Slack API utilities
├── ai_analysis.py          # OpenAI GPT integration
├── stats_utils.py          # Logging and statistics
│
├── watchers.json           # Watcher configurations
├── seen_state.json         # Seen listings state
├── bez_watchers.json       # Bezrealitky watchers
├── bez_seen_state.json     # Bezrealitky seen state
│
├── .env                    # Environment variables (create this)
└── README.md              # This file
```

### Key Files

- **`config.py`** - Loads environment variables, defines constants
- **`run_manager.py`** - Bootstraps the bot, connects to Slack
- **`manager.py`** / **`bez_manager.py`** - Command handlers, watcher lifecycle
- **`watcher.py`** / **`bez_watcher.py`** - Background polling workers
- **`*_parser.py`** - HTML scraping and data extraction
- **`slack_utils.py`** - Slack Block Kit formatting, API wrappers
- **`ai_analysis.py`** - OpenAI integration with structured prompts

---

## 🔧 How It Works

### Watcher Lifecycle

1. **Initialization**
   - Load configuration from JSON
   - Restore seen state with timestamps
   - Start watcher threads for each active channel

2. **Polling Loop**
   ```python
   while not stopped:
       - Prune old entries (TTL: 3 days)
       - Fetch search results page
       - Extract listing links
       - Compare with seen_ids
       - For each new listing:
           - Fetch detail page
           - Extract description
           - Parse fields (price, area, dispo, etc.)
           - Format as Slack blocks
           - Post to channel
           - Update seen_ids with (id, price) key
       - Sleep for interval seconds
   ```

3. **State Persistence**
   - Each new listing updates `seen_state.json`
   - Format: `{"<id>:<price>": <timestamp>}`
   - TTL cleanup removes entries older than 3 days
   - Allows listings to reappear if price changes

### Parsing Strategy

#### Sreality
- Extracts links from search results (`/detail/...`)
- Fetches full detail page for each new listing
- Extracts description between markers (`Zpět` → `Napsat prodejci`)
- Parses structured data from title and HTML

#### Bezrealitky
- More robust best-effort extraction
- Multiple selector fallbacks for each field
- Regex patterns for price, area, disposition
- Feature list extraction from amenities

### AI Analysis Flow

1. User mentions bot with `analyze <URL>`
2. System fetches listing detail
3. Builds unified listing object
4. Calls OpenAI API with structured prompt
5. Receives JSON response with analysis
6. Formats as Slack markdown
7. Sends to user's DM

---

## 👨‍💻 Development

### Adding a New Source

1. Create `<source>_parser.py`:
   ```python
   def extract_new_listings(url, seen_ids, scan_limit, take):
       # Return (new_items, total_found)
       pass
   ```

2. Create `<source>_watcher.py`:
   ```python
   class SourceWatcher(threading.Thread):
       def run(self):
           # Polling loop
           pass
   ```

3. Create `<source>_manager.py`:
   ```python
   class BotManager:
       def handle_command(self, channel_id, user_id, text):
           # Command routing
           pass
   ```

4. Add configuration in `.env`

### Running Tests

```bash
# Test Slack connection
python -c "from slack_sdk import WebClient; WebClient(token='xoxb-...').api_test()"

# Test parser (update URL)
python -c "from sreality_parser import extract_new_listings; print(extract_new_listings('...', set(), 10, 5))"

# Test AI analysis
python -c "from ai_analysis import call_chatgpt_for_listing; print(call_chatgpt_for_listing({'title': 'Test', 'description': 'Nice flat'}))"
```

### Debugging

Enable detailed logging:
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

Check terminal output for parser logs - each new listing prints full details including description.

---

## 📝 License

This project is private and not licensed for public use.

---

## 🤝 Contributing

This is a personal project. For questions or collaboration, contact the repository owner.

---

## 🐛 Known Issues

- Sreality may rate-limit aggressive polling (use intervals ≥60s)
- Bezrealitky HTML structure changes occasionally (parsers use fallbacks)
- AI analysis requires OpenAI API credits
- Large channel histories may slow Slack API calls

---

## 🔮 Future Enhancements

- [ ] SQLite/PostgreSQL backend for better scalability
- [ ] Web dashboard for watcher management
- [ ] Email notifications as alternative to Slack
- [ ] Price drop alerts for existing listings
- [ ] Saved search templates
- [ ] Integration with more Czech real estate portals
- [ ] Machine learning for personalized recommendations
- [ ] Historical price tracking and analytics

---

## 📞 Support

For issues or questions:
1. Check terminal output for error messages
2. Verify `.env` configuration
3. Test Slack permissions
4. Review `watchers.json` and `seen_state.json` for corruption

---

**Made with ☕ for the Czech real estate market**