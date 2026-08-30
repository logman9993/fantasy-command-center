# Fantasy Command Center — GitHub / Render Deployment Edition

This folder is ready to upload directly to a GitHub repository and deploy as a public Flask website.

## Repository layout

```text
app.py
requirements.txt
render.yaml
Procfile
runtime.txt
.env.example
.gitignore
README.md
self_test.py
templates/
static/
data/
```

Do **not** wrap these files inside another folder when uploading to GitHub. `app.py` should be at the repository root.

---

## 1. Create a GitHub repository

Create a new empty repository, for example:

`fantasy-command-center`

Upload **all files in this folder** to that repository.

Do not upload a real `.env` file or any API keys. `.gitignore` already excludes `.env`.

---

## 2. Deploy to Render

You can deploy either manually or from the included `render.yaml`.

### Blueprint method

1. Sign in to Render.
2. Choose **New → Blueprint**.
3. Connect your GitHub account.
4. Select the repository containing this project.
5. Render will detect `render.yaml`.
6. Create the service.

The included blueprint uses:

```text
Build command:
pip install -r requirements.txt

Start command:
gunicorn --workers 2 --threads 4 --timeout 120 --bind 0.0.0.0:$PORT app:app
```

Health check:

```text
/health
```

---

## 3. Environment variables

Render automatically provides `PORT`.

The included `render.yaml` sets:

```text
NFL_SEASON=2026
```

Optional:

```text
FANTASYPROS_API_KEY=your_key_here
```

Add the real FantasyPros key only inside Render's Environment settings. Never commit it to GitHub.

Without FantasyPros, the app continues using its 5-year production model plus Sleeper/current-player fallbacks.

---

## 4. Public URL

After deployment, Render will give you a URL similar to:

```text
https://fantasy-command-center.onrender.com
```

Anyone with that URL can access the dashboard.

Useful endpoints:

```text
/
 /health
 /api/dashboard
 /api/diagnostics
```

---

## 5. Updating the live site

After GitHub is connected to Render:

```text
edit code
→ commit
→ push to GitHub
→ Render automatically redeploys
```

No more manual ZIP deployment is required for normal updates.

---

## 6. Local Windows development

You can still run locally with:

```text
run.bat
```

or:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Then open:

```text
http://localhost:5050
```

---

## 7. Data/cache behavior

The app downloads/cache files from nflverse, Sleeper, and fallback team-stat sources.

Cloud free-tier filesystems can be ephemeral. That is okay: if cached files disappear, the app downloads them again.

For a larger public application, the next infrastructure upgrade would be PostgreSQL for persistent:

- users
- linked Sleeper teams
- saved draft boards
- roster analyses
- projections
- historical snapshots

---

## 8. Diagnostics

If any tab is incomplete, first open:

```text
https://YOUR-SITE.onrender.com/api/diagnostics
```

or use the **Data Health** tab.

It reports:

- player count per position
- nflverse source state
- Sleeper source state
- ranking source state
- analytics errors

---

## 9. Health check

Render uses:

```text
/health
```

Expected output:

```json
{
  "status": "ok",
  "app": "Fantasy Command Center",
  "version": "6.1-deploy",
  "season": 2026
}
```

---

## Security

- Keep API keys in Render environment variables.
- `.env` is ignored by Git.
- The browser never receives your FantasyPros API key because API calls happen server-side.
- Do not expose credentials inside JavaScript or templates.

