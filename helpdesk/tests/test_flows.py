"""End-to-end checks of the main flows and the security rules.

Run with:  python manage.py test helpdesk
"""

import io
import shutil
import struct
import tempfile
import time
import zlib

import pyotp
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from helpdesk import services, throttle
from helpdesk.bootstrap import ensure_defaults
from helpdesk.forms import form_stamp
from helpdesk.models import Note, Status, Ticket, TicketEvent, User

TEMP_MEDIA = tempfile.mkdtemp(prefix="tixsys-test-media-")


def png_bytes():
    w, h = 4, 4
    raw = b"".join(b"\x00" + b"\x10\x20\x30" * w for _ in range(h))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def old_stamp(seconds=30):
    """A form stamp from `seconds` ago, so the too-fast spam check passes."""
    real = time.time
    try:
        time.time = lambda: real() - seconds
        return form_stamp()
    finally:
        time.time = real


@override_settings(
    MEDIA_ROOT=TEMP_MEDIA,
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
    TRUST_X_FORWARDED_FOR=False,
)
class Base(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEMP_MEDIA, ignore_errors=True)

    def setUp(self):
        self.org = ensure_defaults()
        self.tech = self.make_user("tech", User.TECHNICIAN)
        self.tech2 = self.make_user("tech2", User.TECHNICIAN)
        self.boss = self.make_user("boss", User.SUPERVISOR)
        self.admin = self.make_user("admin", User.ADMIN)

    def make_user(self, username, role):
        user = User.objects.create_user(username=username, password="Correct-Horse-9", role=role, organization=self.org)
        user.email = f"{username}@example.org"
        user.first_name = username.title()
        user.save()
        return user

    def submit(self, **overrides):
        data = {
            "name": "Ana Lopez",
            "email": "ana@example.org",
            "phone": "x1234",
            "location": "Room 5",
            "category": self.org.categories.first().pk,
            "description": "Printer won't print\nIt shows an error light.",
            "stamp": old_stamp(),
            "leave_blank": "",
        }
        data.update(overrides)
        return self.client.post(reverse("portal:submit"), data)

    def new_ticket(self, **kwargs):
        defaults = dict(requester_name="Ana Lopez", requester_email="ana@example.org", description="Help")
        defaults.update(kwargs)
        return services.create_ticket(self.org, **defaults)

    def login(self, user):
        self.client.force_login(user)


class PortalTests(Base):
    def test_submit_creates_numbered_ticket_with_private_link(self):
        response = self.submit(files=SimpleUploadedFile("screen.png", png_bytes(), content_type="image/png"))
        ticket = Ticket.objects.get()
        self.assertEqual(ticket.number, 1001)
        self.assertEqual(ticket.summary, "Printer won't print")
        self.assertEqual(ticket.status.kind, Status.NEW)
        self.assertEqual(ticket.board, self.org.default_board())
        self.assertGreaterEqual(len(ticket.token), 40)
        self.assertRedirects(response, reverse("portal:received", args=[ticket.token]))
        self.assertIn("tixsys_mine", response.cookies)
        att = ticket.attachments.get()
        self.assertEqual(att.content_type, "image/png")
        self.assertTrue(TicketEvent.objects.filter(ticket=ticket, action=TicketEvent.CREATED).exists())

        page = self.client.get(reverse("portal:received", args=[ticket.token]))
        self.assertContains(page, "#1001")
        mine = self.client.get(reverse("portal:my_tickets"))
        self.assertContains(mine, "Printer won&#x27;t print")

    def test_second_ticket_gets_next_number(self):
        self.submit()
        self.submit(description="Second problem")
        self.assertEqual(sorted(Ticket.objects.values_list("number", flat=True)), [1001, 1002])

    def test_spam_trap_and_too_fast_are_dropped(self):
        self.submit(leave_blank="http://spam.example")
        self.submit(stamp=form_stamp())  # submitted instantly
        self.submit(stamp="forged")
        self.assertEqual(Ticket.objects.count(), 0)

    def test_email_domain_restriction(self):
        self.org.allowed_email_domain = "example.org"
        self.org.save()
        response = self.submit(email="someone@gmail.com")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Use your work email address")
        self.assertEqual(Ticket.objects.count(), 0)

    def test_fake_image_is_rejected(self):
        response = self.submit(files=SimpleUploadedFile("evil.png", b"<script>alert(1)</script>", content_type="image/png"))
        self.assertContains(response, "isn&#x27;t an image or PDF")
        self.assertEqual(Ticket.objects.count(), 0)

    def test_html_file_is_rejected_even_named_pdf(self):
        response = self.submit(files=SimpleUploadedFile("doc.pdf", b"<html></html>", content_type="application/pdf"))
        self.assertEqual(Ticket.objects.count(), 0)
        self.assertEqual(response.status_code, 200)

    def test_rate_limit_per_network(self):
        with self.settings(PORTAL_TICKETS_PER_IP_PER_HOUR=2):
            for i in range(3):
                self.submit(description=f"Problem {i}")
        self.assertEqual(Ticket.objects.count(), 2)

    def test_wrong_token_is_404(self):
        self.new_ticket()
        self.assertEqual(self.client.get("/t/not-a-real-token/").status_code, 404)

    def test_requester_never_sees_internal_notes_or_their_files(self):
        ticket = self.new_ticket()
        services.add_note(ticket, self.tech, Note.INTERNAL, "Secret staff note")
        internal = Note.objects.get(kind=Note.INTERNAL)
        att = services.save_attachment(
            ticket, SimpleUploadedFile("x.png", png_bytes()), note=internal, uploaded_by=self.tech
        )
        services.add_note(ticket, self.tech, Note.DISCUSSION, "Visible reply")
        page = self.client.get(reverse("portal:ticket", args=[ticket.token]))
        self.assertContains(page, "Visible reply")
        self.assertNotContains(page, "Secret staff note")
        file_url = reverse("portal:attachment", args=[ticket.token, att.id])
        self.assertEqual(self.client.get(file_url).status_code, 404)
        # Staff can open it.
        self.login(self.tech)
        self.assertEqual(self.client.get(reverse("staff:attachment", args=[att.id])).status_code, 200)

    def test_reply_reopens_waiting_and_resolved_tickets(self):
        ticket = self.new_ticket(assignee=self.tech)
        services.add_note(ticket, self.tech, Note.DISCUSSION, "When are you free?", mark_waiting=True)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status.kind, Status.WAITING)
        self.client.post(reverse("portal:ticket", args=[ticket.token]), {"body": "Now", "stamp": old_stamp()})
        ticket.refresh_from_db()
        self.assertEqual(ticket.status.kind, Status.IN_PROGRESS)

        services.add_note(ticket, self.tech, Note.RESOLUTION, "Fixed the cable.")
        ticket.refresh_from_db()
        self.assertEqual(ticket.status.kind, Status.RESOLVED)
        self.assertIsNotNone(ticket.resolved_at)
        page = self.client.get(reverse("portal:ticket", args=[ticket.token]))
        self.assertContains(page, "How it was resolved")
        self.client.post(reverse("portal:ticket", args=[ticket.token]), {"body": "Broken again", "stamp": old_stamp()})
        ticket.refresh_from_db()
        self.assertEqual(ticket.status.kind, Status.IN_PROGRESS)
        self.assertIsNone(ticket.resolved_at)

    def test_closed_ticket_refuses_replies(self):
        ticket = self.new_ticket()
        services.update_ticket(ticket, self.tech, {"status": self.org.status_of_kind(Status.CLOSED)})
        response = self.client.post(reverse("portal:ticket", args=[ticket.token]), {"body": "Hello?", "stamp": old_stamp()})
        self.assertEqual(ticket.notes.count(), 0)
        self.assertContains(response, "This ticket is closed")

    @override_settings(EMAIL_ENABLED=True, EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_emails_when_turned_on(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.submit()
        subjects = [m.subject for m in mail.outbox]
        self.assertTrue(any(s.startswith("Ticket #1001 received") for s in subjects))
        self.assertTrue(any(s.startswith("New ticket #1001") for s in subjects))
        ticket = Ticket.objects.get()
        self.assertIn(ticket.token, mail.outbox[0].body)

        mail.outbox.clear()
        with self.captureOnCommitCallbacks(execute=True):
            services.add_note(ticket, self.tech, Note.INTERNAL, "staff only")
        self.assertEqual(len(mail.outbox), 0)
        with self.captureOnCommitCallbacks(execute=True):
            services.add_note(ticket, self.tech, Note.RESOLUTION, "Done")
        self.assertEqual(mail.outbox[0].to, ["ana@example.org"])

    @override_settings(EMAIL_ENABLED=True, EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_email_links_gives_same_answer_for_unknown_address(self):
        self.new_ticket()
        mail.outbox.clear()
        r1 = self.client.post(reverse("portal:my_tickets"), {"email": "ana@example.org", "stamp": old_stamp()})
        r2 = self.client.post(reverse("portal:my_tickets"), {"email": "nobody@example.org", "stamp": old_stamp()})
        self.assertContains(r1, "on their way")
        self.assertContains(r2, "on their way")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["ana@example.org"])

    def test_security_headers(self):
        response = self.client.get("/")
        self.assertIn("script-src 'self'", response["Content-Security-Policy"])
        self.assertEqual(response["Referrer-Policy"], "same-origin")
        self.assertEqual(response["X-Frame-Options"], "DENY")


class SignInTests(Base):
    def post_login(self, username="tech", password="Correct-Horse-9"):
        return self.client.post(reverse("staff:login"), {"username": username, "password": password})

    def test_staff_pages_need_sign_in(self):
        response = self.client.get(reverse("staff:tickets"))
        self.assertRedirects(response, "/staff/login/?next=/staff/")

    def test_password_sign_in(self):
        response = self.post_login()
        self.assertRedirects(response, "/staff/")

    def test_slow_down_then_lock_out(self):
        for _ in range(5):
            self.post_login(password="wrong")
        response = self.post_login()  # right password, but must wait
        self.assertContains(response, "Wait")
        self.assertNotIn("_auth_user_id", self.client.session)
        throttle.clear("login-wait:user:tech")  # pretend the wait passed
        with self.settings(LOGIN_SLOWDOWN_AFTER=100):
            for _ in range(5):
                self.post_login(password="wrong")
        response = self.post_login()
        self.assertContains(response, "locked")
        self.assertNotIn("_auth_user_id", self.client.session)
        call_command("unlock_login", "tech", stdout=io.StringIO())
        self.assertRedirects(self.post_login(), "/staff/")

    def test_authenticator_code_required_and_not_reusable(self):
        self.login(self.tech)
        self.client.get(reverse("staff:authenticator"))
        secret = self.client.session["tixsys_totp_setup"]
        code = pyotp.TOTP(secret).now()
        self.client.post(reverse("staff:authenticator"), {"code": code})
        self.tech.refresh_from_db()
        self.assertTrue(self.tech.totp_enabled)
        self.client.logout()

        response = self.post_login()
        self.assertRedirects(response, reverse("staff:login_code"))
        self.assertNotIn("_auth_user_id", self.client.session)
        response = self.client.post(reverse("staff:login_code"), {"code": "000000"})
        self.assertContains(response, "didn&#x27;t work")
        # The code used to turn it on can't be used again.
        response = self.client.post(reverse("staff:login_code"), {"code": code})
        self.assertNotIn("_auth_user_id", self.client.session)

        totp = pyotp.TOTP(secret)
        next_code = totp.at(time.time() + 30)
        response = self.client.post(reverse("staff:login_code"), {"code": next_code})
        self.assertRedirects(response, "/staff/")
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.tech.pk)

    def test_settings_area_only_for_administrator(self):
        self.login(self.tech)
        response = self.client.get("/staff/settings/")
        self.assertIn(response.status_code, (302, 403))
        if response.status_code == 302:
            self.assertEqual(self.client.get(response["Location"]).status_code, 403)
        self.login(self.admin)
        self.assertEqual(self.client.get("/staff/settings/").status_code, 200)
        self.assertEqual(self.client.get("/staff/settings/helpdesk/user/").status_code, 200)

    def test_settings_sign_in_returns_to_settings(self):
        response = self.client.get("/staff/settings/", follow=True)
        self.assertEqual(response.redirect_chain[-1][0], "/staff/login/?next=/staff/settings/")
        response = self.client.post(
            "/staff/login/", {"username": "admin", "password": "Correct-Horse-9", "next": "/staff/settings/"}
        )
        self.assertRedirects(response, "/staff/settings/")


class WorkspaceTests(Base):
    def test_ticket_list_views_and_search(self):
        mine = self.new_ticket(assignee=self.tech, description="Monitor broken")
        free = self.new_ticket(description="Keyboard sticky")
        self.login(self.tech)
        r = self.client.get(reverse("staff:tickets"), {"view": "mine"})
        self.assertContains(r, "Monitor broken")
        self.assertNotContains(r, "Keyboard sticky")
        r = self.client.get(reverse("staff:tickets"), {"view": "unassigned"})
        self.assertContains(r, "Keyboard sticky")
        r = self.client.get(reverse("staff:tickets"), {"q": f"#{free.number}"})
        self.assertContains(r, "Keyboard sticky")
        self.assertNotContains(r, "Monitor broken")
        self.assertEqual(self.client.get(reverse("staff:ticket", args=[mine.number])).status_code, 200)

    def test_assigning_moves_new_to_assigned_and_records_history(self):
        ticket = self.new_ticket()
        self.login(self.tech)
        self.client.post(reverse("staff:ticket_take", args=[ticket.number]))
        ticket.refresh_from_db()
        self.assertEqual(ticket.assignee, self.tech)
        self.assertEqual(ticket.status.kind, Status.ASSIGNED)
        fields = list(ticket.events.filter(action=TicketEvent.CHANGED).values_list("field", flat=True))
        self.assertEqual(fields, ["assignee", "status"])

    def test_only_supervisor_can_reassign_someone_elses_ticket(self):
        ticket = self.new_ticket(assignee=self.tech2)
        self.login(self.tech)
        self.client.post(reverse("staff:ticket_take", args=[ticket.number]))
        ticket.refresh_from_db()
        self.assertEqual(ticket.assignee, self.tech2)
        self.login(self.boss)
        data = {
            "summary": ticket.summary,
            "board": ticket.board_id,
            "status": ticket.status_id,
            "priority": "high",
            "category": "",
            "assignee": self.tech.pk,
        }
        self.client.post(reverse("staff:ticket_update", args=[ticket.number]), data)
        ticket.refresh_from_db()
        self.assertEqual(ticket.assignee, self.tech)
        self.assertEqual(ticket.priority, "high")

    def test_notes_and_resolution(self):
        ticket = self.new_ticket(assignee=self.tech)
        self.login(self.tech)
        self.client.post(reverse("staff:ticket_note", args=[ticket.number]), {"kind": "internal", "body": "checking"})
        self.client.post(reverse("staff:ticket_note", args=[ticket.number]), {"kind": "resolution", "body": "Replaced it"})
        ticket.refresh_from_db()
        self.assertEqual(ticket.status.kind, Status.RESOLVED)
        self.assertEqual(list(ticket.notes.values_list("kind", flat=True)), ["internal", "resolution"])

    def test_log_a_call(self):
        self.login(self.tech)
        response = self.client.post(
            reverse("staff:log_call"),
            {
                "source": "phone",
                "requester_name": "Bo Smith",
                "requester_phone": "x9",
                "requester_email": "",
                "location": "Lobby",
                "board": self.org.default_board().pk,
                "category": "",
                "priority": "medium",
                "description": "Can't log in",
                "assign_to_me": "on",
            },
        )
        ticket = Ticket.objects.get()
        self.assertRedirects(response, reverse("staff:ticket", args=[ticket.number]))
        self.assertEqual(ticket.source, "phone")
        self.assertEqual(ticket.assignee, self.tech)
        self.assertEqual(ticket.created_by, self.tech)
        self.assertEqual(ticket.status.kind, Status.ASSIGNED)

    def test_poll_reports_new_tickets(self):
        first = self.new_ticket()
        self.login(self.tech)
        data = self.client.get(reverse("staff:poll"), {"after": first.id}).json()
        self.assertEqual(data["new"], [])
        second = self.new_ticket(description="Brand new")
        data = self.client.get(reverse("staff:poll"), {"after": first.id}).json()
        self.assertEqual([t["number"] for t in data["new"]], [second.number])
        self.assertEqual(data["latest_id"], second.id)

    def test_reports_for_supervisors_only(self):
        call_command("seed_demo", tickets=30, stdout=io.StringIO())
        self.login(self.tech)
        self.assertEqual(self.client.get(reverse("staff:reports")).status_code, 403)
        self.login(self.boss)
        response = self.client.get(reverse("staff:reports"))
        self.assertContains(response, "Opened and resolved per week")
        self.assertContains(response, "Oldest open tickets")

    def test_clear_demo_keeps_real_data(self):
        real = self.new_ticket(description="Real ticket")
        call_command("seed_demo", tickets=20, stdout=io.StringIO())
        self.assertTrue(Ticket.objects.filter(is_demo=True).exists())
        call_command("clear_demo", yes=True, stdout=io.StringIO())
        self.assertEqual(list(Ticket.objects.values_list("pk", flat=True)), [real.pk])
        self.assertFalse(User.objects.filter(username__startswith="demo.").exists())
