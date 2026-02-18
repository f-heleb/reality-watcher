# Reality Watcher 🏠

**Reality Watcher** is an intelligent, web-based Czech real estate monitoring system that tracks property listings from **Sreality.cz**. Built with Django, it provides an intuitive interface to manage search configurations, monitor new listings, and analyze properties using AI-powered insights.

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

Reality Watcher is a Django web application that:
- **Monitors** property search URLs from Sreality
- **Detects** new listings automatically at customizable intervals
- **Stores** listings in a local database with scraped images and contact info
- **Analyzes** listings using AI (OpenAI GPT) to assess value, identify red flags, and provide viewing checklists
- **Tracks** all listings in a responsive web interface with filtering and search capabilities
- **Manages** multiple search configurations from a simple admin panel

Perfect for real estate investors, homebuyers, or anyone tracking the Czech property market.

---

## ✨ Key Features

### 🔍 Sreality Scraping
- Automatic extraction of property listings from Sreality search results
- Detailed structured data: price, area, disposition, locality
- Image downloading from listings
- Contact information extraction (agent name, phone, agency)

### 📊 Web Dashboard
- Clean, responsive interface to browse all tracked listings
- Advanced filtering by price, area, disposition, and locality
- Search functionality across titles and descriptions
- Create and manage multiple property search configurations
- One-click manual scraping to fetch latest listings

### 🧠 AI-Powered Analysis
- Free-form AI analysis via OpenAI GPT-4 Mini
- Price assessment (undervalued/overvalued/fair)
- Red flag detection with severity ratings
- Missing information identification
- Market comparison and positioning
- Viewing checklist generation

### 📈 Portfolio Tracking
- Track personally owned properties
- Calculate ROI and annual returns (CAGR)
- Monitor cash flow (rent minus costs)
- Store property photos and financial details

### ⚙️ Flexible Configuration
- Customizable polling intervals per search
- Background job scheduler (APScheduler)
- Database persistence with SQLite
- Environment-based settings

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────┐
│          Django Web Application             │
│  ┌────────────────────────────────────────┐ │
│  │  Views & Templates                     │ │
│  │  (Browse listings, manage configs)     │ │
│  └────────────┬─────────────────────────┘ │
└───────────────┼──────────────────────────┘
                │
    ┌───────────▼───────────┐
    │   APScheduler Jobs    │
    │  (Background polling) │
    └────────────┬──────────┘
                 │
    ┌────────────▼──────────────┐
    │  Scraper Service          │
    │  (extract_new_listings)   │
    └────────────┬──────────────┘
                 │
    ┌────────────▼──────────────────┐
    │  HTML Parser                  │
    │  (BeautifulSoup)              │
    └────────────┬──────────────────┘
                 │
    ┌────────────▼──────────────────┐
    │  Database                     │
    │  (Listing, SearchConfig, etc) │
    └───────────────────────────────┘
```

### Components

1. **Django Application** (`webapp/`) - RESTful API and web interface
2. **Views** (`listings/views.py`) - Handle HTTP requests and JSON responses
3. **Models** (`listings/models.py`) - Listing, SearchConfig, AIAnalysis, OwnedProperty
4. **Scheduler** (`listings/scheduler.py`) - APScheduler integration for background jobs
5. **Scraper** (`listings/services/scraper.py`) - Fetch and parse Sreality listings
6. **AI Analysis** (`listings/services/ai.py`) - OpenAI GPT integration
7. **Parser** (`src/core/parser.py`) - BeautifulSoup HTML extraction

---

## 📦 Installation

### Prerequisites
- Python 3.9+
- pip and virtual environment

### Steps

1. **Clone the repository**
```bash
git clone https://github.com/f-heleb/reality-watcher.git
cd reality-watcher
```

2. **Create and activate virtual environment**
```bash
python3 -m venv env
source env/bin/activate
```

3. **Install dependencies**
```bash
pip install -r requirements.txt
```

Required packages:
- `django` - Web framework
- `django-apscheduler` - Background job scheduling
- `beautifulsoup4` - HTML parsing
- `lxml` - Fast HTML parser
- `requests` - HTTP client
- `openai` - OpenAI API client
- `python-dotenv` - Environment variable management
- `pillow` - Image processing

---

## ⚙️ Configuration

### Environment Variables

Create a `.env` file in the repository root:

```env
# Django settings
DJANGO_SECRET_KEY=your-secret-key-here
DJANGO_DEBUG=true                           # false in production
DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost

# OpenAI API key (required for AI analysis features)
OPENAI_API_KEY=sk-your-openai-api-key

# Optional configuration
DEFAULT_INTERVAL_SEC=300                    # polling interval in seconds
```

| Variable | Description | Default |
|----------|-------------|---------|
| `DJANGO_SECRET_KEY` | Django secret key for sessions | *required* |
| `DJANGO_DEBUG` | Enable debug mode | `true` |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated allowed hosts | `127.0.0.1,localhost` |
| `OPENAI_API_KEY` | OpenAI API key for AI analysis | *optional* |
| `DEFAULT_INTERVAL_SEC` | Default polling interval in seconds | `300` |

### Search Configuration

Add search configurations via the Django admin or the web interface:

1. Navigate to `/admin/` after starting the server
2. Click "Add Search Config"
3. Enter a name and Sreality search URL
4. Set the polling interval (in seconds)
5. Save — the scheduler will automatically start monitoring
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

### Starting the Web Application

1. **Run migrations** (first time only):
   ```bash
   python webapp/manage.py migrate
   ```

2. **Create a superuser** (optional, for Django admin):
   ```bash
   python webapp/manage.py createsuperuser
   ```

3. **Start the development server**:
   ```bash
   python webapp/manage.py runserver
   ```

   The app will automatically apply any pending migrations (such as the
   `purchase_date` field) on startup, so you don’t normally need to run
   `migrate` by hand unless you’re preparing the database for the first time.

4. **Open in browser**:
   - Web interface: http://127.0.0.1:8000/
   - Django admin: http://127.0.0.1:8000/admin/

### Managing Search Configurations

**Via Web Interface:**
1. Go to http://127.0.0.1:8000/
2. Click "Add Search"
3. Paste a Sreality search URL
4. Set polling interval (in seconds)
5. Listings will start appearing automatically

**Via Django Admin:**
1. Go to http://127.0.0.1:8000/admin/
2. Click "Search configs"
3. Add new configuration with URL and interval
4. Save and the scheduler will pick it up

### Viewing Listings

- **Browse**: All listings appear in the main feed
- **Filter**: By price range, area, disposition, locality
- **Search**: Find specific properties by keyword
- **Analyze**: Click AI button to generate property analysis
- **Track**: Save properties to your personal portfolio

### Manual Scraping

Trigger a scrape immediately without waiting for the interval:
1. Go to search configuration details
2. Click "Scrape Now"
3. New listings will appear within seconds

---

## 🧠 AI Analysis

The AI analysis feature uses OpenAI GPT-4 Mini to analyze properties on demand.

### Requesting Analysis

1. Browse to any listing in the web interface
2. Click the "Analyze" button
3. The AI will generate a detailed report

### Analysis Components

**Price Assessment**
- Verdict: Undervalued / Fair / Overvalued / Cannot assess
- Confidence: 1-5 rating
- Expected price range per m²

**Red Flags**
- Severity: 1-5 rating
- Source: Text analysis / Location estimate / Missing info  
- Examples: suspicious descriptions, missing amenities, high price per m²

**Missing Critical Information**
- Importance: 1-5 rating
- Recommendations on what to verify during viewing

**Market Comparison**
- Segment positioning vs similar properties
- Key pros and cons identification

**Viewing Checklist**
- Practical points to verify
- Questions to ask the agent

---

## 📁 Project Structure

```
reality-watcher/
├── webapp/                       # Django web application
│   ├── manage.py                # Django CLI
│   ├── config/                  # Django configuration
│   │   ├── settings.py          # Django settings
│   │   ├── urls.py              # URL routing
│   │   └── wsgi.py              # WSGI entry point
│   ├── listings/                # Main Django app
│   │   ├── models.py            # Database models
│   │   ├── views.py             # API views
│   │   ├── urls.py              # App URL routing
│   │   ├── admin.py             # Django admin config
│   │   ├── scheduler.py         # APScheduler integration
│   │   ├── services/            # Business logic
│   │   │   ├── scraper.py       # Sreality scraping
│   │   │   ├── ai.py            # AI analysis service
│   │   │   └── __init__.py
│   │   ├── templates/           # HTML templates
│   │   ├── migrations/          # Database migrations
│   │   └── static/              # CSS, JS
│   └── media/                   # User uploads
│
├── src/                         # Shared Python modules
│   ├── core/                    # Core utilities
│   │   ├── config.py            # Configuration
│   │   └── ai_analysis.py       # OpenAI integration
│   └── utils/                   # Shared utilities
│       └── stats_utils.py       # Logging helpers
│
├── logs/                        # Application logs
├── db.sqlite3                   # SQLite database
├── .env                         # Environment variables (create this)
├── requirements.txt             # Python dependencies
└── README.md                    # This file
```

### Component Responsibilities

**`webapp/`** - Django web application
- REST API for listing management
- Web interface for browsing and filtering
- Search configuration management
- Background job scheduler

**`src/core/`** - Shared core modules
- Configuration loading
- OpenAI GPT integration

**`src/utils/`** - Shared utilities
- Statistics and logging

---

## 🔧 How It Works

### Background Scheduler

The application uses APScheduler to run background jobs periodically:

1. **On Startup**
   - Django load all active `SearchConfig` records
   - Create background jobs for each one
   - Set polling interval based on config

2. **Polling Loop** (runs every `interval_sec` seconds)
   - Fetch Sreality search results page
   - Extract listing URLs and metadata
   - Compare with already-stored listing IDs
   - For each new listing:
     - Fetch detail page
     - Extract description and images
     - Extract contact information
     - Save to database
   - Update `last_scraped` timestamp

3. **Data Persistence**
   - All listings stored in SQLite database
   - Images URLs preserved for lazy loading
   - Contact info stored as JSON

### HTML Parsing

The scraper uses BeautifulSoup to extract:
- **Title** and URL
- **Price** (parsed from text)
- **Area** in m²
- **Disposition** (kk, kk, etc.)
- **Locality** (Prague district or area)
- **Description** from detail page
- **Images** URLs
- **Contact info** (agent name, phone, agency)

---

## 👨‍💻 Development

### Setting Up Development Environment

```bash
# Clone and setup
git clone <repo>
cd reality-watcher
python3 -m venv env
source env/bin/activate
pip install -r requirements.txt

# Setup Django
python webapp/manage.py migrate
python webapp/manage.py createsuperuser
python webapp/manage.py runserver

# Open http://127.0.0.1:8000/
```

### Common Tasks

**Add a test search configuration:**
```bash
python webapp/manage.py shell
>>> from listings.models import SearchConfig
>>> SearchConfig.objects.create(
...     name="Test Search",
...     url="https://www.sreality.cz/hledani/prodej/byty/praha",
...     interval_sec=300,
...     is_active=True
... )
>>> exit()
```

**Manually trigger a scrape:**
```bash
python webapp/manage.py shell
>>> from listings.models import SearchConfig
>>> from listings.services.scraper import run_scrape
>>> config = SearchConfig.objects.get(name="Test Search")
>>> count = run_scrape(config)
>>> print(f"Scraped {count} new listings")
```

**Check scheduled jobs:**
```bash
python webapp/manage.py shell
>>> from listings.scheduler import get_scheduler
>>> scheduler = get_scheduler()
>>> for job in scheduler.get_jobs():
...     print(f"{job.id}: {job.next_run_time}")
```

**Run tests:**
```bash
python webapp/manage.py test
```

### Debugging

Enable Django debug logging:
```python
# In webapp/config/settings.py
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'DEBUG',
    },
}
```

Then check console output when scraping runs.

---

## � Known Issues

- Sreality may rate-limit aggressive polling (recommend intervals ≥60 seconds)
- AI analysis requires OpenAI API credits and internet connection
- Some listings may be missing images if Sreality updates their CDN URLs
- Contact info extraction is best-effort (not all listings have complete data)

## 🔮 Future Enhancements

- [ ] PostgreSQL support (currently SQLite only)
- [ ] Plot historical price trends
- [ ] Price drop alerts
- [ ] Email notifications
- [ ] Integration with more Czech portals (Bezrealitky.cz, etc.)
- [ ] Saved search templates
- [ ] Export to CSV/Excel
- [ ] Mobile app
- [ ] Machine learning predictions

---

## 📞 Support

For issues:
1. Check the Django console output for errors
2. Verify `.env` has `OPENAI_API_KEY` set (optional for basic usage)
3. Ensure database is migrated: `python webapp/manage.py migrate`
4. Check database is accessible: `ls -la db.sqlite3`

---

**Made with ☕ for Czech real estate investors and homebuyers**