# Five website tests for V9

Run these after the V9 beta is deployed. The live site must identify itself as V9 Beta and show Decision Lab; otherwise it is still the old deployment.

1. **Build and save your real team.** In League HQ, add your roster manually, set your actual starting slots (including Superflex if applicable), and mark a few genuinely available players. Refresh. Your roster and slots should remain. In Decision Lab, set passing TD points and TE premium to match your league. Report any missing player, lost setting or duplicated/incorrectly eligible starter.

2. **Challenge an add/drop recommendation.** Evaluate the roster, open one suggested swap and inspect its before/after lineup. Protect the proposed drop, then evaluate again. That player must disappear from drop suggestions. No suggestion should add a player you did not mark available. Tell me whether the recommendation makes football sense and paste its reasoning.

3. **Compare a trade.** Enter another manager's full roster and select one player to give and one to receive. Both teams should show before/after lineup values, with each player appearing at most once. No trade is submitted. Report an example where the values or lineup choice feel wrong.

4. **Check stats and the mobile view.** On Players, choose 2024, analyze a player you know, and compare the actual stats with your fantasy site. Use Player usage history & comparison for two players. Return to Stats: latest; it should use the newest available results and label their season. On your phone, confirm Decision Lab is reachable, controls fit and text is readable. Missing data should not masquerade as a zero-point game.

5. **Test connections and feedback.** Confirm Sleeper still loads your correct team. Try ESPN sync with extension 0.2.5; report the exact stage/error if it fails. Test Yahoo only after its setup is configured. An ordinary refresh must not force an old ESPN snapshot open. Create a private workspace key, save/load it in a second browser, and submit feedback. Cross-device saves require a persistent server disk; never include your recovery key, passwords or cookies in your feedback.

For feedback, send: test number, device/browser, player/team involved, what you expected, what happened, and any visible error text.

## Automated browser smoke test

Install Playwright in a local test environment (`npm install --no-save playwright` and `npx playwright install chromium`), start the app on port 5050, then run `node browser-smoke.cjs`. Set `BROWSER_CHANNEL=msedge` to use installed Edge instead of bundled Chromium. Test data is synthetic. Workspace and feedback requests exercise the local server and the test deletes its workspace afterward. Set `BASE_URL` only to a dedicated test instance.
