# Security scan results

Run on October 21, 2026 (Pacific time) against the code in this repository. Re-run them any time with the commands below; a clean result means "nothing known found", not "nothing could ever be wrong" (see [SECURITY.md](../SECURITY.md), Honest limits).

| Check | Tool | Result |
|---|---|---|
| Automated tests, including 39 security tests | Django test runner | **84 passed, 0 failed** |
| Known vulnerabilities in every Python package the app uses, including indirect ones | pip-audit 2.10.1 (PyPI advisory database) | **No known vulnerabilities found** |
| Security problems in the app's code | Bandit 1.9.4 | **0 issues** (5 lines marked as reviewed, explained below) |
| Django's production deployment checklist | `manage.py check --deploy --fail-level WARNING`, Django 5.2.18 | **No issues** (3 deliberately handled, explained below) |
| Code mistakes and style | Ruff 0.16.9 | **All checks passed** |
| Shell scripts (`tixsys`, backup, startup) | ShellCheck 0.11.0 | **No findings** |
| Unsafe ways of putting text into pages from JavaScript (`innerHTML`, `eval`) | search of `static/js/` | **None used** |

## What was fixed because of these checks

- **Pillow** (reads uploaded images) 12.3.0 had 24 published vulnerabilities. Upgraded to 13.0.0, which fixes all of them.
- Odd values typed into addresses and filters (a superscript ², a 30-digit number, an invisible "NUL" character) could make a page fail with a server error instead of "not found". Every such value is now cleaned or refused first, and the tests cover each one.
- A ticket's search entry could be erased when the ticket was assigned or changed. Fixed at the source (ordinary saves never touch the search entry), with tests.
- Junk sign-in attempts with many different usernames could have pushed a real lockout counter out of the shared cache. The cache now holds 100,000 entries.
- The demo accounts used one fixed password written in the code. Each `./tixsys demo` run now makes a new random password and prints it.

## Lines marked as reviewed

Bandit flags things that look risky by pattern. These were checked and are fine:

| Where | Bandit's concern | Why it's fine |
|---|---|---|
| `admin.py`, `views/auth.py`, `reset_authenticator.py` | "Hard-coded password: empty string" | It erases an authenticator secret; nothing is set to a password. |
| `models.py` | "Hard-coded password: password_changed" | It's the name of a security-log entry. |
| `seed_demo.py` | "Not a secure random generator" | It only shapes fake demo data. The demo password uses the secure generator. |

## Deliberately handled deployment checks

| Django's note | How it's handled |
|---|---|
| Redirect all HTTP to HTTPS (`SECURE_SSL_REDIRECT`) | Caddy, the web server in front, already sends every `http://` request to `https://`. |
| HSTS for all subdomains, and HSTS preload | Left off so this app can't force HTTPS onto other sites on your domain. HSTS itself is on (30 days). |

## Commands

From the project folder (inside the app container, `./tixsys test` runs the tests):

```
python manage.py test helpdesk
pip-audit -r requirements.txt
bandit -r helpdesk config -x helpdesk/tests,helpdesk/migrations
SECRET_KEY=<a long random value> TIXSYS_DOMAIN=help.example.org python manage.py check --deploy --fail-level WARNING
ruff check .
shellcheck tixsys docker/*.sh
```
