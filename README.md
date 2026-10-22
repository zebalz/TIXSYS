# TIXSYS

An IT help desk you host yourself. Employees use one web page to submit tickets, get remote help, and check on their tickets. Staff work every ticket from one list, and every change is recorded.

No outside services. The only outside connections are the free HTTPS certificate and, if you turn it on, email.

- **[How it works](docs/how-it-works.md)**: what employees and staff do, how a ticket moves, searching, and a 5-minute demo script.
- **[Security](SECURITY.md)**: what it protects, how, and the automated checks that prove it. Latest scans: [docs/security-scan-results.md](docs/security-scan-results.md).

## What's in v1

**Employee portal** (no account needed)
- Submit a ticket: what's wrong, name, email, phone or extension, location, category, screenshots.
- Each ticket gets a number and a private link to check status and reply.
- Remote help: an "Open Quick Assist" button, a picture guide, and each tech's Zoom link.
- My tickets: tickets sent from that browser. With email on, employees can get links to all their tickets.
- How-to articles that the administrator edits.

**Staff workspace** (at `/staff/`)
- Boards (Help Desk plus any others you add), statuses, priorities, categories.
- Ticket list with quick views (All open, Mine, Unassigned, My board) and filters.
- Search every ticket and note, Gmail style: `printer status:resolved opened:<30d`, `"blue screen"`, `vpn OR wifi`, `-calendar`. Save searches to the sidebar.
- Ticket page with three note types: Discussion (employee sees it), Internal (staff only), Resolution (employee sees it and the ticket is resolved).
- Full history of every change: who, what, when.
- Log a call: open a ticket for someone who called, texted or walked up.
- New-ticket alerts: a chime and a desktop notification while the workspace is open.
- Export as text: copy one ticket, or download a whole list, to paste into another ticket system.
- Reports (supervisors and the administrator): tickets per day as a 3D chart you can turn, portal versus phone, opened versus resolved, when people ask for help, time to fix, where tickets go, open work, oldest open tickets.
- Settings (administrator only, at `/staff/settings/`): staff accounts, roles, boards, categories, statuses, how-to articles, name, logo and colors, and the security log.

**Roles**: Technician, Developer (a technician with a specialty board), Supervisor (also reassigns anyone's tickets and sees reports), Administrator (everything, plus settings).

**Security**: HTTPS only; staff passwords plus authenticator-app codes (required for the administrator); failed sign-ins slowed, then locked; spam and flood protection on the public form; private ticket links with 256-bit random codes; only real images and PDFs accepted; a strict browser security policy; a read-only security log; locked-down containers; nightly backups. Details and proof: [SECURITY.md](SECURITY.md).

## Try it on your Mac

This runs a private copy on your Mac only, at `http://localhost`. Nobody else can reach it. Use fake data.

1. Install **Docker Desktop** from docker.com (Download for Mac, Apple chip or Intel chip, whichever your Mac has). Open it once and let it finish starting. The whale icon in the menu bar means it's running.
2. Download TIXSYS: on the GitHub page for this repository, click the green **Code** button, then **Download ZIP**. Double-click the ZIP in Downloads to unzip it.
3. Open **Terminal** (press Command + Space, type Terminal, press Return) and go to the folder:
   ```
   cd ~/Downloads/TIXSYS-main
   ```
4. Set it up (the first run takes a few minutes):
   ```
   chmod +x tixsys
   ./tixsys setup http://localhost
   ```
   At the end it asks you to make your administrator account: pick a username, an email (press Return to skip) and a password.
5. Add the fake demo tickets and staff:
   ```
   ./tixsys demo
   ```
   Write down the demo password it prints.
6. Open **http://localhost** in your browser. That's the employee portal. Staff sign in at **http://localhost/staff/**:
   - `demo.director` and the demo password: the supervisor, with Reports.
   - `demo.marcus` and the demo password: a technician.
   - Your administrator account: the first sign-in walks you through adding an authenticator app on your phone (Microsoft Authenticator or Google Authenticator), because administrators must use one.
7. When you're done: `./tixsys stop`. Next time: open Docker Desktop, then `./tixsys start` from the same folder.

## Put it on a server

For other people to use it, it needs a server they can reach. You need a small Linux server (Ubuntu 24.04 works) with at least 1 GB of memory, and ideally a domain name pointed at it. Run these on the server:

1. Install Docker:
   ```
   curl -fsSL https://get.docker.com | sudo sh
   ```
2. Download TIXSYS:
   ```
   git clone https://github.com/zebalz/tixsys.git
   cd tixsys
   ```
   The repository is private, so git asks for your GitHub username and, instead of your password, a personal access token (on GitHub: your picture, Settings, Developer settings, Personal access tokens).
3. Set it up. It asks for the web address, creates the settings file with fresh passwords, starts everything, then asks you to create your administrator account:
   ```
   sudo ./tixsys setup
   ```
4. Open the address it prints. Staff sign in at `/staff/`. The administrator sets up an authenticator app at the first sign-in.

No domain yet? At the address prompt, type `http://` and the server's IP address. It works, but without HTTPS, so use fake data only until you add a domain.

Before real people use it, go through "Running it safely" in [SECURITY.md](SECURITY.md).

## Load fake data for testing and demos

```
sudo ./tixsys demo
```

This adds about 320 fake tickets over the last 26 weeks, so the reports have something to show, and six fake staff accounts (usernames start with `demo.`). Each run prints a new random password for them. Remove all of it later, keeping anything real:

```
sudo ./tixsys clear-demo
```

## Everyday commands

Run `./tixsys help` for the full list. On a Mac, leave out `sudo`.

| Command | What it does |
|---|---|
| `sudo ./tixsys start` / `stop` / `restart` | Start, stop, or restart the help desk |
| `sudo ./tixsys logs app` | Show the app's recent log |
| `sudo ./tixsys password <username>` | Set a new password for a staff account |
| `sudo ./tixsys unlock <username>` | Unlock someone after too many failed sign-ins |
| `sudo ./tixsys reset-authenticator <username>` | Turn off someone's authenticator app when they lose their phone |
| `sudo ./tixsys backup` | Save everything to one file in `backups/` |
| `sudo ./tixsys update` | Back up, download the newest version and security patches, restart |
| `sudo ./tixsys test` | Run all the automated checks |

Add staff accounts in Settings, then Staff accounts, then Add staff account.

## Backups and moving to another server

A backup runs every night and keeps the newest 14 in the `backups/` folder. Copy that folder somewhere else now and then, so a dead server doesn't take the backups with it.

To move to another server:

1. On the old server: `sudo ./tixsys backup` and copy the file it makes to the new server.
2. On the new server, after steps 1 and 2 of "Put it on a server": `sudo ./tixsys restore <that file>`

The backup file holds every ticket and the server's passwords, so keep it private.

## Turn on email

Email is off until you fill in the `EMAIL_` lines in `.env` with your mail provider's SMTP details, then run `sudo ./tixsys restart`. With email on, employees get their ticket link and updates by email, and staff get new-ticket emails (each person can turn those off under My account).

## Settings you can change in `.env`

After any change, run `sudo ./tixsys restart`.

| Setting | What it does |
|---|---|
| `REQUIRE_AUTHENTICATOR_FOR` | Who must use an authenticator app: `admin` (default), `supervisors`, `all` (recommended once everyone has one), or `none` |
| `TIME_ZONE` | Time zone for dates and reports, for example `America/Los_Angeles` |
| `BACKUP_TIME_UTC`, `BACKUP_KEEP` | When the nightly backup runs, and how many to keep |
| `MAX_ATTACHMENT_MB`, `MAX_ATTACHMENTS_PER_UPLOAD` | Upload limits (10 MB and 5 files by default) |
| `LOGIN_SLOWDOWN_AFTER`, `LOGIN_LOCKOUT_AFTER`, `LOGIN_LOCKOUT_MINUTES` | Failed sign-in limits (5, 10 and 30 by default) |

## Not in v1

Importing tickets from the old intranet ticket system (waiting on a look at how its data is stored), email-to-ticket, Microsoft sign-in, response-time targets and automation rules, asset inventory, time tracking, extra per-board fields for developer specialties, and several organizations in one install (every record already carries an organization, so the data is ready for it).

## For developers

Python 3.13, Django 5.2 (long-term support), PostgreSQL 16 with full-text search, Caddy, Docker Compose. No JavaScript libraries: the charts are plain SVG and CSS 3D in `static/js/charts.js`. App code is in `helpdesk/`, page templates in `templates/`, styles and scripts in `static/`.

Checks:
```
python manage.py test helpdesk     # 92 tests, including the security tests in helpdesk/tests/test_security.py
ruff check .
pip-audit -r requirements.txt
bandit -r helpdesk config -x helpdesk/tests,helpdesk/migrations
```

Run it without Docker (needs a local PostgreSQL 16):
```
pip install -r requirements.txt
export DEBUG=1 POSTGRES_HOST=localhost POSTGRES_USER=postgres POSTGRES_PASSWORD=... POSTGRES_DB=tixsys
python manage.py migrate && python manage.py createcachetable && python manage.py seed_demo
python manage.py runserver
```

Text uses Arial / Helvetica, which every computer already has, so no fonts are downloaded.
