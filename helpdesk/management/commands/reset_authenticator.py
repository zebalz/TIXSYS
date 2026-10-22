"""Turns off the authenticator app for a staff account, for when someone loses their phone.
Run on the server, so only someone with server access can do it:

python manage.py reset_authenticator <username>

If their role requires an authenticator, they set up a new one the next time they sign in.
"""

import logging

from django.core.management.base import BaseCommand, CommandError

from helpdesk.models import SecurityEvent, User


class Command(BaseCommand):
    help = "Turn off the authenticator app for a staff account (lost phone)."

    def add_arguments(self, parser):
        parser.add_argument("username")

    def handle(self, *args, **opts):
        user = User.objects.filter(username=opts["username"]).first()
        if user is None:
            raise CommandError(f"No staff account named {opts['username']}.")
        user.totp_enabled = False
        user.totp_secret = ""  # erases the secret; not a password  # nosec B105
        user.totp_last_counter = 0
        user.save(update_fields=["totp_enabled", "totp_secret", "totp_last_counter"])
        SecurityEvent.objects.create(
            organization=user.organization,
            user=user,
            username=user.username,
            kind=SecurityEvent.AUTHENTICATOR_RESET,
            ip="server",
            detail=f"for {user.username}, from the server command line",
        )
        logging.getLogger("tixsys.security").info(
            "security event=authenticator_reset user=%s (command line)", user.username
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Authenticator app turned off for {user.username}. They'll set up a new one when they sign in."
            )
        )
