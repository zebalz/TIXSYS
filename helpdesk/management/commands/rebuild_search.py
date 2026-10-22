"""Rebuilds the search index for tickets.

    python manage.py rebuild_search            # every ticket
    python manage.py rebuild_search --missing  # only tickets that have never been indexed
    python manage.py rebuild_search --auto     # every ticket if search changed since the last run,
                                               # otherwise only missing ones (used at startup)

The app keeps the index up to date by itself. This is for after a restore
from an old backup, an update that improves search, or if results ever look stale."""

from django.core.cache import cache
from django.core.management.base import BaseCommand

from helpdesk import search
from helpdesk.models import Ticket

VERSION_KEY = "tixsys:search-version"


class Command(BaseCommand):
    help = "Rebuild the ticket search index."

    def add_arguments(self, parser):
        parser.add_argument("--missing", action="store_true", help="Only index tickets that have no index entry yet.")
        parser.add_argument("--auto", action="store_true", help="Everything if search changed, else only missing.")

    def handle(self, *args, **opts):
        only_missing = opts["missing"]
        if opts["auto"]:
            only_missing = cache.get(VERSION_KEY) == search.VERSION
        tickets = Ticket.objects.all()
        if only_missing:
            tickets = tickets.filter(search_vector__isnull=True)
        ids = list(tickets.values_list("pk", flat=True))
        for start in range(0, len(ids), 500):
            search.refresh(ids[start : start + 500])
        cache.set(VERSION_KEY, search.VERSION, timeout=None)
        if ids or not only_missing:
            self.stdout.write(f"Search index updated for {len(ids)} ticket(s).")
