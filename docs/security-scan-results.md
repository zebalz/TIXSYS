# Security scan results

Run on October 22, 2026 (Pacific time) against the code in this repository. Re-run them any time with the commands below; a clean result means "nothing known found", not "nothing could ever be wrong" (see [SECURITY.md](../SECURITY.md), Honest limits).

| Check | Tool | Result |
|---|---|---|
| Automated tests, including 47 security tests | Django test runner | **92 passed, 0 failed** |
| Known vulnerabilities in every Python package the app uses, including indirect ones | pip-audit 2.10.1 (PyPI advisory database) | **No known vulnerabilities found** |
| Security problems in the app's code | Bandit 1.9.4 | **0 issues** (5 lines marked as reviewed, explained below) |
| Django's production deployment checklist | `manage.py check --deploy --fail-level WARNING`, Django 5.2.18 | **No issues** (3 deliberately handled, explained below) |
| Code mistakes and style | Ruff 0.16.9 | **All checks passed** |
| Shell scripts (`tixsys`, backup, startup) | ShellCheck 0.11.0 | **No findings** |
| Unsafe ways of putting text into pages from JavaScript (`innerHTML`, `eval`) | search of `static/js/` | **None used** |

## Internal review, October 22, 2026

After the first scans, a separate review of the code tried to get around the protections instead of confirming them. It was internal, not an outside penetration test. Each problem it found was shown by actually doing it against the app running the way it runs on the server (three app workers answering requests side by side). Each one was then fixed, with a test that failed before the fix and passes after it.

### Found and fixed

| What was wrong | How it was shown | Fix | Proved by |
|---|---|---|---|
| Sign-in guesses sent at the same moment could slip past the slow-down and the lockout. | 40 wrong passwords sent at once: 12, and in a second run 15, were checked against the real password before the 10-failure lockout. With the slow-down on, 7 got through instead of 5. The failure counter also lost counts (12 recorded for 15 real failures). | Sign-in attempts for one username now take turns (a database lock), and every counter change is made one at a time. Rerun: exactly 10, and exactly 5. | `test_simultaneous_wrong_passwords_cannot_slip_past_the_lockout`, `test_simultaneous_hits_on_a_rate_limit_are_all_counted` |
| One authenticator code could sign in twice if two sign-ins sent it at the same moment. | The same code sent from two sign-ins at once: both got in, in 2 of 4 tries. | The database checks "not used yet" and records the use in one step. Rerun: 0 of 4. | `test_a_code_cannot_be_used_twice_even_by_sign_ins_at_the_same_moment`, `test_one_authenticator_code_signs_in_once_even_when_sent_twice_at_once` |
| A rate-limit counter with a very long name never counted. | A valid 242-character email address: its per-address counter stayed at 1 however many times it was used. | Long counter names are replaced by a fixed-length fingerprint (SHA-256) that always fits. | `test_very_long_rate_limit_keys_still_count` |
| The portal logo was served with the type its file name suggested. A real picture named `logo.pdf` went out as a PDF, without the sandboxed policy that attachments get. Only the administrator can upload a logo, so this was low risk. | Uploaded through Settings, then fetched from the portal. | The logo is served only if its contents are a PNG, JPG, GIF or WEBP picture, with that type and the sandboxed policy. Settings refuses anything else. | `test_logo_must_be_a_real_picture`, `test_logo_is_only_served_as_a_picture` |

Also tightened: the authenticator code box accepts only the digits 0 to 9 (look-alikes such as "²" get a clear message), and codes are compared in constant time. Proved by `test_odd_characters_in_a_code_are_refused_cleanly`.

### Checked and held up

- Opening any staff page, action or Settings page without signing in, or with a role that isn't allowed.
- Reading another employee's ticket: guessing or editing private links, editing the "My tickets" cookie, using one ticket's file address on another ticket.
- Internal notes and their files reaching employees: portal pages, file links, emails, and "Email me my links".
- Skipping the authenticator code: going straight to the workspace or Settings after the password step, or using an expired code step.
- Script injection: every place where text from a ticket, a name, a file name or an email address appears; the browser security policy; the browser scripts.
- The search box: only letters and digits ever reach the full-text search engine, whatever is typed.
- Uploads: disguised files, wrong extensions, oversized pictures, and how files are served.
- Open redirects after sign-in, unknown host names, forms sent without the anti-forgery token, and the security headers on every kind of page.
- The Docker setup and the helper scripts, by reading them. The workspace these checks ran in can't download Docker images, so the bundle itself hasn't been run yet.

### Accepted, and why

- **"Email me my links" timing.** The answer is the same whether or not the address has tickets. With email turned on, though, the request takes longer when it actually sends an email, so someone timing many tries could tell whether an address has tickets. The limit of 3 tries an hour per address keeps that slow, and what it reveals is minor.
- **Limits per network address** can be dodged by someone with many addresses. The per-account sign-in lockout still holds.
- **Shared computers, disk space on a public server, and the database's main account** are listed in [SECURITY.md](../SECURITY.md), Honest limits, with what to do about each.

## Fixed after the first scans, October 21, 2026

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
