# ESPN linking options — approval required before changing

V8.6 does **not** change the working ESPN v0.2.4 sync extension.

## Option A — Keep the current manual sync (current production behavior)

- User signs into ESPN normally.
- User opens the ESPN team page.
- User clicks the Command Center extension and presses Sync.
- The extension sends fantasy league JSON to Command Center.
- No ESPN password is collected.
- No browser `cookies` permission is requested.

**Pros:** smallest permission footprint; clear user control; no ESPN authentication stored on Render.

**Cons:** user must manually sync when they want fresh league data.

## Option B — Local auto-sync extension (recommended next experiment if approved)

Add narrowly scoped ESPN permissions plus a browser alarm/background refresh. ESPN credentials/cookies would remain local to the extension; Render would still receive only normalized fantasy data.

Potential behavior:

- sync every 30–60 minutes while the browser is open
- sync immediately when an ESPN fantasy page is visited
- keep each league/team snapshot isolated in the user's extension storage
- push only changed roster/matchup/free-agent data to Command Center

**Pros:** much more automatic without turning Render into an ESPN credential store.

**Cons:** broader browser permission request; still depends on the user's browser being open and ESPN not changing its web endpoints.

## Option C — Server-side persistent ESPN sync

Store an encrypted ESPN session credential on the backend and refresh leagues from Render even while the user's browser is closed. This is similar to the type of model established fantasy products use for persistent ESPN refreshes.

**Pros:** true background synchronization.

**Cons:** substantially higher security burden. It would require proper user accounts, encrypted credential storage, database isolation, rotation/revocation behavior, breach handling, and ideally a managed secrets/KMS strategy. Not recommended for the current no-account architecture.

## Option D — Public ESPN league import

For public ESPN leagues, add a simple league/team URL importer and read public league data without private-session handling.

**Pros:** no extension required for public leagues.

**Cons:** does not solve private league sync.

## Recommended decision

Keep Option A for now. If you want ESPN to refresh automatically, approve **Option B** next. It gives us most of the convenience without storing ESPN session credentials on Render.
