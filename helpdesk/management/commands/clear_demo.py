"""Removes everything seed_demo added: demo tickets (with their notes, files and
history) and the demo.* staff accounts. Real tickets and accounts are kept.

    python manage.py clear_demo --yes
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from helpdesk.models import Attachment, Ticket, User


class Command(BaseCommand):
    help = "Remove demo tickets and demo staff accounts."

    def add_arguments(self, parser):
        parser.add_argument("--yes", action="store_true", help="Confirm you want to delete the demo data.")

    def handle(self, *args, **opts):
        tickets = Ticket.objects.filter(is_demo=True)
        users = User.objects.filter(username__startswith="demo.")
        if not opts["yes"]:
            raise CommandError(
                f"This deletes {tickets.count()} demo tickets and {users.count()} demo staff accounts. "
                "Run again with --yes to do it."
            )
        files = list(Attachment.objects.filter(ticket__in=tickets))
        with transaction.atomic():
            ticket_count = tickets.count()
            tickets.delete()
            user_count = users.count()
            users.delete()
        for f in files:
            f.file.delete(save=False)
        self.stdout.write(self.style.SUCCESS(f"Removed {ticket_count} demo tickets and {user_count} demo staff accounts."))
