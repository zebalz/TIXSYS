"""Authenticator-app codes (TOTP). Works with Microsoft Authenticator, Google
Authenticator, 1Password and others. No outside service is involved."""

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
        if totp.generate_otp(counter) == code:
            return counter
    return None


def verify_for_user(user, code):
    """Checks a code and refuses one that was already used."""
    if not user.totp_secret:
        return False
    counter = matching_counter(user.totp_secret, code)
    if counter is None or counter <= user.totp_last_counter:
        return False
    user.totp_last_counter = counter
    user.save(update_fields=["totp_last_counter"])
    return True
