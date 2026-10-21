# TIXSYS

An IT help desk you host yourself. Employees use one web page to submit tickets, get remote help, and check on their tickets. Staff work every ticket from one queue, and every change is recorded.

No outside services. The only outside connections are the free HTTPS certificate and, if you turn it on, email.

## What's in v1

**Employee portal** (no account needed)
- Submit a ticket: name, email, phone or extension, location, category, description, screenshots.
- Each ticket gets a number and a private link to check status and reply.
- Get remote help: Quick Assist steps and each tech's Zoom link.
- My tickets: tickets sent from that browser. With email on, employees can get links to all their tickets.
- How-to articles that the administrator edits.

**Staff workspace** (at `/staff/`)
- Boards (Help Desk plus any others you add), statuses, priorities, categories.
- Ticket list with quick views (All open, Mine, Unassigned, My board) and filters.
- Ticket page with three note types: Discussion (employee sees it), Internal (staff only), Resolution (employee sees it and the ticket is resolved).
- Full history of every change: who, what, when.
- Log a call: open a ticket for someone who called, texted or walked up.
- New-ticket alerts: a chime and a desktop notification while the workspace is open.
- Reports (supervisors and the administrator): open tickets by board, status and assignee; opened and resolved per week; average time to resolve; oldest open tickets.
- Settings (administrator only, at `/staff/settings/`): staff accounts, roles, boards, categories, statuses, how-to articles, name, logo and colors.

**Roles**: Technician, Developer (a technician with a specialty board), Supervisor (also reassigns anyone's tickets and sees reports), Administrator (everything, plus settings).

**Security**: HTTPS only; staff passwords plus an optional authenticator-app code; failed sign-ins are slowed down, then locked; the public form is rate-limited, has a spam trap, and can be limited to your email domain; private ticket links use long random codes; attachments are checked to be real images or PDFs with a size cap; automatic nightly backup.

## Put it on a server

You need a small Linux server (Ubuntu 24.04 works) with at least 1 GB of memory, and ideally a domain name pointed at it. Run these on the server:

1. Install Docker:
   ```
   curl -fsSL https://get.docker.com | sudo sh
   ```
2. Download TIXSYS:
   ```
   git clone https://github.com/zebalz/tixsys.git
   cd tixsys
   ```
3. Set it up. It asks for the web address, creates the settings file with fresh passwords, starts everything, then asks you to create your administrator account:
   ```
   sudo ./tixsys setup
   ```
4. Open the address it prints. Staff sign in at `/staff/`.

No domain yet? At the address prompt, type `http://` and the server's IP address. It works, but without HTTPS, so use fake data only until you add a domain.

## Load fake data for testing and demos

```
sudo ./tixsys demo
```

This adds about 56 fake tickets and six fake staff accounts (usernames start with `demo.`; the command prints the shared password). Remove them later, keeping anything real:

```
sudo ./tixsys clear-demo
```

## Everyday commands

Run `./tixsys help` for the full list. The common ones:

| Command | What it does |
|---|---|
| `sudo ./tixsys start` / `stop` / `restart` | Start, stop, or restart the help desk |
| `sudo ./tixsys logs app` | Show the app's recent log |
| `sudo ./tixsys password <username>` | Set a new password for a staff account |
| `sudo ./tixsys unlock <username>` | Unlock someone after too many failed sign-ins |
| `sudo ./tixsys backup` | Save everything to one file in `backups/` |
| `sudo ./tixsys update` | Back up, download the newest version, restart |

Add staff accounts in Settings, then Staff accounts, then Add staff account.

## Backups and moving to another server

A backup runs every night and keeps the newest 14 in the `backups/` folder. Copy that folder somewhere else now and then, so a dead server doesn't take the backups with it.

To move to another server:

1. On the old server: `sudo ./tixsys backup` and copy the file it makes to the new server.
2. On the new server, after steps 1 and 2 of "Put it on a server": `sudo ./tixsys restore <that file>`

The backup file holds every ticket and the server's passwords, so keep it private.

## Turn on email

Email is off until you fill in the `EMAIL_` lines in `.env` with your mail provider's SMTP details, then run `sudo ./tixsys restart`. With email on, employees get their ticket link and updates by email, and staff get new-ticket emails (each person can turn those off under My account).

## Not in v1

Email-to-ticket, Microsoft sign-in, response-time targets and automation rules, asset inventory, time tracking, extra per-board fields for developer specialties, and several organizations in one install (every record already carries an organization, so the data is ready for it).

## For developers

Python 3.13, Django 5.2, PostgreSQL 16, Caddy, Docker Compose. App code is in `helpdesk/`, page templates in `templates/`, styles and scripts in `static/`.

Run the checks inside the running app: `sudo ./tixsys test`.

Run it locally without Docker (needs a local PostgreSQL):
```
pip install -r requirements.txt
export DEBUG=1 POSTGRES_HOST=localhost POSTGRES_USER=postgres POSTGRES_PASSWORD=... POSTGRES_DB=tixsys
python manage.py migrate && python manage.py createcachetable && python manage.py seed_demo
python manage.py runserver
```

The font (Hanken Grotesk) is served from this server under the SIL Open Font License; the license file is in `static/fonts/`.
