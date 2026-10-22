"""Ticket search: words, phrases, OR, leaving words out, fields and dates."""

from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from helpdesk import search, services
from helpdesk.models import Board, Note, Status, Ticket
from helpdesk.tests.test_flows import Base


class SearchTests(Base):
    def setUp(self):
        super().setUp()
        self.printer = self.new_ticket(
            description="Printer jam on the second floor\nPaper stuck in tray 2", requester_name="Grace Kim"
        )
        self.vpn = self.new_ticket(description="VPN won't connect from home", requester_name="Derek Johnson")
        self.wifi = self.new_ticket(description="Wi-Fi drops in the conference room", location="Room 210")
        self.screen = self.new_ticket(description="Blue screen when printing a report")
        services.add_note(self.vpn, self.tech, Note.INTERNAL, "Reinstalled the certificate profile")
        services.update_ticket(self.vpn, self.tech, {"assignee": self.tech})

    def find(self, q, user=None):
        parsed = search.parse(q, user=user or self.tech)
        return set(search.apply(Ticket.objects.all(), parsed).values_list("number", flat=True)), parsed

    def test_words_must_all_match_and_word_forms_count(self):
        found, _ = self.find("printer jam")
        self.assertEqual(found, {self.printer.number})
        found, _ = self.find("print")  # finds "Printer" and "printing"
        self.assertEqual(found, {self.printer.number, self.screen.number})

    def test_exact_phrase(self):
        found, _ = self.find('"blue screen"')
        self.assertEqual(found, {self.screen.number})
        found, _ = self.find('"screen blue"')
        self.assertEqual(found, set())

    def test_or_and_leaving_words_out(self):
        found, _ = self.find("vpn OR wifi")
        self.assertEqual(found, {self.vpn.number, self.wifi.number})
        found, _ = self.find("print -jam")
        self.assertEqual(found, {self.screen.number})

    def test_notes_and_requester_details_are_searched(self):
        found, _ = self.find("certificate")
        self.assertEqual(found, {self.vpn.number})
        found, _ = self.find("grace")
        self.assertEqual(found, {self.printer.number})

    def test_ticket_number(self):
        found, _ = self.find(f"#{self.wifi.number}")
        self.assertEqual(found, {self.wifi.number})

    def test_fields(self):
        found, _ = self.find("assignee:me")
        self.assertEqual(found, {self.vpn.number})
        found, _ = self.find("assignee:none")
        self.assertEqual(found, {self.printer.number, self.wifi.number, self.screen.number})
        found, _ = self.find('location:"room 210"')
        self.assertEqual(found, {self.wifi.number})
        found, _ = self.find("requester:derek")
        self.assertEqual(found, {self.vpn.number})
        found, _ = self.find("status:assigned")
        self.assertEqual(found, {self.vpn.number})
        found, _ = self.find("-status:assigned")
        self.assertEqual(found, {self.printer.number, self.wifi.number, self.screen.number})
        found, _ = self.find("has:internal")
        self.assertEqual(found, {self.vpn.number})

    def test_boards_and_dates(self):
        db = Board.objects.create(organization=self.org, name="Database", order=20)
        old = self.new_ticket(description="Data request for the board report", board=db)
        Ticket.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=40))
        found, _ = self.find("board:database")
        self.assertEqual(found, {old.number})
        found, _ = self.find("opened:<7d")
        self.assertNotIn(old.number, found)
        found, _ = self.find("opened:>30d")
        self.assertEqual(found, {old.number})
        day = timezone.localdate()
        found, _ = self.find(f"opened:{day.isoformat()}")
        self.assertEqual(found, {self.printer.number, self.vpn.number, self.wifi.number, self.screen.number})

    def test_mistakes_are_explained_not_ignored(self):
        _, parsed = self.find("opened:soon priority:")
        self.assertEqual(len(parsed.problems), 2)
        response = self.client.get(reverse("staff:tickets"), {"q": "opened:soon"})
        self.assertEqual(response.status_code, 302)  # signed out
        self.login(self.tech)
        response = self.client.get(reverse("staff:tickets"), {"q": "opened:soon"})
        self.assertContains(response, "Couldn&#x27;t read the date")

    def test_search_list_shows_best_match_first(self):
        # A match in the summary outranks a newer ticket that only mentions it further down.
        newer = self.new_ticket(description="Toner is low\nThe printer in room 9 says replace soon")
        self.login(self.tech)
        response = self.client.get(reverse("staff:tickets"), {"q": "printer"})
        body = response.content.decode()
        self.assertLess(body.index(f">{self.printer.number}<"), body.index(f">{newer.number}<"))

    def test_index_survives_other_changes(self):
        # Assigning, re-prioritizing or resolving must never wipe a ticket from search.
        services.update_ticket(self.printer, self.tech, {"assignee": self.tech, "priority": Ticket.HIGH})
        services.add_note(self.printer, self.tech, Note.RESOLUTION, "Replaced the roller")
        self.printer.save()
        found, _ = self.find("jam")
        self.assertEqual(found, {self.printer.number})
        found, _ = self.find("roller")
        self.assertEqual(found, {self.printer.number})

    def test_hyphenated_words_found_either_way(self):
        found, _ = self.find("wifi")
        self.assertEqual(found, {self.wifi.number})
        found, _ = self.find("wi-fi")
        self.assertEqual(found, {self.wifi.number})

    def test_index_follows_edits(self):
        services.add_requester_reply(self.wifi, "It also happens in the cafeteria", [])
        found, _ = self.find("cafeteria")
        self.assertEqual(found, {self.wifi.number})
        services.update_ticket(self.wifi, self.tech, {"summary": "Conference Wi-Fi keeps dropping"})
        found, _ = self.find("keeps")
        self.assertEqual(found, {self.wifi.number})

    def test_closed_tickets_are_searched_too(self):
        services.add_note(self.printer, self.tech, Note.RESOLUTION, "Cleared the jam")
        self.assertEqual(self.printer.status.kind, Status.RESOLVED)
        self.login(self.tech)
        response = self.client.get(reverse("staff:tickets"), {"q": "jam"})
        self.assertContains(response, "Printer jam")

    def test_rebuild_command_reindexes_after_search_changes(self):
        from io import StringIO

        from django.core.cache import cache
        from django.core.management import call_command

        Ticket.objects.update(search_vector=None)
        cache.delete("tixsys:search-version")
        out = StringIO()
        call_command("rebuild_search", auto=True, stdout=out)
        self.assertIn("4 ticket(s)", out.getvalue())
        out = StringIO()
        call_command("rebuild_search", auto=True, stdout=out)
        self.assertEqual(out.getvalue(), "")  # nothing left to do
        found, _ = self.find("jam")
        self.assertEqual(found, {self.printer.number})
