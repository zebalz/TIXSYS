"""Security checks. Each test name says what it proves; SECURITY.md lists them by control.

Run with:  python manage.py test helpdesk
"""

import io
import os
import secrets
import struct
import subprocess
import sys
import threading
import zlib
from pathlib import Path

import pyotp
from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import Client, TransactionTestCase, override_settings
from django.urls import reverse

from helpdesk import services, throttle, totp
from helpdesk.bootstrap import ensure_defaults
from helpdesk.models import Attachment, Note, SecurityEvent, Ticket, User
from helpdesk.tests.test_flows import Base, old_stamp, png_bytes

BASE_DIR = Path(settings.BASE_DIR)


def png_with_size(width, height):
    """A tiny file whose header claims a huge picture (a "decompression bomb")."""

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00" * 64))
        + chunk(b"IEND", b"")
    )


def run_with_production_settings(code, extra_env=None):
    """Runs Python in a fresh process with production-style settings (no DEBUG, real domain)."""
    env = {k: v for k, v in os.environ.items() if k not in ("DEBUG", "TIXSYS_DOMAIN")}
    env.update(
        {
            "SECRET_KEY": secrets.token_urlsafe(50),  # a fresh random key, like ./tixsys setup makes
            "TIXSYS_DOMAIN": "help.example.org",
            "DJANGO_SETTINGS_MODULE": "config.settings",
        }
    )
    env.update(extra_env or {})
    return subprocess.run(
        [sys.executable, "-c", code], cwd=BASE_DIR, env=env, capture_output=True, text=True, timeout=120, check=False
    )


class AccessControlTests(Base):
    def test_every_staff_page_needs_sign_in(self):
        ticket = self.new_ticket()
        att = Attachment.objects.create(
            ticket=ticket,
            file=SimpleUploadedFile("a.png", png_bytes()),
            original_name="a.png",
            content_type="image/png",
            size=10,
        )
        urls = [
            reverse("staff:tickets"),
            reverse("staff:log_call"),
            reverse("staff:ticket", args=[ticket.number]),
            reverse("staff:ticket_update", args=[ticket.number]),
            reverse("staff:ticket_take", args=[ticket.number]),
            reverse("staff:ticket_note", args=[ticket.number]),
            reverse("staff:reset_link", args=[ticket.number]),
            reverse("staff:attachment", args=[att.pk]),
            reverse("staff:reports"),
            reverse("staff:poll"),
            reverse("staff:export_text"),
            reverse("staff:save_search"),
            reverse("staff:delete_search", args=[1]),
            reverse("staff:account"),
            reverse("staff:password"),
            reverse("staff:authenticator"),
            "/staff/settings/",
            "/staff/settings/helpdesk/user/",
            "/staff/settings/helpdesk/securityevent/",
        ]
        for url in urls:
            for method in ("get", "post"):
                response = getattr(self.client, method)(url)
                self.assertIn(
                    response.status_code, (302, 405), f"{method.upper()} {url} answered {response.status_code}"
                )
                if response.status_code == 302:
                    self.assertIn("login/", response["Location"], url)

    def test_technician_cannot_open_reports_or_settings(self):
        self.login(self.tech)
        self.assertEqual(self.client.get(reverse("staff:reports")).status_code, 403)
        response = self.client.get("/staff/settings/")
        self.assertIn(response.status_code, (302, 403))
        if response.status_code == 302:
            self.assertEqual(self.client.get(response["Location"]).status_code, 403)

    def test_administrator_must_set_up_authenticator_first(self):
        admin = self.make_user("admin2", User.ADMIN)
        self.login(admin)
        for url in (reverse("staff:tickets"), reverse("staff:reports"), "/staff/settings/"):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302, url)
            self.assertEqual(response["Location"], "/staff/account/authenticator/?required=1")
        page = self.client.get("/staff/account/authenticator/?required=1")
        self.assertContains(page, "authenticator", status_code=200)

    def test_administrator_cannot_turn_authenticator_off(self):
        self.login(self.admin)
        response = self.client.post(reverse("staff:authenticator"), {"password": "Correct-Horse-9"})
        self.assertEqual(response.status_code, 200)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.totp_enabled)

    @override_settings(REQUIRE_AUTHENTICATOR_FOR="all")
    def test_authenticator_can_be_required_for_everyone(self):
        self.login(self.tech)
        response = self.client.get(reverse("staff:tickets"))
        self.assertEqual(response["Location"], "/staff/account/authenticator/?required=1")

    def test_logout_needs_a_form_post(self):
        self.login(self.tech)
        self.assertEqual(self.client.get(reverse("staff:logout")).status_code, 405)
        self.client.post(reverse("staff:logout"))
        self.assertNotIn("_auth_user_id", self.client.session)


class EmployeePrivacyTests(Base):
    def test_private_links_are_long_and_random(self):
        a, b = self.new_ticket(), self.new_ticket()
        self.assertGreaterEqual(len(a.token), 43)  # 256 bits of randomness
        self.assertNotEqual(a.token, b.token)

    def test_guessing_a_link_finds_nothing(self):
        ticket = self.new_ticket()
        for guess in (
            ticket.token[:-1] + ("A" if ticket.token[-1] != "A" else "B"),
            "1001",
            str(ticket.number),
            "a" * 43,
        ):
            self.assertEqual(self.client.get(f"/t/{guess}/").status_code, 404, guess)

    def test_reset_link_turns_off_the_old_one(self):
        ticket = self.new_ticket()
        old = ticket.token
        self.login(self.tech)
        self.client.post(reverse("staff:reset_link", args=[ticket.number]))
        ticket.refresh_from_db()
        self.assertNotEqual(ticket.token, old)
        self.client.logout()
        self.assertEqual(self.client.get(f"/t/{old}/").status_code, 404)
        self.assertEqual(self.client.get(f"/t/{ticket.token}/").status_code, 200)
        self.assertTrue(SecurityEvent.objects.filter(kind=SecurityEvent.LINK_RESET).exists())

    def test_one_ticket_link_cannot_open_another_tickets_file(self):
        mine = self.new_ticket()
        theirs = self.new_ticket(files=[SimpleUploadedFile("secret.png", png_bytes(), content_type="image/png")])
        att = theirs.attachments.get()
        self.assertEqual(self.client.get(f"/t/{theirs.token}/files/{att.pk}/").status_code, 200)
        self.assertEqual(self.client.get(f"/t/{mine.token}/files/{att.pk}/").status_code, 404)

    def test_internal_notes_and_files_stay_internal(self):
        ticket = self.new_ticket()
        services.add_note(
            ticket,
            self.tech,
            Note.INTERNAL,
            "Server password is in the vault",
            files=[SimpleUploadedFile("internal.png", png_bytes(), content_type="image/png")],
        )
        att = ticket.attachments.get()
        page = self.client.get(f"/t/{ticket.token}/")
        self.assertNotContains(page, "vault")
        self.assertNotContains(page, "internal.png")
        self.assertEqual(self.client.get(f"/t/{ticket.token}/files/{att.pk}/").status_code, 404)

    def test_my_tickets_cookie_is_signed_and_hidden_from_scripts(self):
        response = self.submit()
        cookie = response.cookies["tixsys_mine"]
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], "Lax")
        ticket = Ticket.objects.get()
        self.assertContains(self.client.get("/my-tickets/"), ticket.token)
        # A cookie someone edits by hand (to list another person's ticket) is ignored.
        other = self.new_ticket(description="Someone else's problem")
        self.client.cookies["tixsys_mine"] = other.token
        page = self.client.get("/my-tickets/")
        self.assertNotContains(page, other.token)
        self.assertNotContains(page, ticket.token)

    def test_portal_pages_are_never_cached(self):
        ticket = self.new_ticket()
        response = self.client.get(f"/t/{ticket.token}/")
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertEqual(response["Referrer-Policy"], "same-origin")


class InputHandlingTests(Base):
    def test_html_in_tickets_is_shown_as_text_not_run(self):
        evil = '<script>alert("x")</script><img src=x onerror=alert(1)>'
        self.submit(name=evil, description=evil + "\nmore", location=evil)
        ticket = Ticket.objects.get()
        self.login(self.tech)
        for url in (reverse("staff:ticket", args=[ticket.number]), reverse("staff:tickets"), f"/t/{ticket.token}/"):
            body = self.client.get(url).content.decode()
            self.assertNotIn("<script>alert", body, url)
            self.assertNotIn("<img src=x", body, url)
            self.assertIn("&lt;script&gt;", body, url)

    def test_strange_search_text_never_breaks_anything(self):
        self.new_ticket(description="Printer jam on floor 2")
        self.login(self.tech)
        nasty = [
            "'; DROP TABLE helpdesk_ticket; --",
            "printer' OR '1'='1",
            "a & b | c ! d <-> e :* (",
            '"unclosed phrase',
            "status:",
            "-",
            "--",
            "OR OR OR",
            "opened:9999-99-99",
            "opened:<-5d",
            "opened:2026-13-45..yesterday",
            "requester:\x00abc",
            "nul\x00byte",
            "\u202e\u0000\ufeff",
            "#99999999999999999999999",
            "assignee:" + "x" * 500,
            "ü" * 5000,
            "\\",
            "%",
            "_",
            "*:*",
        ]
        for q in nasty:
            response = self.client.get(reverse("staff:tickets"), {"q": q})
            self.assertEqual(response.status_code, 200, repr(q))
            response = self.client.get(reverse("staff:export_text"), {"q": q})
            self.assertEqual(response.status_code, 200, repr(q))
        self.assertEqual(self.client.get(reverse("staff:tickets"), {"q": "printer"}).content.count(b"Printer jam"), 1)

    def test_strange_filter_values_never_break_anything(self):
        self.login(self.boss)
        odd = ["abc", "-1", "²", "١", "99999999999999999999999", "1;DROP", "\x00", "", " "]
        for value in odd:
            for key in ("board", "status", "assignee", "priority", "sort", "view", "page"):
                response = self.client.get(reverse("staff:tickets"), {key: value})
                self.assertEqual(response.status_code, 200, f"{key}={value!r}")
            self.assertEqual(self.client.get(reverse("staff:reports"), {"weeks": value}).status_code, 200, repr(value))
            self.assertEqual(self.client.get(reverse("staff:poll"), {"after": value}).status_code, 200, repr(value))

    def test_out_of_range_numbers_in_addresses_are_not_found(self):
        self.login(self.tech)
        huge = "9" * 30
        for url in (f"/staff/tickets/{huge}/", f"/staff/files/{huge}/", f"/how-to/{huge}/"):
            self.assertEqual(self.client.get(url).status_code, 404, url)
        self.assertEqual(self.client.get("/t/%00/").status_code, 404)
        self.assertEqual(self.client.get("/t/" + "a" * 5000 + "/").status_code, 404)

    def test_saving_a_search_cleans_what_it_stores(self):
        self.login(self.tech)
        response = self.client.post(
            reverse("staff:save_search"),
            {
                "name": "Mine\x00\r\nSet-Cookie: x=1",
                "query_string": "q=printer\r\nLocation: https://evil.example&view=all",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("/staff/?"))
        self.assertNotIn("\n", response["Location"])
        saved = self.tech.saved_searches.get()
        self.assertNotIn("\x00", saved.name)
        self.assertNotIn("\n", saved.query_string)

    def test_sign_in_never_sends_people_to_another_site(self):
        for target in ("https://evil.example/", "//evil.example/", "/\\evil.example/", "javascript:alert(1)"):
            client = Client()
            response = client.post("/staff/login/", {"username": "tech", "password": "Correct-Horse-9", "next": target})
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response["Location"], "/staff/", target)

    def test_very_long_rate_limit_keys_still_count(self):
        # A valid email address can be 300 characters; its counter must still count.
        key = "portal-submit:email:" + "a" * 300 + "@example.org"
        self.assertEqual([throttle.count(key, 60) for _ in range(3)], [1, 2, 3])

    def test_unknown_host_names_are_refused(self):
        response = self.client.get("/", HTTP_HOST="evil.example")
        self.assertEqual(response.status_code, 400)


class FileUploadTests(Base):
    def upload(self, name, content, content_type="image/png"):
        return self.submit(files=SimpleUploadedFile(name, content, content_type=content_type))

    def test_only_real_images_and_pdfs_are_accepted(self):
        bad = [
            ("page.html", b"<html><script>alert(1)</script></html>", "text/html"),
            ("fake.png", b"<html><script>alert(1)</script></html>", "image/png"),
            (
                "drawing.svg",
                b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
                "image/svg+xml",
            ),
            ("tool.exe", b"MZ\x90\x00\x03\x00\x00\x00", "application/octet-stream"),
            ("macro.docm", b"PK\x03\x04", "application/vnd.ms-word"),
            ("real.png.exe", png_bytes(), "image/png"),
            ("photo.jpg", png_bytes(), "image/jpeg"),
        ]
        for name, content, content_type in bad:
            self.upload(name, content, content_type)
        self.assertFalse(Ticket.objects.exists())
        self.upload("screen.png", png_bytes())
        self.assertEqual(Attachment.objects.count(), 1)

    def test_decompression_bomb_is_refused(self):
        response = self.upload("bomb.png", png_with_size(30000, 30000))
        self.assertFalse(Ticket.objects.exists())
        self.assertContains(response, "too large")

    @override_settings(MAX_ATTACHMENT_MB=1)
    def test_size_limit(self):
        big = png_bytes() + b"\x00" * (1024 * 1024 + 10)
        response = self.upload("big.png", big)
        self.assertFalse(Ticket.objects.exists())
        self.assertContains(response, "larger than 1 MB")

    def test_files_are_served_safely(self):
        pdf = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"
        ticket = self.new_ticket(
            files=[
                SimpleUploadedFile("report.pdf", pdf, content_type="application/pdf"),
                SimpleUploadedFile("screen.png", png_bytes(), content_type="image/png"),
            ]
        )
        pdf_att = ticket.attachments.get(original_name="report.pdf")
        png_att = ticket.attachments.get(original_name="screen.png")
        response = self.client.get(f"/t/{ticket.token}/files/{pdf_att.pk}/")
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("attachment", response["Content-Disposition"])  # downloaded, never opened in the page
        self.assertIn("default-src 'none'", response["Content-Security-Policy"])
        self.assertIn("sandbox", response["Content-Security-Policy"])
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        response = self.client.get(f"/t/{ticket.token}/files/{png_att.pk}/")
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertTrue(pdf_att.file.name.startswith("attachments/"))
        self.assertNotIn("report", Path(pdf_att.file.name).name)  # stored under a random name

    def logo_form(self, logo):
        fields = {
            "name": self.org.name,
            "portal_title": self.org.portal_title,
            "brand_color": "#26232F",
            "header_color": "#CFC6FF",
            "help_phone": "",
            "welcome_text": "",
            "remote_help_text": "",
            "allowed_email_domain": "",
            "logo": logo,
        }
        return self.client.post(f"/staff/settings/helpdesk/organization/{self.org.pk}/change/", fields)

    def test_logo_must_be_a_real_picture(self):
        self.login(self.admin)
        # A real picture with a name that would make browsers treat it as a PDF.
        response = self.logo_form(SimpleUploadedFile("logo.pdf", png_bytes(), content_type="application/pdf"))
        self.assertEqual(response.status_code, 200)
        self.org.refresh_from_db()
        self.assertFalse(self.org.logo)
        response = self.logo_form(SimpleUploadedFile("logo.png", png_bytes(), content_type="image/png"))
        self.assertEqual(response.status_code, 302)
        self.org.refresh_from_db()
        response = self.client.get(reverse("portal:logo"))
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertIn("sandbox", response["Content-Security-Policy"])
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")

    def test_logo_is_only_served_as_a_picture(self):
        # Whatever ends up in the logo's place (an old upload, a restored backup), only a
        # real picture is ever served, with its type taken from its contents, not its name.
        self.org.logo.save("logo.pdf", ContentFile(png_bytes()), save=True)
        response = self.client.get(reverse("portal:logo"))
        self.assertEqual(response["Content-Type"], "image/png")
        self.org.logo.save("logo.png", ContentFile(b"%PDF-1.4\n1 0 obj<<>>endobj\n%%EOF"), save=True)
        self.assertEqual(self.client.get(reverse("portal:logo")).status_code, 404)


class BrowserProtectionTests(Base):
    def test_strict_content_security_policy(self):
        self.login(self.boss)
        for url in ("/", reverse("staff:tickets"), reverse("staff:reports"), "/staff/login/"):
            policy = self.client.get(url)["Content-Security-Policy"]
            directives = dict(d.strip().split(" ", 1) for d in policy.split(";"))
            self.assertEqual(directives["script-src"], "'self'", url)
            self.assertEqual(directives["style-src"], "'self'", url)
            self.assertEqual(directives["frame-ancestors"], "'none'", url)
            self.assertEqual(directives["object-src"], "'none'", url)
            self.assertNotIn("unsafe", policy, url)

    def test_no_inline_scripts_or_styles_in_pages(self):
        ticket = self.new_ticket()
        self.login(self.boss)
        pages = [
            "/",
            "/my-tickets/",
            "/remote-help/",
            "/how-to/",
            f"/t/{ticket.token}/",
            reverse("staff:tickets"),
            reverse("staff:ticket", args=[ticket.number]),
            reverse("staff:reports"),
            reverse("staff:log_call"),
            reverse("staff:account"),
        ]
        for url in pages:
            body = self.client.get(url).content.decode()
            self.assertNotIn(" style=", body, url)
            self.assertNotIn("<style", body, url)
            for chunk in body.split("<script")[1:]:
                head = chunk.split(">", 1)[0]
                self.assertTrue("src=" in head or 'type="application/json"' in head, f"inline script on {url}")

    def test_other_protective_headers(self):
        response = self.client.get("/")
        self.assertEqual(response["X-Frame-Options"], "DENY")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response["Referrer-Policy"], "same-origin")
        self.assertEqual(response["Cross-Origin-Opener-Policy"], "same-origin")
        self.assertEqual(response["Cross-Origin-Resource-Policy"], "same-origin")
        self.assertIn("camera=()", response["Permissions-Policy"])

    def test_forms_need_the_anti_forgery_token(self):
        client = Client(enforce_csrf_checks=True)
        response = client.post(
            reverse("portal:submit"), {"name": "A", "email": "a@example.org", "description": "x", "stamp": old_stamp()}
        )
        self.assertEqual(response.status_code, 403)
        response = client.post("/staff/login/", {"username": "tech", "password": "Correct-Horse-9"})
        self.assertEqual(response.status_code, 403)
        client.force_login(self.tech)
        ticket = self.new_ticket()
        response = client.post(reverse("staff:ticket_take", args=[ticket.number]))
        self.assertEqual(response.status_code, 403)
        ticket.refresh_from_db()
        self.assertIsNone(ticket.assignee)

    def test_production_settings_are_locked_down(self):
        result = run_with_production_settings(
            "import django; django.setup()\n"
            "from django.conf import settings as s\n"
            "assert not s.DEBUG\n"
            "assert s.SESSION_COOKIE_SECURE and s.CSRF_COOKIE_SECURE\n"
            "assert s.SESSION_COOKIE_HTTPONLY and s.CSRF_COOKIE_HTTPONLY\n"
            "assert s.SESSION_COOKIE_SAMESITE == 'Lax'\n"
            "assert s.SECURE_HSTS_SECONDS >= 2592000\n"
            "assert s.SECURE_PROXY_SSL_HEADER == ('HTTP_X_FORWARDED_PROTO', 'https')\n"
            "assert s.ALLOWED_HOSTS[0] == 'help.example.org'\n"
            "assert s.PASSWORD_HASHERS[0].endswith('Argon2PasswordHasher')\n"
            "print('ok')\n"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ok", result.stdout)

    def test_django_deployment_checklist_passes(self):
        result = run_with_production_settings(
            "import django, sys; django.setup()\n"
            "from django.core.management import call_command\n"
            "call_command('check', deploy=True, fail_level='WARNING')\n"
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_app_refuses_to_start_without_a_secret_key(self):
        result = run_with_production_settings("import django; django.setup()", {"SECRET_KEY": ""})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SECRET_KEY is not set", result.stderr)


class AccountSecurityTests(Base):
    def test_passwords_are_stored_with_argon2(self):
        user = User.objects.get(username="tech")
        self.assertTrue(user.password.startswith("argon2$"))
        self.assertNotIn("Correct-Horse-9", user.password)

    def test_weak_passwords_are_refused(self):
        for weak in ("password1", "12345678901", "short", "tech-tech"):
            with self.assertRaises(ValidationError, msg=weak):
                validate_password(weak, user=self.tech)
        validate_password("Mauve-Kettle-Orbit-42", user=self.tech)

    def test_sign_ins_and_failures_are_logged(self):
        self.client.post("/staff/login/", {"username": "tech", "password": "wrong-password"})
        self.client.post("/staff/login/", {"username": "tech", "password": "Correct-Horse-9"})
        kinds = list(SecurityEvent.objects.order_by("created_at").values_list("kind", "username"))
        self.assertEqual(kinds, [(SecurityEvent.LOGIN_FAILED, "tech"), (SecurityEvent.LOGIN_OK, "tech")])
        event = SecurityEvent.objects.last()
        self.assertEqual(event.ip, "127.0.0.1")

    def test_exports_are_logged(self):
        self.login(self.tech)
        self.client.get(reverse("staff:export_text"), {"q": "printer"})
        event = SecurityEvent.objects.get(kind=SecurityEvent.EXPORT)
        self.assertEqual(event.user, self.tech)
        self.assertIn("printer", event.detail)

    def test_authenticator_codes_cannot_be_replayed(self):
        code = pyotp.TOTP(self.admin_secret).now()
        for attempt in range(2):
            client = Client()
            client.post("/staff/login/", {"username": "admin", "password": "Correct-Horse-9"})
            client.post(reverse("staff:login_code"), {"code": code})
            signed_in = "_auth_user_id" in client.session
            self.assertEqual(signed_in, attempt == 0)

    def test_a_code_cannot_be_used_twice_even_by_sign_ins_at_the_same_moment(self):
        # Two sign-ins that both loaded the account before either one checked the code.
        first = User.objects.get(pk=self.admin.pk)
        second = User.objects.get(pk=self.admin.pk)
        code = pyotp.TOTP(self.admin_secret).now()
        self.assertTrue(totp.verify_for_user(first, code))
        self.assertFalse(totp.verify_for_user(second, code))

    def test_odd_characters_in_a_code_are_refused_cleanly(self):
        self.client.post("/staff/login/", {"username": "admin", "password": "Correct-Horse-9"})
        for odd in ("²²²²²²", "１２３４５６", "12 34 5"):
            response = self.client.post(reverse("staff:login_code"), {"code": odd})
            self.assertEqual(response.status_code, 200, odd)
            self.assertNotIn("_auth_user_id", self.client.session)

    def test_security_log_is_read_only(self):
        self.client.post("/staff/login/", {"username": "tech", "password": "nope"})
        event = SecurityEvent.objects.get()
        self.login(self.admin)
        self.assertEqual(self.client.get("/staff/settings/helpdesk/securityevent/").status_code, 200)
        self.assertEqual(self.client.get("/staff/settings/helpdesk/securityevent/add/").status_code, 403)
        self.client.post(f"/staff/settings/helpdesk/securityevent/{event.pk}/delete/", {"post": "yes"})
        self.assertTrue(SecurityEvent.objects.filter(pk=event.pk).exists())

    def test_lost_phone_reset_from_the_server(self):
        from django.core.management import call_command

        call_command("reset_authenticator", "admin", stdout=io.StringIO())
        self.admin.refresh_from_db()
        self.assertFalse(self.admin.totp_enabled)
        self.assertEqual(self.admin.totp_secret, "")
        self.assertTrue(SecurityEvent.objects.filter(kind=SecurityEvent.AUTHENTICATOR_RESET, username="admin").exists())
        # As an administrator, the next sign-in goes straight to setting up a new one.
        self.login(self.admin)
        self.assertEqual(
            self.client.get(reverse("staff:tickets"))["Location"], "/staff/account/authenticator/?required=1"
        )

    def test_settings_changes_are_recorded(self):
        self.login(self.admin)
        self.client.post(
            "/staff/settings/helpdesk/user/",
            {"action": "turn_off_authenticator", "_selected_action": [self.tech.pk]},
        )
        self.assertTrue(
            SecurityEvent.objects.filter(kind=SecurityEvent.AUTHENTICATOR_RESET, detail="for tech").exists()
        )


@override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
    TRUST_X_FORWARDED_FOR=False,
    LOGIN_SLOWDOWN_AFTER=100,
    LOGIN_LOCKOUT_AFTER=4,
)
class SimultaneousRequestTests(TransactionTestCase):
    """Requests that arrive at the same moment, the way they do on the server, where
    several app workers answer requests side by side. Each test starts real threads,
    each with its own database connection, and lets them all go at once."""

    def setUp(self):
        cache.clear()
        self.org = ensure_defaults()
        self.user = User.objects.create_user(
            username="racer", password="Correct-Horse-9", role=User.TECHNICIAN, organization=self.org
        )

    def tearDown(self):
        cache.clear()  # these tests commit their counters; don't leave them for other tests

    def all_at_once(self, count, work):
        """Runs work(i) for i in range(count), each in its own thread, all released together."""
        start = threading.Barrier(count)
        results = [None] * count
        errors = []

        def run(i):
            try:
                start.wait()
                results[i] = work(i)
            except Exception as e:  # noqa: BLE001 - reported by the assertion below
                errors.append(e)
            finally:
                connection.close()

        threads = [threading.Thread(target=run, args=(i,)) for i in range(count)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        return results

    def test_simultaneous_hits_on_a_rate_limit_are_all_counted(self):
        results = self.all_at_once(10, lambda i: [throttle.count("race-test", 60) for _ in range(5)])
        every_count = sorted(n for counts in results for n in counts)
        self.assertEqual(every_count, list(range(1, 51)))  # 50 hits, each counted exactly once

    def test_simultaneous_wrong_passwords_cannot_slip_past_the_lockout(self):
        def guess(i):
            return Client().post("/staff/login/", {"username": "racer", "password": f"wrong-guess-{i}"})

        self.all_at_once(8, guess)
        # Each "wrong password" log entry is a password that was really checked.
        checked = SecurityEvent.objects.filter(kind=SecurityEvent.LOGIN_FAILED, username="racer").count()
        self.assertEqual(checked, 4)  # LOGIN_LOCKOUT_AFTER; the other 4 guesses were refused unchecked
        response = Client().post("/staff/login/", {"username": "racer", "password": "Correct-Horse-9"})
        self.assertContains(response, "locked")

    def test_one_authenticator_code_signs_in_once_even_when_sent_twice_at_once(self):
        secret = pyotp.random_base32()
        self.user.totp_secret = secret
        self.user.totp_enabled = True
        self.user.save()
        clients = [Client() for _ in range(4)]
        for client in clients:
            client.post("/staff/login/", {"username": "racer", "password": "Correct-Horse-9"})
        code = pyotp.TOTP(secret).now()

        def send_code(i):
            clients[i].post(reverse("staff:login_code"), {"code": code})
            return "_auth_user_id" in clients[i].session

        self.assertEqual(sorted(self.all_at_once(4, send_code)), [False, False, False, True])
