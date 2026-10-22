"""Writes the security log (sign-ins, lockouts, authenticator changes, exports)."""

import logging

from .models import SecurityEvent
from .throttle import client_ip

log = logging.getLogger("tixsys.security")


def record(request, kind, user=None, username="", detail=""):
    user = user if user is not None and getattr(user, "pk", None) else None
    name = username or (user.username if user else "")
    org = getattr(user, "organization", None) if user else None
    if org is None:
        org = getattr(request, "org", None)
        org = org if getattr(org, "pk", None) else None
    event = SecurityEvent.objects.create(
        organization=org,
        user=user,
        username=name[:150],
        kind=kind,
        ip=client_ip(request)[:64],
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:200],
        detail=detail[:300],
    )
    # Also goes to the app log, so it reaches whatever collects server logs.
    log.info("security event=%s user=%s ip=%s %s", kind, name, event.ip, detail)
    return event
