"""Authenticator-app codes (TOTP). Works with Microsoft Authenticator, Google
Authenticator, 1Password and others. No outside service is involved."""

import hmac
import io
import time

import pyotp
import qrcode
import qrcode.image.svg

STEP = 30


def new_secret():
    return pyotp.random_base32()


def provisioning_uri(secret, username, issuer):
    return pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name=issuer)


def qr_svg(uri):
    image = qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage, box_size=8, border=2)
    buffer = io.BytesIO()
    image.save(buffer)
    svg = buffer.getvalue().decode("utf-8")
    # Drop the XML declaration so it can sit inside the page.
    if svg.startswith("<?xml"):
        svg = svg.split("?>", 1)[1]
    return svg


def matching_counter(secret, code, now=None):
    """Returns the time step the code belongs to (allowing one step of clock
    drift either way), or None if the code is wrong."""
    now = now or time.time()
    totp = pyotp.TOTP(secret)
    current = int(now // STEP)
    for counter in (current, current - 1, current + 1):
        # Compared in constant time, so response timing gives nothing away.
        if hmac.compare_digest(totp.generate_otp(counter).encode(), str(code).encode()):
            return counter
    return None


def verify_for_user(user, code):
    """Checks a code and refuses one that was already used.

    The database checks "not used yet" and records the use in one statement, so two
    sign-ins sending the same code at the same moment can't both get in."""
    if not user.totp_secret:
        return False
    counter = matching_counter(user.totp_secret, code)
    if counter is None:
        return False
    not_used_yet = type(user).objects.filter(
        pk=user.pk,
        totp_enabled=True,
        totp_secret=user.totp_secret,  # still the secret this code was checked against
        totp_last_counter__lt=counter,
    )
    if not not_used_yet.update(totp_last_counter=counter):
        return False
    user.totp_last_counter = counter
    return True
