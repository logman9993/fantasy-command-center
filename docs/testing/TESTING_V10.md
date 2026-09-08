# Five V10 website tests

First confirm the page title says **V10 Beta** and navigation has **Who Should I Start?** (Compare on mobile). The local update does not change a deployed site until it is published.

1. **Import your actual roster screenshot.** League HQ → Build a team → Choose screenshot. Include starters, bench and IR across multiple screenshots if necessary. Review names, resolve initials, and add selected players. Check that names, duplicates and missing players are handled correctly. Refresh: roster and slots should remain.
2. **Read the team improvement report.** Set your real slots and reception scoring, mark a few genuinely available players, then grade the team. Check whether the priorities identify your actual weaknesses and whether the suggested targets/add-drops make sense. Unconfirmed availability must stay labeled.
3. **Use Who Should I Start?** Compare two real alternatives for a selected week. Read the reason for the lean. Switch history to 2024, inspect Stats and Game log, then return to latest. Historical numbers should change; the current-week recommendation must not be driven by the historical display selector. Report missing or unreasonable recommendations with the player pair and selected week.
4. **Check board depth and photos.** All positions should show 25 per board; WR/RB/TE selections should show up to 100 where the data supports that many. Filters should preserve original ranks. Check photos and confirm an unavailable image uses initials. Verify a kicker's stats no longer show an incorrect zero caused by missing column mapping.
5. **Try your phone and the retained features.** Check screenshot upload, the two-player layout, tabs and selectors on mobile. Confirm Sleepers/Injury still load. In League HQ, try Save across devices & send feedback. Send the test number, browser/device, expected result and actual result; do not share your private recovery key or account cookies.

## Automated checks

```
pip install -r requirements.txt ruff==0.16.6
ruff check .
ruff format --check .
python -m unittest discover -v
python self_test.py
node check_js.cjs
node test_extension.cjs
```

For the browser test, install Playwright in a test environment, run the local Flask app on port 5050, then run `node browser-smoke.cjs`. Set `BROWSER_CHANNEL=msedge` to use installed Edge, or install Playwright Chromium. Set `SCREENSHOT_DIR` to an existing directory to retain previews. Only set `BASE_URL` to a dedicated test server. The browser test makes real public player/history requests and real temporary workspace/feedback writes, tests actual bundled OCR on a generated roster image, and uses a synthetic ranking list for the exact 25/100 assertions. It deletes its successful test workspace afterward.
