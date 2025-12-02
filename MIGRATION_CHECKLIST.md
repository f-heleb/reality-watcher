# Migration Checklist

Use this checklist when upgrading an existing Reality Watcher installation to the new structure.

## Pre-Migration

- [ ] **Backup current installation**
  ```bash
  cp -r reality-watcher reality-watcher-backup
  ```

- [ ] **Stop all running bot processes**
  - Stop Sreality bot (Ctrl+C or `kill <pid>`)
  - Stop Bezrealitky bot if running

- [ ] **Document current configuration**
  - Note your Slack channel IDs
  - Note active watchers
  - Save a copy of your `.env` file

## Migration Steps

- [ ] **1. Pull latest changes**
  ```bash
  cd reality-watcher
  git pull origin main
  ```

- [ ] **2. Verify new structure**
  ```bash
  ls -la src/
  ls -la config/
  ```

- [ ] **3. Install/update dependencies**
  ```bash
  pip install -r requirements.txt
  ```

- [ ] **4. Migrate JSON files**
  ```bash
  # If files are in root, move them:
  mv watchers.json config/watchers.json 2>/dev/null || echo "Already moved"
  mv seen_state.json config/seen_state.json 2>/dev/null || echo "Already moved"
  mv bez_watchers.json config/bez_watchers.json 2>/dev/null || echo "Already moved"
  mv bez_seen_state.json config/bez_seen_state.json 2>/dev/null || echo "Already moved"
  ```

- [ ] **5. Verify config files are in place**
  ```bash
  ls config/
  # Should show: watchers.json, seen_state.json, etc.
  ```

- [ ] **6. Check .env file**
  ```bash
  cat .env
  # Verify all tokens are present
  ```

## Post-Migration Testing

- [ ] **7. Start Sreality bot**
  ```bash
  python run_manager.py
  ```
  Expected output:
  ```
  ✅ Sreality Manager running. Type 'ping' in any channel to test events.
  ```

- [ ] **8. Test in Slack**
  - Send `ping` → Should receive `pong`
  - Send `@BotName help` → Should receive help menu
  - Send `@BotName list` → Should show your watchers

- [ ] **9. Verify watchers are running**
  - Check that channels are still receiving updates
  - Monitor for at least one polling cycle (check interval)

- [ ] **10. (Optional) Start Bezrealitky bot**
  ```bash
  python run_bez_manager.py
  ```

- [ ] **11. Check logs**
  ```bash
  ls logs/
  # Should show *.tsv files if stats were enabled
  ```

## Validation

- [ ] **All watchers restored** - `@BotName list` shows correct count
- [ ] **Seen state preserved** - No duplicate notifications
- [ ] **New listings detected** - Bot responds to new properties
- [ ] **Commands working** - All bot commands respond correctly
- [ ] **No error messages** - Terminal shows no import/runtime errors

## Rollback (If Needed)

If something goes wrong:

- [ ] **Stop new bots**
  ```bash
  # Press Ctrl+C in terminals
  ```

- [ ] **Restore from backup**
  ```bash
  cd ..
  mv reality-watcher reality-watcher-new
  mv reality-watcher-backup reality-watcher
  cd reality-watcher
  ```

- [ ] **Restart old version**
  ```bash
  python run_manager.py  # or whatever your old entry point was
  ```

## Success Criteria

✅ All checklist items completed  
✅ Bots running without errors  
✅ Watchers functioning normally  
✅ Commands responding correctly  
✅ No data loss  

## Notes

- **Downtime:** Plan for 5-10 minutes of bot downtime during migration
- **Timing:** Best done during low-activity hours
- **Testing:** Test in a staging Slack workspace first if possible
- **Support:** Keep backup until confirmed stable (24+ hours)

---

**Completed on:** _______________  
**Completed by:** _______________  
**Issues encountered:** _______________

---

## Common Issues and Solutions

### Issue: "ModuleNotFoundError: No module named 'src'"
**Solution:** Ensure you're in the project root directory when running.

### Issue: "FileNotFoundError: config/watchers.json"
**Solution:** JSON files weren't moved. Re-run step 4.

### Issue: Bot starts but doesn't respond
**Solution:** Check Slack permissions, verify tokens in .env.

### Issue: Duplicate notifications
**Solution:** Seen state didn't transfer. Stop bot, restore seen_state.json.

---

**After successful migration, you can delete:**
- `reality-watcher-backup/` (after 48 hours of stable operation)
- `*.json.backup` files (after verification)
