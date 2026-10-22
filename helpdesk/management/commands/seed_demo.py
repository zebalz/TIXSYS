"""Fills the help desk with fake staff, tickets and history for testing and demos.

    python manage.py seed_demo

Everything it makes is marked as demo data, and `clear_demo` removes it.
No real names or work data are used."""

import math
import random
import secrets
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from helpdesk import search, services
from helpdesk.bootstrap import ensure_defaults
from helpdesk.models import Board, Category, Note, Resource, Status, Ticket, TicketEvent, User

# Added by the demo, removed again by clear_demo if no real ticket uses them.
DEMO_CATEGORIES = [("Data request", "Database", 85), ("Intranet site", "Intranet", 86)]

STAFF = [
    # username, first, last, role, specialty board, zoom
    ("demo.director", "Dana", "Whitfield", User.SUPERVISOR, None, ""),
    ("demo.marcus", "Marcus", "Bell", User.TECHNICIAN, None, "https://zoom.us/j/5550101001"),
    ("demo.priya", "Priya", "Nair", User.TECHNICIAN, None, "https://zoom.us/j/5550101002"),
    ("demo.tomas", "Tomás", "Rivera", User.DEVELOPER, "Database", ""),
    ("demo.kevin", "Kevin", "Osei", User.DEVELOPER, "Database", ""),
    ("demo.lena", "Lena", "Park", User.DEVELOPER, "Intranet", ""),
]

PEOPLE = [
    ("Angela Torres", "Finance, 3rd floor", "x4120"),
    ("Brian Cho", "Records office", "x4188"),
    ("Carmen Diaz", "Front desk", "x4001"),
    ("Derek Johnson", "Annex, room 104", "x4310"),
    ("Elena Petrova", "HR suite", "x4255"),
    ("Frank Nguyen", "Warehouse", "(555) 010-2231"),
    ("Grace Kim", "Main building, 2nd floor", "x4212"),
    ("Hector Ramirez", "Planning, room 210", "x4277"),
    ("Irene Walsh", "Legal, 4th floor", "x4402"),
    ("Jamal Carter", "Facilities", "(555) 010-2290"),
    ("Karen O'Neil", "Finance, 3rd floor", "x4133"),
    ("Luis Mendoza", "Permits counter", "x4019"),
    ("Monica Shah", "Main building, 2nd floor", "x4220"),
    ("Nathan Brooks", "Training room", "x4350"),
    ("Olivia Grant", "Director's office", "x4500"),
    ("Paul Herrera", "Annex, room 112", "x4318"),
    ("Rosa Alvarez", "Records office", "x4191"),
    ("Sam Patel", "Planning, room 214", "x4281"),
]

# category, board, priority, description, (discussion question, employee answer) or None, internal note or None, resolution
ISSUES = [
    (
        "Password or sign-in",
        None,
        "high",
        "Locked out of my computer after changing my password\nIt says my account is locked. I changed my password on Friday and now nothing works.",
        None,
        None,
        "Unlocked your account and reset the password. Windows will ask you to choose a new one when you sign in.",
    ),
    (
        "Password or sign-in",
        None,
        "medium",
        "Need my sign-in app reset, I got a new phone\nThe old phone is gone so I can't approve sign-ins anymore.",
        ("Do you still have your old phone number?", "Yes, same number, just a new phone."),
        None,
        "Reset your sign-in method. You set up the app on the new phone while we were on the call.",
    ),
    (
        "Email and Outlook",
        None,
        "medium",
        "Outlook keeps asking for my password\nA box pops up every few minutes since this morning, even after I type it in.",
        None,
        "Saved credentials were stale after the password change. Cleared them in Credential Manager.",
        "Cleared old saved passwords and signed you back into Outlook. The prompt should be gone.",
    ),
    (
        "Email and Outlook",
        None,
        "low",
        "Shared mailbox doesn't show up in Outlook\nI was added to the Permits shared mailbox yesterday but I can't see it.",
        None,
        None,
        "Added the shared mailbox to your Outlook. It can take a few minutes to fill in after a restart.",
    ),
    (
        "Printer or scanner",
        None,
        "medium",
        "Printer on the 2nd floor jams on every job\nIt jams on the first page. We have a lot to print for tomorrow.",
        None,
        None,
        "Removed a torn sheet stuck behind the rear door and cleaned the rollers. Test pages print fine.",
    ),
    (
        "Printer or scanner",
        None,
        "low",
        "Can't find the new color printer\nIt isn't in my list of printers. Room 210.",
        None,
        None,
        "Added the color printer to your computer and made it your default.",
    ),
    (
        "Printer or scanner",
        None,
        "medium",
        "Scanner sends emails to the wrong address\nScan-to-email goes to my old address.",
        ("Which scanner are you using, the one by the front desk?", "Yes, the big one by the front desk."),
        None,
        "Updated your address in the scanner's address book.",
    ),
    (
        "Computer or hardware",
        None,
        "medium",
        "Second monitor stopped working\nIt says no signal. I didn't move anything.",
        None,
        "Cable was bent at the connector.",
        "Replaced the monitor cable. Both screens work.",
    ),
    (
        "Computer or hardware",
        None,
        "low",
        "Laptop battery only lasts about an hour\nIt used to last all day.",
        ("Is it a Dell or HP laptop? There's a sticker on the bottom.", "Dell, model Latitude 5420."),
        "Battery health at 41%. Ordered replacement.",
        "Replaced the battery. Health shows 100% now.",
    ),
    (
        "Computer or hardware",
        None,
        "high",
        "Computer won't turn on\nPressing the power button does nothing. I have a deadline today.",
        None,
        None,
        "Power supply had failed. Swapped in a loaner computer with your files restored.",
    ),
    (
        "Software or app",
        None,
        "low",
        "Need Adobe Acrobat Pro to edit PDFs\nMy manager approved it.",
        None,
        None,
        "Installed Acrobat Pro. Find it in the Start menu.",
    ),
    (
        "Software or app",
        None,
        "medium",
        "Teams crashes when I share my screen\nIt happens in every meeting when I click Share.",
        None,
        "Display driver was two years old.",
        "Updated Teams and the display driver. Screen sharing works.",
    ),
    (
        "Software or app",
        None,
        "low",
        "Please install the Zoom add-in for Outlook",
        None,
        None,
        "Installed the Zoom add-in. You'll see a Zoom button when you create a meeting.",
    ),
    (
        "Network, Wi-Fi or VPN",
        None,
        "high",
        "VPN won't connect from home\nIt gets stuck on 'connecting' and times out.",
        ("Are you on home Wi-Fi or a hotspot?", "Home Wi-Fi."),
        None,
        "Reinstalled the VPN profile. You connected fine while we were on the phone.",
    ),
    (
        "Network, Wi-Fi or VPN",
        None,
        "medium",
        "Wi-Fi keeps dropping in the big conference room\nIt drops every 10 minutes or so during meetings.",
        None,
        "Access point in the conference room keeps rebooting. Probably the power supply.",
        "Replaced the conference room access point. No drops since.",
    ),
    (
        "Phone or voicemail",
        None,
        "low",
        "Voicemail light stays on\nI listened to everything but the light won't go off.",
        None,
        None,
        "Reset the message light on your phone.",
    ),
    (
        "New employee setup",
        None,
        "medium",
        "New hire starting Monday: Jordan Lee, Finance\nNeeds a laptop, email, and access to the finance share.",
        None,
        "Finance share access approved by Angela.",
        "Account, laptop and phone are ready. The sign-in sheet went to the manager.",
    ),
    (
        "Something else",
        None,
        "low",
        "Training room projector says no signal\nThe laptop is plugged in but nothing shows on the wall.",
        None,
        None,
        "Switched the projector to the right input (HDMI 2). Added a label on the remote.",
    ),
    (
        "Data request",
        "Database",
        "medium",
        "Data request: active permits for the Q3 board report\nNeed a list of all active permits with issue date and type, by the 15th.",
        ("Do you need expired permits from Q3 too, or only active?", "Only active ones, thanks."),
        "Pulled from the permits database, filtered to status Active.",
        "Sent the report to you as a spreadsheet by email.",
    ),
    (
        "Data request",
        "Database",
        "high",
        "Duplicate records in case search\nSome cases show up two or three times in the search results.",
        None,
        "The search view joins the contacts table twice. Fixing the query.",
        "Fixed the search. Each case shows once now.",
    ),
    (
        "Data request",
        "Database",
        "medium",
        "Data request: monthly overtime totals by department",
        None,
        None,
        "Sent the overtime totals for the last 12 months.",
    ),
    (
        "Intranet site",
        "Intranet",
        "medium",
        "Staff directory on the intranet shows old phone numbers\nSeveral extensions changed after the move.",
        None,
        "Directory reads from an old export. Switched it to the current list.",
        "Updated the directory. New extensions show now.",
    ),
    (
        "Intranet site",
        "Intranet",
        "high",
        "Intranet shows an error after this morning's update\nThe home page says something went wrong.",
        None,
        "App pool crashed after deploy. Rolled back config change.",
        "Fixed the intranet error. The home page loads again.",
    ),
    (
        "Intranet site",
        "Intranet",
        "low",
        "Please add the new holiday calendar to the intranet",
        None,
        None,
        "Posted the holiday calendar on the intranet home page.",
    ),
]


# The story the demo data tells (so the Reports page has something real to show):
# - Mondays are busiest, Fridays quieter; a few portal tickets arrive at night and on weekends.
# - More and more people use the portal instead of calling (about 15% at the start, about 75% now).
# - Tickets get fixed faster over time.
# - One bad Tuesday about six weeks ago: an email outage brought a pile of tickets in one morning.
WEEKDAY_WEIGHT = [1.35, 1.15, 1.0, 0.95, 0.75]
OFFICE_HOUR_WEIGHT = {8: 3, 9: 6, 10: 6, 11: 5, 12: 2, 13: 4, 14: 5, 15: 4, 16: 2}
AFTER_HOURS = {6: 1, 7: 2, 17: 2, 18: 2, 19: 2, 20: 2, 21: 1, 22: 1}
NOT_PORTAL = [(Ticket.PHONE, 60), (Ticket.WALKUP, 20), (Ticket.TEXT, 12), (Ticket.EMAIL, 8)]
OUTAGE_ISSUE = (
    "Email and Outlook",
    None,
    "high",
    "Outlook won't connect this morning\nIt says it's trying to connect and my email isn't coming in.",
    None,
    "Mail server certificate expired overnight. Renewed it at 10:40.",
    "The email server is fixed. Close and reopen Outlook and your email will catch up.",
)
# Minutes from "resolution started" to "fixed": quick, same day, next day, a few days.
FIX_BUCKETS = [(20, 90), (60, 300), (240, 1500), (1500, 3000), (3000, 7000)]
FIX_ODDS_EARLY = [0.14, 0.24, 0.30, 0.19, 0.13]
FIX_ODDS_LATE = [0.36, 0.34, 0.18, 0.08, 0.04]


def weighted(rng, pairs):
    total = sum(w for _, w in pairs)
    pick = rng.uniform(0, total)
    for value, w in pairs:
        pick -= w
        if pick <= 0:
            return value
    return pairs[-1][0]


def portal_share(progress):
    """Share of tickets from the portal; progress runs 0 (oldest week) to 1 (this week)."""
    return 0.12 + 0.68 / (1 + math.exp(-(progress - 0.68) * 10))


class Command(BaseCommand):
    help = "Add fake staff and tickets for testing and demos."

    def add_arguments(self, parser):
        parser.add_argument("--weeks", type=int, default=26, help="How many weeks of history to make (default 26).")
        parser.add_argument("--per-week", type=float, default=12, help="Average tickets per week (default 12).")
        parser.add_argument("--seed", type=int, default=7)
        parser.add_argument(
            "--password", default="", help="Password for the demo accounts. Leave out to get a new random one."
        )

    @transaction.atomic
    def handle(self, *args, **opts):
        rng = random.Random(opts["seed"])  # only shapes fake demo data  # nosec B311
        # A fresh random password each run, so the demo accounts can't be guessed from this code.
        password = opts["password"] or "demo-" + secrets.token_urlsafe(9)
        org = ensure_defaults()
        if org.name == "Your Organization":
            org.name = "Demo Organization"
            org.help_phone = org.help_phone or "x4000"
            org.save()

        boards = {"Help Desk": org.default_board()}
        for name, desc in [("Database", "Data requests and database work"), ("Intranet", "Intranet site and back end")]:
            boards[name], _ = Board.objects.get_or_create(
                organization=org, name=name, defaults={"description": desc, "order": 20}
            )

        staff = {}
        for username, first, last, role, specialty, zoom in STAFF:
            user, _created = User.objects.get_or_create(username=username, defaults={"organization": org})
            user.first_name, user.last_name, user.role = first, last, role
            user.email = f"{username.replace('demo.', '')}@example.org"
            user.organization = org
            user.zoom_link = zoom
            user.specialty = boards.get(specialty) if specialty else None
            user.set_password(password)
            user.save()
            staff[username] = user
        techs = [staff["demo.marcus"], staff["demo.priya"]]
        devs_by_board = {
            "Database": [staff["demo.tomas"], staff["demo.kevin"]],
            "Intranet": [staff["demo.lena"]],
        }

        # Demo-only categories that send tickets straight to the developers' boards.
        for name, board_name, order in DEMO_CATEGORIES:
            Category.objects.get_or_create(
                organization=org, name=name, defaults={"board": boards[board_name], "order": order}
            )

        status = {s.kind: s for s in Status.objects.filter(organization=org).order_by("-order")}
        categories = {c.name: c for c in Category.objects.filter(organization=org)}

        now = timezone.now()
        plan = self.schedule(rng, now, opts["weeks"], opts["per_week"])

        # Still being worked on: the newest few haven't been picked up yet, some from this
        # past week are in progress or waiting on the employee, and a few older ones are stuck.
        statuses_for = {}
        for i in range(max(0, len(plan) - 4), len(plan)):
            statuses_for[i] = "new"
        recent = [i for i, item in enumerate(plan) if (now - item["created"]).days <= 7 and i not in statuses_for]
        recent_kinds = ["assigned", "assigned", "in_progress", "in_progress", "waiting", "waiting"]
        for i, kind in zip(rng.sample(recent, min(6, len(recent))), recent_kinds, strict=False):
            statuses_for[i] = kind
        older = [i for i, item in enumerate(plan) if 10 <= (now - item["created"]).days <= 35]
        for i, kind in zip(rng.sample(older, min(3, len(older))), ["waiting", "in_progress", "assigned"], strict=False):
            statuses_for[i] = kind

        made_ids = []
        for i, item in enumerate(plan):
            ticket = self.make_ticket(
                rng, org, item, statuses_for.get(i, "done"), now, boards, techs, devs_by_board, status, categories
            )
            made_ids.append(ticket.pk)

        for start in range(0, len(made_ids), 200):
            search.refresh(made_ids[start : start + 200])

        if not Resource.objects.filter(organization=org).exists():
            for order, (title, body) in enumerate(SAMPLE_ARTICLES, start=1):
                Resource.objects.create(organization=org, title=title, body=body, order=order * 10)

        self.stdout.write(
            self.style.SUCCESS(f"Added {len(made_ids)} demo tickets and {len(STAFF)} demo staff accounts.")
        )
        self.stdout.write("Demo staff sign-ins (all use the same password):")
        for username, first, last, role, _specialty, _zoom in STAFF:
            self.stdout.write(f"  {username:15} {first} {last} — {dict(User.ROLE_CHOICES)[role]}")
        self.stdout.write(f"  Password: {password}")
        self.stdout.write("Remove all demo data (and these accounts) later with: ./tixsys clear-demo")

    # ------------------------------------------------------------------ plan
    def schedule(self, rng, now, weeks, per_week):
        """When each ticket arrives, how, and what it's about. Oldest first."""
        local_now = timezone.localtime(now)
        this_monday = (local_now - timedelta(days=local_now.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        first_monday = this_monday - timedelta(weeks=weeks - 1)
        outage_week = max(0, weeks - 7)
        per_day = per_week / sum(WEEKDAY_WEIGHT)
        plan = []

        def add(when, issue, source):
            if when < local_now - timedelta(minutes=20):
                plan.append({"created": when, "issue": issue, "source": source})

        for w in range(weeks):
            progress = w / max(weeks - 1, 1)
            share = portal_share(progress)
            monday = first_monday + timedelta(weeks=w)
            for d in range(7):
                day = monday + timedelta(days=d)
                if d < 5:
                    count = self.poisson(rng, per_day * WEEKDAY_WEIGHT[d] * rng.uniform(0.8, 1.2))
                else:
                    count = 1 if rng.random() < share * 0.45 else 0
                for _ in range(count):
                    on_portal = d >= 5 or rng.random() < share
                    source = Ticket.PORTAL if on_portal else weighted(rng, NOT_PORTAL)
                    if on_portal and (d >= 5 or rng.random() < 0.08 + share * 0.12):
                        hour = weighted(rng, list(AFTER_HOURS.items()) if d < 5 else [(h, 1) for h in range(9, 21)])
                    else:
                        hour = weighted(rng, list(OFFICE_HOUR_WEIGHT.items()))
                    when = day.replace(hour=hour, minute=rng.randrange(60))
                    add(when, ISSUES[rng.randrange(len(ISSUES))], source)
                if w == outage_week and d == 1:
                    for _ in range(12):
                        source = Ticket.PORTAL if rng.random() < share else weighted(rng, NOT_PORTAL)
                        when = day.replace(
                            hour=weighted(rng, [(7, 2), (8, 5), (9, 4), (10, 2)]), minute=rng.randrange(60)
                        )
                        add(when, OUTAGE_ISSUE, source)
        plan.sort(key=lambda item: item["created"])
        for item in plan:
            item["progress"] = (item["created"] - first_monday).total_seconds() / max(
                (local_now - first_monday).total_seconds(), 1
            )
        return plan

    @staticmethod
    def poisson(rng, mean):
        # Knuth's method; fine for small means.
        limit, k, p = math.exp(-mean), 0, 1.0
        while True:
            p *= rng.random()
            if p <= limit:
                return k
            k += 1

    # ---------------------------------------------------------------- ticket
    def make_ticket(self, rng, org, item, plan, now, boards, techs, devs_by_board, status, categories):
        cat_name, board_name, priority, description, question, internal, resolution = item["issue"]
        person, location, phone = PEOPLE[rng.randrange(len(PEOPLE))]
        email = person.lower().replace("'", "").replace(" ", ".") + "@example.org"
        created = item["created"]
        source = item["source"]
        outage = item["issue"] is OUTAGE_ISSUE

        # How long the fix takes, decided up front. Tickets that wouldn't be fixed yet stay open.
        progress = item["progress"]
        odds = [early + (late - early) * progress for early, late in zip(FIX_ODDS_EARLY, FIX_ODDS_LATE, strict=True)]
        bucket = weighted(rng, list(zip(FIX_BUCKETS, odds, strict=True)))
        fix_minutes = rng.randint(60, 240) if outage else rng.randint(*bucket)
        if plan == "done" and created + timedelta(minutes=fix_minutes + 240) > now:
            plan = "in_progress"

        board = boards[board_name] if board_name else boards["Help Desk"]
        pool = devs_by_board.get(board_name, techs)
        assignee = rng.choice(pool) if plan != "new" else None
        logged_by = rng.choice(techs) if source != Ticket.PORTAL else None

        ticket = services.create_ticket(
            org,
            requester_name=person,
            requester_email=email,
            requester_phone=phone,
            location=location,
            category=categories.get(cat_name),
            board=board,
            priority=priority,
            source=source,
            created_by=logged_by,
            description=description,
            is_demo=True,
            created_at=created,
        )
        t = created
        latest = now - timedelta(minutes=5)

        def step(minutes_min, minutes_max):
            # Move the clock forward, but never past a few minutes ago.
            nonlocal t
            t = min(t + timedelta(minutes=rng.randint(minutes_min, minutes_max)), max(t, latest))
            return t

        def event(actor, field, old, new):
            TicketEvent.objects.create(
                ticket=ticket,
                actor=actor,
                actor_name=actor.display_name if actor else ticket.requester_name,
                action=TicketEvent.CHANGED,
                field=field,
                old_value=old,
                new_value=new,
                created_at=t,
            )

        def note(kind, body, author=None):
            Note.objects.create(
                ticket=ticket,
                kind=kind,
                body=body,
                author=author,
                author_name=author.display_name if author else ticket.requester_name,
                from_requester=author is None,
                created_at=t,
            )
            TicketEvent.objects.create(
                ticket=ticket,
                actor=author,
                actor_name=author.display_name if author else ticket.requester_name,
                action=TicketEvent.REPLY if author is None else TicketEvent.NOTE,
                detail="replied" if author is None else f"added a {kind} note",
                created_at=t,
            )

        current = ticket.status
        if assignee:
            step(3, 40)
            ticket.assignee = assignee
            event(assignee, "assignee", "", assignee.display_name)
            event(assignee, "status", current.name, status["assigned"].name)
            current = status["assigned"]
            if plan in ("in_progress", "waiting", "done"):
                step(5, 60)
                event(assignee, "status", current.name, status["in_progress"].name)
                current = status["in_progress"]
            if question and plan in ("waiting", "done", "in_progress"):
                step(5, 40)
                note(Note.DISCUSSION, question[0], assignee)
                if plan == "waiting":
                    event(assignee, "status", current.name, status["waiting"].name)
                    current = status["waiting"]
                else:
                    step(10, 120)
                    note(Note.DISCUSSION, question[1])
            if plan == "waiting" and not question:
                step(5, 60)
                note(Note.DISCUSSION, "Can you tell me when you're at your desk today so I can take a look?", assignee)
                event(assignee, "status", current.name, status["waiting"].name)
                current = status["waiting"]
            if internal and plan in ("in_progress", "done"):
                step(5, 60)
                note(Note.INTERNAL, internal, assignee)
            if plan == "done":
                t = max(t, min(created + timedelta(minutes=fix_minutes), latest))
                note(Note.RESOLUTION, resolution, assignee)
                event(assignee, "status", current.name, status["resolved"].name)
                current = status["resolved"]
                ticket.resolved_at = t
                if (now - t).days > 7 and rng.random() < 0.7:
                    t = t + timedelta(days=rng.randint(2, 5))
                    event(assignee, "status", current.name, status["closed"].name)
                    current = status["closed"]
        ticket.status = current
        ticket.updated_at = min(t, now)
        ticket.save()
        return ticket


SAMPLE_ARTICLES = [
    (
        "Reset your password",
        (
            "If you know your current password:\n1. Press Ctrl + Alt + Delete.\n2. Select Change a password.\n"
            "3. Type your old password, then your new one twice.\n\nIf you're locked out, submit a ticket or call the help desk."
        ),
    ),
    (
        "Connect to the VPN from home",
        (
            "1. Make sure you're connected to the internet.\n2. Open the VPN app from the Start menu.\n"
            "3. Sign in with your work account.\n\nIf it stays on 'connecting', restart your computer and try again before submitting a ticket."
        ),
    ),
    (
        "Add a printer",
        (
            "1. Open Settings, then Bluetooth & devices, then Printers & scanners.\n2. Select Add device.\n"
            "3. Pick the printer with your room or floor in its name.\n\nDon't see it? Submit a ticket with your room number."
        ),
    ),
    (
        "Before you submit a ticket",
        (
            "Restart your computer. It fixes more problems than you'd think.\n\n"
            "If you see an error message, take a screenshot (Windows key + Shift + S) and attach it to your ticket."
        ),
    ),
]
