# TIXSYS handoff

Read this first in any new session. Updated October 22, 2026.

## The project

TIXSYS is a self-hosted IT help desk Zeb is building for his workplace, to cut down the constant help desk calls. Employees submit tickets on a portal with no account; staff work them in a ConnectWise-style workspace. Zeb plans to show it to the IT director. If the director says no, Zeb keeps using the old intranet ticket system and uses TIXSYS's text export to copy tickets into it.

- Spec: Claude Doc "Help Desk Platform — v1 Spec", https://claude.ai/artifact/WVV4ZCDJBoAFMMFT3iPX6R
- Repo: https://github.com/zebalz/TIXSYS, branch `main`. The Claude GitHub App is installed on this repo only; pushing works from Claude sessions.
- **The repo is still public.** Zeb wants it private. Claude can't change visibility through the proxy; Zeb must do it: repo, Settings, General, Danger Zone, Change visibility, Make private.
- Staff at Zeb's work: 2 technicians, 3 developers (a SQL engineer, a systems engineer, an ASP.NET developer who handle data requests and the intranet), a supervisor (IT director), and Zeb as administrator.

## How to work with Zeb

- Plain, clear language. No metaphors. Step-by-step instructions for anything he has to do ("walk me through it like I'm 3"). Say what he needs to do, what you need from him, and what he needs to decide.
- Confirm before starting big code changes, and tell him before a big step so he can raise the effort setting. He said "GO" for the batch that is now finished; new work needs a new go-ahead.
- Design he wants: minimal, pastel and pastel gradients, ChatGPT-like simplicity, nothing that looks like stock AI. Fonts only Arial, Arial Narrow, Helvetica. Rounded corners. See-through glass layers with things visible behind. Real "liquid glass" only where it's real (it is: refraction in Chrome/Edge), never faked. 3D for one showpiece chart only; other charts flat and each a different type.

## Stack

Django 5.2.18 (LTS), Python 3.13, PostgreSQL 16 (full-text search), Caddy 2 (HTTPS), Docker Compose, gunicorn 26.2.0 (run with `--no-control-socket`), whitenoise, pyotp, qrcode, Pillow 13.0.0, argon2-cffi. No JavaScript libraries; no outside services except the HTTPS certificate and optional SMTP email. One Django app, `helpdesk`. Single organization in v1, but every record has an organization ID.

## Code map

| Path | What it is |
|---|---|
| `config/settings.py` | Everything from env vars. Strict security settings, `REQUIRE_AUTHENTICATOR_FOR` (admin default), DB cache with 100k entries (lockout counters) |
| `helpdesk/models.py` | Organization, Board, Category, Status, User (role: technician/developer/supervisor/admin), Ticket (number from 1001, `token` = private link, `search_vector`), Note (discussion/internal/resolution), Attachment, TicketEvent (history), Resource (how-to), SavedSearch, SecurityEvent |
| `helpdesk/services.py` | Every ticket change goes through here (history, status rules, emails, search refresh) |
| `helpdesk/search.py` | Search parser (Gmail/Jira style) to PostgreSQL tsquery; only letters/digits reach tsquery. `VERSION` constant |
| `helpdesk/reports.py` | All Reports numbers; charts drawn by `static/js/charts.js` |
| `helpdesk/views/portal.py`, `staff.py`, `auth.py` | Employee portal, staff workspace, sign-in/TOTP/account |
| `helpdesk/middleware.py` | CSP and security headers, org, forces authenticator setup by role |
| `helpdesk/safe.py` | Input guards and URL converters (`token`, `num`) |
| `helpdesk/throttle.py` | Sign-in lockout and portal rate-limit counters (in the DB cache). `one_at_a_time(key)` is a PostgreSQL advisory lock: every counter change uses it, and `sign_in_turn(username)` wraps each whole sign-in attempt (check, password or code, count) |
| `helpdesk/totp.py` | Authenticator codes. `verify_for_user` claims the code's time step with one conditional UPDATE (no reuse, even at the same moment) |
| `helpdesk/uploads.py` | Images/PDF only by magic bytes, size caps, decompression-bomb guard |
| `helpdesk/admin.py` | Settings area at `/staff/settings/` (admin only), read-only security log |
| `helpdesk/export.py` | Plain-text export of tickets |
| `helpdesk/management/commands/` | `bootstrap`, `seed_demo`, `clear_demo`, `unlock_login`, `reset_authenticator`, `rebuild_search` |
| `helpdesk/tests/` | `test_flows.py` (31), `test_security.py` (47), `test_search.py` (14). `SimultaneousRequestTests` uses real threads (TransactionTestCase) to test requests arriving at the same moment |
| `static/css/tixsys.css`, `static/js/` | One stylesheet. `glass.js` (refraction), `charts.js`, `common.js`, `staff.js` (alerts), `portal.js` |
| `docker-compose.yml`, `Dockerfile`, `docker/`, `tixsys` | The bundle and the `./tixsys` helper (setup, start, stop, demo, clear-demo, backup, restore, update, test, password, unlock, reset-authenticator) |
| `README.md`, `SECURITY.md`, `docs/how-it-works.md`, `docs/security-scan-results.md` | User guide, security case for the director, plain explanation with a 5-minute demo script, scan results |

## What's done

- Portal: submit with category chips, screenshots, remembered details; ticket number and private link; reply on the link; My tickets (signed cookie); Remote help with an "Open Quick Assist" button (`ms-quick-assist:`), picture guide, techs' Zoom links; how-to articles; branding from Settings.
- Workspace: quick views, filters, search with saved searches, ticket page with three note types and full history, Assign to me, reset private link, Log a call, chime + desktop alerts (15 s poll), export as text (one ticket or the whole list), Reports.
- Reports: KPI tiles, 3D tickets-per-day (CSS 3D, drag/arrow keys, flat calendar view, busiest-day label), portal vs phone (hero % + weekly share + channel bar), opened vs resolved (difference chart), punch card (weekday × hour with office hours), time to fix (median + middle-half band, log scale), flow (channel → board → fixed/open), bar lists, oldest open tickets, 4/12/26-week range, a table view for every chart. Colors checked with a colorblind-safety validator.
- Security: strict CSP (no inline scripts or styles anywhere), Argon2, lockouts and rate limits, TOTP required for admins (no replay), security log, upload checks, sandboxed file responses, input guards, hardened containers (non-root, read-only, no capabilities, no-new-privileges), deploy checklist clean.
- Internal security review (October 22): done by a fresh session that hadn't written the code, against the app running under gunicorn with 3 workers. Found and fixed 4 problems, each proved by doing it and each with a test that failed before the fix: simultaneous sign-in guesses got past the lockout (12-15 checked before a 10-failure lock; counters lost counts); one authenticator code could sign in twice at the same moment (2 of 4 tries); counter keys over 255 characters never counted; the logo was served by its file name's type (a picture named logo.pdf went out as a PDF). Full write-up in `docs/security-scan-results.md`. SECURITY.md was corrected where it said more than was true: the app's database account is a PostgreSQL superuser (not just "owner"), checks don't run automatically "on every update", and the server-compromise steps were wrong (changing `POSTGRES_PASSWORD` in `.env` breaks the DB connection; authenticator secrets and private links also need resetting).
- Demo data: about 320 tickets over 26 weeks with a story (busy Mondays, a one-morning email outage about 6 weeks back, portal share rising from about 30% to 90%, faster fixes). Demo accounts: `demo.director` (supervisor), `demo.marcus`, `demo.priya` (technicians), `demo.tomas`, `demo.kevin`, `demo.lena` (developers). A new random password is printed each run (`--password` sets one).
- Last check (October 22): 92 tests pass; pip-audit, Bandit, `check --deploy`, Ruff, ShellCheck all clean; `makemigrations --check` shows no changes.

## Not verified yet

- **The Docker bundle has never been run.** The Claude workspace can't download Docker Hub images (the proxy answers 403 for registry-1.docker.io; `dockerd` itself starts), so everything was tested without Docker. The first real run is Zeb's Mac. Watch for problems from the container hardening (`read_only`, `cap_drop`, `no-new-privileges`), the startup script, and Caddy. If something fails, get the exact error (`./tixsys logs app`, `./tixsys logs caddy`).

## Next steps

1. Zeb: make the repo private (steps above).
2. Zeb: try it on his MacBook with Docker Desktop (README, "Try it on your Mac": `./tixsys setup http://localhost`, `./tixsys demo`, open http://localhost). He asked to be walked through it one step at a time.
3. Zeb decides where it runs for real: a VM at work (an Ubuntu VM on the internal network is the safest and most likely option; ask the systems engineer) or a rented cloud server (about $6 to $12 a month). From the review, for a work VM: (a) an internal-only name (like `helpdesk.corp.local`) can't get a free public HTTPS certificate, so Caddy would need the company's certificate or `tls internal`; (b) if the company puts a load balancer or proxy in front, every visitor would look like one address, and the per-network limits would then apply to everyone at once. Ask the systems engineer about both.
4. Import from the old intranet ticket system: waiting on Zeb's photos or a sample of how it stores tickets.
5. Decisions for Zeb from the review (none started; each needs his go-ahead):
   - Least-privilege database account: the app currently connects as the PostgreSQL superuser. A limited account is the biggest remaining hardening. Best done after the first Mac run works, since it changes the Docker setup.
   - Shared computers: the portal remembers tickets and typed details per browser. Option: a "This is a shared computer" choice or a "Forget me on this computer" button. Today SECURITY.md says to use a private window.
   - A total upload cap (limits are per network address today). Only matters if the server is reachable from the internet.
   - Automatic test runs on GitHub (CI with a PostgreSQL service) on every push, so the checks really run on every change.
6. Later ideas, not promised: "skins" (Zeb mentioned); Microsoft (Azure) sign-in is probably a "hell no" at his work for employees.

## Answer already given about access

GitHub only stores the code. It can't run TIXSYS (GitHub Pages only serves plain pages; this needs a database and sign-in). To see it: Docker Desktop on his Mac at `http://localhost` (private to his Mac). For other people to use it: a server (work VM or cloud).

## Working in the Claude workspace

- No Docker. Run natively: `pip install --break-system-packages -r requirements.txt`; PostgreSQL 16. In the last workspace the data lived at `/var/tmp/tixsys-pg` with the socket in `/var/tmp` (initdb under `/tmp` failed on permissions). Create it with `mkdir -p /var/tmp/tixsys-pg && chown postgres:postgres /var/tmp/tixsys-pg && su postgres -c "/usr/lib/postgresql/16/bin/initdb -D /var/tmp/tixsys-pg -A trust -U postgres"`. Start: `su postgres -c "/usr/lib/postgresql/16/bin/pg_ctl -D /var/tmp/tixsys-pg -l /var/tmp/tixsys-pg/log -o '-k /var/tmp -p 5432' -w start"`. After a container restart, delete a stale `/var/tmp/tixsys-pg/postmaster.pid` first.
- To test like the server does (several workers at once), run gunicorn with `--workers 3 --no-control-socket` after `collectstatic`, with `DEBUG=0`, and fire requests from threads. The race scripts used in the review sent 30-40 sign-ins at once with a shared CSRF token.
- Env for local runs: `SECRET_KEY=<anything> TIXSYS_DOMAIN=http://127.0.0.1:8000 POSTGRES_HOST=/var/tmp POSTGRES_USER=postgres POSTGRES_DB=tixsys DEBUG=1`. Then `migrate`, `createcachetable`, `bootstrap`, `seed_demo --password <pw>`, `runserver`.
- Tests: `python3 manage.py test helpdesk --noinput`. Use a different `POSTGRES_DB` (e.g. `tixsys_ci`) if anything else might be running tests at the same time.
- Screenshots: Playwright with the preinstalled Chromium. Use viewport shots for review (full-page shots show sticky bars over content).
- Don't kill the dev server with `pkill -f` (it matched and killed the shell); save the PID and kill that.
- Only one migration (`0001_initial`) exists and nothing is deployed, so model changes can still regenerate it. Once anything is deployed, add normal migrations instead.

## Gotchas

- CSP blocks inline `style=` attributes and `<style>`. Use classes, or set styles from JS through `element.style` (allowed). A test fails if a page has inline styles or scripts.
- `Referrer-Policy: no-referrer` broke CSRF (Origin: null). Keep `same-origin`.
- Chrome refraction: an element's outer box-shadow shifts the `backdrop-filter: url()` refraction; `.liquid-on` keeps only inset shadows. Refraction is skipped on large elements.
- `Ticket.save()` never writes `search_vector`; only `search.refresh()` does. When `search_document()` changes, bump `search.VERSION`; servers re-index on start (`rebuild_search --auto`).
- `str.isdigit()` accepts "²"; use `safe.number()` for ids from addresses and forms.
- Sign-in code that checks the lockout must stay inside `throttle.sign_in_turn(username)`, and new counters must go through `throttle.count()`, or simultaneous requests slip past the limits again. The locks are session-level PostgreSQL advisory locks (not tied to a transaction), released in `finally`.
- Tests that commit (TransactionTestCase) also commit cache counters; clear the cache in `setUp` and `tearDown` so later tests aren't locked out.
- Stop hook: commit and push before ending a turn. Commit trailer lines are given by the session reminder.
