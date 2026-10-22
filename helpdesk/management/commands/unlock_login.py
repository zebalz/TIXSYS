"""Unlocks a staff account that was locked by too many failed sign-ins.

python manage.py unlock_login <username>
"""

from django.core.management.base import BaseCommand

from helpdesk import throttle


class Command(BaseCommand):
    help = "Unlock a staff sign-in early."

    def add_arguments(self, parser):
        parser.add_argument("username")

    def handle(self, *args, **opts):
        throttle.unlock(opts["username"])
        self.stdout.write(self.style.SUCCESS(f"Unlocked {opts['username']}."))
