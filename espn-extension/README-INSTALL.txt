FANTASY COMMAND CENTER — ESPN SYNC v0.2.4
=========================================

WHAT CHANGED
------------
ESPN migrated fantasy reads away from:
https://fantasy.espn.com/apis/v3/...

The current read API is:
https://lm-api-reads.fantasy.espn.com/apis/v3/...

v0.2.4 calls the current read host directly from the extension service worker.

INSTALL
-------
1. Extract this ZIP to a NEW folder.
2. Open edge://extensions or chrome://extensions.
3. Remove the old Fantasy Command Center ESPN Sync extension.
4. Enable Developer mode.
5. Click Load unpacked.
6. Select the v0.2.4 folder.
7. Open your ESPN Fantasy Football TEAM page while signed in.
8. Click ESPN Sync.
9. Click Sync current ESPN team.

EXPECTED FLOW
-------------
1/3 Testing ESPN fantasy API connection…
Then the worker reads:
- league settings
- league teams
- rosters
- matchup/standings data
- up to 250 FREEAGENT/WAIVERS players

Then Command Center analyzes the snapshot and opens League HQ.

SECURITY
--------
The extension does NOT request the "cookies" API permission.
It never reads your ESPN password, espn_s2 value, or SWID value.

The service worker uses fetch(..., credentials:"include") against ESPN's current
read host. Chrome/Edge may attach the existing ESPN session as part of the network
request without exposing the cookie value to our JavaScript.

IF PRIVATE AUTH STILL FAILS
---------------------------
If ESPN returns 401/403 after this change, then the remaining issue is specifically
that ESPN's private-league cookies are not being attached to lm-api-reads from the
extension context.

At that point we can decide whether to:
A) request narrowly-scoped cookie permission and keep cookie values local to the extension, or
B) use a page/network interception approach.

v0.2.4 is intentionally trying the lower-permission option first.
