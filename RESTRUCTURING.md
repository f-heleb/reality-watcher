# Project Restructuring - Summary

## What Was Changed

The Reality Watcher project has been reorganized from a flat file structure to a **modular, well-organized architecture**.

## New Directory Structure

```
reality-watcher/
├── src/                          # All source code
│   ├── core/                     # Shared core functionality
│   │   ├── config.py            # Environment & configuration
│   │   └── ai_analysis.py       # OpenAI GPT integration
│   │
│   ├── utils/                    # Shared utilities
│   │   ├── slack_utils.py       # Slack API helpers
│   │   └── stats_utils.py       # Statistics & logging
│   │
│   ├── sreality/                 # Sreality.cz platform
│   │   ├── manager.py           # Bot manager
│   │   ├── watcher.py           # Background poller
│   │   └── parser.py            # HTML scraper
│   │
│   └── bezrealitky/              # Bezrealitky.cz platform
│       ├── manager.py           # Bot manager
│       ├── watcher.py           # Background poller
│       ├── parser.py            # HTML scraper
│       └── formatter.py         # Slack formatter
│
├── config/                       # Configuration files
│   ├── watchers.json
│   ├── seen_state.json
│   ├── bez_watchers.json
│   └── bez_seen_state.json
│
├── logs/                         # Statistics logs
│   └── *.tsv
│
├── run_manager.py               # Sreality entry point
├── run_bez_manager.py           # Bezrealitky entry point
├── requirements.txt             # Python dependencies
├── .gitignore                   # Git ignore rules
└── README.md                    # Documentation
```

## Key Benefits

### 1. **Clear Separation of Concerns**
   - **Before**: All 17 Python files in root directory
   - **After**: Organized into logical modules
   - Each platform (Sreality/Bezrealitky) is self-contained

### 2. **Better Import Paths**
   - **Before**: `from manager import BotManager`
   - **After**: `from src.sreality.manager import BotManager`
   - Explicit, clear, no naming conflicts

### 3. **Easier to Navigate**
   - Files grouped by responsibility
   - New developers can understand structure quickly
   - Related code stays together

### 4. **Configuration Organization**
   - All JSON configs in `config/` folder
   - All logs in `logs/` folder
   - Clean project root

### 5. **Scalability**
   - Easy to add new platforms (just add new folder under `src/`)
   - Shared utilities don't need duplication
   - Testing becomes simpler

### 6. **Professional Structure**
   - Follows Python best practices
   - Package structure with `__init__.py`
   - Ready for PyPI distribution if needed

## Files Moved

### Core Modules
- `config.py` → `src/core/config.py`
- `ai_analysis.py` → `src/core/ai_analysis.py`

### Utilities
- `slack_utils.py` → `src/utils/slack_utils.py`
- `stats_utils.py` → `src/utils/stats_utils.py`

### Sreality Platform
- `manager.py` → `src/sreality/manager.py`
- `watcher.py` → `src/sreality/watcher.py`
- `sreality_parser.py` → `src/sreality/parser.py`

### Bezrealitky Platform
- `bez_manager.py` → `src/bezrealitky/manager.py`
- `bez_watcher.py` → `src/bezrealitky/watcher.py`
- `bez_parser.py` → `src/bezrealitky/parser.py`
- `bez_formatter.py` → `src/bezrealitky/formatter.py`

### Configuration Files
- `*.json` → `config/*.json`

## Import Changes

All imports have been updated to use the new structure:

**Old:**
```python
from config import DEFAULT_INTERVAL_SEC
from manager import BotManager
from watcher import Watcher
from slack_utils import slack_post_text
```

**New:**
```python
from src.core.config import DEFAULT_INTERVAL_SEC
from src.sreality.manager import BotManager
from src.sreality.watcher import Watcher
from src.utils.slack_utils import slack_post_text
```

## New Files Added

1. **`src/__init__.py`** - Makes src a package
2. **`src/core/__init__.py`** - Core module marker
3. **`src/utils/__init__.py`** - Utils module marker
4. **`src/sreality/__init__.py`** - Sreality package marker
5. **`src/bezrealitky/__init__.py`** - Bezrealitky package marker
6. **`run_bez_manager.py`** - Entry point for Bezrealitky bot
7. **`requirements.txt`** - Python dependencies list
8. **`.gitignore`** - Git ignore rules

## Running the Bots

**Before:**
```bash
python run_manager.py              # Sreality
python bez_manager.py              # Bezrealitky (if it existed)
```

**After:**
```bash
python run_manager.py              # Sreality
python run_bez_manager.py          # Bezrealitky
```

## Migration Notes

### For Existing Deployments

1. **Stop running bots**
2. **Backup** current `*.json` files
3. **Pull changes**
4. **Move** your JSON files to `config/` folder:
   ```bash
   mv watchers.json config/
   mv seen_state.json config/
   mv bez_watchers.json config/
   mv bez_seen_state.json config/
   ```
5. **Install dependencies** (if not already):
   ```bash
   pip install -r requirements.txt
   ```
6. **Restart bots**

### Environment Variables

No changes needed! The `.env` file stays in the project root and works as before.

### Data Persistence

- All existing state is preserved
- JSON file format unchanged
- Just moved to `config/` folder

## Testing

After restructuring:
1. ✅ No Python syntax errors
2. ✅ All imports updated correctly
3. ✅ Module structure validated
4. ✅ Entry points functional

## Future Improvements

With this structure, we can now easily:
- Add unit tests (`tests/` folder)
- Add documentation (`docs/` folder)
- Package for PyPI distribution
- Add more real estate platforms
- Implement CI/CD pipelines

---

**Summary:** The project is now properly organized, easier to maintain, and ready for growth! 🚀
