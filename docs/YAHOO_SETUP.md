# Yahoo Fantasy setup — V8.7

Yahoo's current Fantasy Sports developer program uses OAuth 2.0 and requires API access approval. V8.7 includes the browser/user OAuth flow and encrypted per-browser token storage, but it stays disabled until approved Yahoo credentials are configured in Render.

## 1. Apply for Yahoo Fantasy Sports API access

Current portal:

- https://sports.yahoo.com/developer/
- Documentation: https://sports.yahoo.com/developer/docs/

Request read access for Fantasy Sports. Yahoo's current developer portal describes an application submission, review, and approval process.

## 2. Register the callback

Use this callback for the current Render site:

`https://fantasy-command-center.onrender.com/auth/yahoo/callback`

If the public domain changes, update both Yahoo and Render to the same exact callback URL.

## 3. Add Render environment variables

Set these in Render, never GitHub:

- `YAHOO_CLIENT_ID`
- `YAHOO_CLIENT_SECRET`
- `YAHOO_REDIRECT_URI=https://fantasy-command-center.onrender.com/auth/yahoo/callback`
- `YAHOO_TOKEN_SECRET=<long-random-secret>`

A suitable token secret can be generated locally with Python:

`python -c "import secrets; print(secrets.token_urlsafe(48))"`

## 4. Connection model

When a manager clicks **Connect Yahoo**:

1. Command Center redirects the browser to Yahoo.
2. The manager signs in to Yahoo and authorizes the approved app.
3. Yahoo returns an authorization code to Command Center.
4. Render exchanges that one-time code for Yahoo OAuth tokens.
5. The tokens are encrypted before being placed in an HttpOnly, SameSite cookie in that manager's browser.
6. Command Center can then discover that manager's Yahoo NFL fantasy teams.

The Yahoo password is never sent to Command Center.

## V8.7 import

After connecting, select a Yahoo team to import its roster, supported lineup slots and up to 100 ranked free-agent candidates. The app displays a model grade using standard PPR/Half/Standard scoring, not exact custom league scoring or league-relative rankings. Unsupported slots or unmatched roster players stop the import with an explanation. Waiver-locked players are excluded.

Live Yahoo sign-in and import still need validation with approved credentials. Automated tests cover nested metadata, team ownership, empty free-agent pools and unmatched players. Use Disconnect Yahoo to clear this browser's token; revoke access in Yahoo account settings to revoke the provider authorization.
