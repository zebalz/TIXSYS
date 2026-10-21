"""Creates the organization, statuses, Help Desk board and categories on first run.
Safe to run every time the app starts."""

from django.core.management.base import BaseCommand

from helpdesk.bootstrap import ensure_defaults


class Command(BaseCommand):
    help = "Create starter settings if they don't exist yet."

    def handle(self, *args, **opts):
        org = ensure_defaults()
        self.stdout.write(f"Organization ready: {org.name}")
