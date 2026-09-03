---
name: drive-browser
description: Drive the running TAP web app in a real headless browser (Playwright + Chromium) to verify client-side behavior an HTTP fetch can't see — JS rendering, viewer-local time localization (spec-web-time-display), Tabulator formatters, HTMX swaps. Reaches auth-walled pages by injecting a minted Django session cookie; sets the browser timezone so local-time rendering is deterministic. Use to confirm a web change actually renders in the browser, not just in tests.
allowed-tools: Read Bash Bash(scripts/dc *) Bash(curl *)
argument-hint: [url-or-page-path to verify, e.g. /administrivia/batches]
---

# Drive the TAP web app in a browser

You are verifying a web change **as a browser meets it** — after the JavaScript
runs. A `curl` of a TAP page only proves the server-rendered HTML; it cannot see
Tabulator formatting, HTMX-swapped fragments, or the client-side local-time pass
(`localtime.js`, `spec-web-time-display`) that rewrites `<time>` elements to the
viewer's zone. This skill launches a headless Chromium against the running dev
server, reaches auth-walled pages via an injected session cookie, and dumps what
actually rendered.

Two committed helpers live next to this file:

- **`drive.py`** — the Playwright driver. Injects a `sessionid` cookie, sets the
  browser's IANA timezone (`--tz`), loads a URL, and prints the
  `text`/`title`/`datetime` of every matched element (default selector `time`)
  plus any console errors and an optional full-page screenshot.
- **`mint_session.py`** — mints a real Django DB session for a user and prints
  its key, so you skip the Google OIDC login wall.

## When to use

- Confirming a template / panel / JS change **renders** (blank frame = failure).
- Verifying viewer-local time display: render as two zones and watch the display
  shift while the UTC `title`/`datetime` stay fixed (the `spec-web-time-display`
  proof).
- Any "does this actually work in the app" check the test suite can't make
  because the behavior is client-side.

Not for: pure server logic (a test or `curl` is faster), or anything that needs
a real logged-in Google identity (this uses a synthetic session).

## One-time setup (idempotent)

No browser tooling ships with the repo. Create a persistent venv **outside** the
worktree (Chromium is ~150 MB; never commit it) and install Playwright + its
Chromium. This block is a no-op once the venv exists, so it is safe to run every
invocation:

```bash
VENV="$HOME/.cache/tap-playwright/venv"
if [ ! -x "$VENV/bin/python" ]; then
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install --quiet --upgrade pip playwright
  "$VENV/bin/python" -m playwright install chromium
fi
```

## Procedure

**Step 1 — app up + this session's web port.** The port is per-worktree in
`.env.local` (`WEB_PORT`). Confirm the server answers:

```bash
PORT=$(grep -E '^WEB_PORT=' .env.local | cut -d= -f2)
curl -sf -o /dev/null -w "login %{http_code}\n" "http://localhost:$PORT/auth/login/"
```

If it doesn't answer, `scripts/dc up -d web` and wait for it.

**Step 2 — mint a session** (skip for public pages like `/auth/login/`):

```bash
SKEY=$(scripts/dc exec -T web uv run python manage.py shell \
       < tap_web/skills/drive-browser/mint_session.py \
       | grep SESSIONKEY | cut -d= -f2)
echo "session=$SKEY"
```

Default user is `admin`; override with `-e TAP_DRIVE_USER=<username>` on the
`exec` (e.g. `tap_viewer` to test a `grid.read`-only actor).

**Step 3 — drive it.** Point the venv python at `drive.py`:

```bash
VENV="$HOME/.cache/tap-playwright/venv"
PORT=$(grep -E '^WEB_PORT=' .env.local | cut -d= -f2)
"$VENV/bin/python" tap_web/skills/drive-browser/drive.py \
  --session "$SKEY" \
  --tz America/New_York \
  --shot /tmp/drive.png \
  --url "http://localhost:$PORT/administrivia/batches"
```

Then **look at the screenshot** with the Read tool — a blank frame is a failed
launch, not a pass. `console_errors=[]` in the output means nothing threw.

**Verify by presence, never by absence.** A `--select` for error markup that matches zero
elements is not a pass — on 2026-09-02 a graph-panel fix was reported green on exactly that
check while the panel was still throwing (`NameError` → `UnboundLocalError`; the peer session read
the server log). Select for the thing that must be *there* (rows, nodes, a value) and count it.
For a panel that mounts through HTMX, the surest check is the fragment itself:

```bash
SKEY=…; PORT=…; PANEL=$(curl -s -b "sessionid=$SKEY" "http://localhost:$PORT/<page>" | grep -o 'hx-get="/panel/[^"]*"' | head -1 | sed 's/hx-get="//;s/"$//')
curl -s -b "sessionid=$SKEY" "http://localhost:$PORT$PANEL" > /tmp/fragment.html
python3 -c "import re,html,json; s=open('/tmp/fragment.html').read(); m=re.search(r'<script id=\"tap-graph-nodes-[^\"]*\"[^>]*>(.*?)</script>', s, re.S); print('nodes', len(json.loads(html.unescape(m.group(1)))) if m else 'NO DATA SCRIPT')"
scripts/dc logs --since 1m web | grep -c '\[<site token>\]'     # the log site the failure path uses; 0 after the fetch
```

A data script with N > 0 and zero failure-site log lines after the fetch is the pass; "no error
selector matched" is not.

## Worked example — verifying viewer-local time (spec-web-time-display)

Render the same page in two zones. The **display + zone abbrev shift**; the
**UTC `title` and `datetime` attribute do not** — that's the proof localization
is genuine and non-destructive, not a hardcoded string:

```bash
for TZ in America/New_York America/Los_Angeles; do
  "$VENV/bin/python" tap_web/skills/drive-browser/drive.py \
    --session "$SKEY" --tz "$TZ" \
    --url "http://localhost:$PORT/administrivia/batches"
done
# NY  -> text '… 16:00 EDT', title '… 20:00:48 UTC'
# LA  -> text '… 13:00 PDT', title '… 20:00:48 UTC'   (same instant, shifted display)
```

The **server path** (a `<time data-tap-localtime>` emitted by the `tap_localtime`
filter / `timefmt.render_local_time`, then localized by `localtime.js`'s DOM
pass) is visible on an object viewer, e.g. `/object/batch/<slug>--<uuid>/`: the
raw HTML body reads `… UTC` (the no-JS fallback) and the browser rewrites it to
local. The **client path** (`panel-table.js` → `TapLocalTime.formatEl`) is the
Tabulator tables under `/administrivia/…`.

## Cleanup

- The venv persists across sessions by design — leave it.
- Screenshots go to `/tmp` (or your scratchpad); disposable.
- The minted session is a real DB row. It's harmless on a local dev stack, but
  to tidy up you can flush sessions:
  `scripts/dc exec -T web uv run python manage.py clearsessions` (removes only
  expired sessions) or delete the row explicitly in a shell if you want it gone
  immediately.

## Failure modes

- **`playwright install chromium` slow/failing** — it downloads from Microsoft's
  CDN (~150 MB) the first time; re-run, it resumes/caches. Nothing lands in the
  repo.
- **`mint_session.py refuses to run: settings.DEBUG is False`** — the guard
  fired: the target isn't a dev system. This is by design (the mint is DEV
  ONLY). Point it at a dev stack, or don't bypass auth on a hardened box.
- **Page loads but is the login wall** — the session cookie didn't take. Check
  `mint_session.py`'s `_auth_user_backend` still matches
  `settings.AUTHENTICATION_BACKENDS`, that the user exists, and that the cookie
  `domain`/`--host` is `localhost`.
- **`match_count[time]=0` on a page you expected timestamps** — the data may be
  empty, or the timestamps render through Tabulator only after the fragment
  loads; bump `--wait-ms`, or confirm rows exist. Parameterized viewer pages
  (`/object/<type>/<id>/`) are not in `/__nav-index.json` — navigate to them by
  built URL, not by crawling the index.
- **Blank screenshot / timeout** — the server wasn't up or the URL 404s; verify
  Step 1 and the path.
- **`match_count[<error selector>]=0` read as a pass** — the failure may render with
  different markup (the graph panel's error block is not `.tap-panel-error`), or not render at
  all. See *Verify by presence* in Step 3.
- **The dev server is mid-reload.** A Python change restarts runserver; a fetch during the
  restart returns the pre-change behaviour or a connection error. `scripts/dc logs --since 1m web |
  grep -i 'Starting development server'` and fetch after it.

## References

- [`tap_web/specs/spec-web-time-display.md`](../../specs/spec-web-time-display.md) — the local-time convention this skill was built to verify.
- [`spec-dev-playwright-refresh.md`](../../../specs/spec-dev-playwright-refresh.md) — related browser-driving notes.
