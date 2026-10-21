"""Counters for sign-in lockout and portal rate limits, kept in the shared cache."""

import time

from django.conf import settings
from django.core.cache import cache


def client_ip(request):
    if settings.TRUST_X_FORWARDED_FOR:
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if forwarded:
            # The proxy in front of the app appends the real address last.
            return forwarded.split(",")[-1].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


def _full(key):
    return f"tixsys:{key}"


def count(key, window_seconds):
    """Add one to a counter that resets window_seconds after its first hit. Returns the new count."""
    now = time.time()
    data = cache.get(_full(key))
    if not data or data[1] <= now:
        data = (0, now + window_seconds)
    data = (data[0] + 1, data[1])
    cache.set(_full(key), data, max(1, int(data[1] - now) + 1))
    return data[0]


def peek(key):
    data = cache.get(_full(key))
    return data[0] if data and data[1] > time.time() else 0


def clear(key):
    cache.delete(_full(key))


def over_limit(key, limit, window_seconds):
    """Counts this attempt and says whether it went over the limit."""
    return count(key, window_seconds) > limit


# --- Sign-in -----------------------------------------------------------------


class SignInBlocked(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message


def _name(username):
    return (username or "").strip().lower()


def _until(key):
    value = cache.get(_full(key))
    return value if value and value > time.time() else None


def check_sign_in_allowed(username, ip):
    name = _name(username)
    if _until(f"login-lock:user:{name}") or _until(f"login-lock:ip:{ip}"):
        raise SignInBlocked(
            f"Too many failed sign-ins. Signing in is locked for {settings.LOGIN_LOCKOUT_MINUTES} minutes. "
            "Ask the administrator if you need in sooner."
        )
    wait_until = _until(f"login-wait:user:{name}")
    if wait_until:
        seconds = int(wait_until - time.time()) + 1
        raise SignInBlocked(f"Too many failed sign-ins. Wait {seconds} seconds, then try again.")


def record_failure(username, ip):
    name = _name(username)
    window = settings.LOGIN_LOCKOUT_MINUTES * 60
    failures = count(f"login-fail:user:{name}", window)
    ip_failures = count(f"login-fail:ip:{ip}", window)
    if failures >= settings.LOGIN_LOCKOUT_AFTER:
        cache.set(_full(f"login-lock:user:{name}"), time.time() + window, window)
    elif failures >= settings.LOGIN_SLOWDOWN_AFTER:
        # Each extra failure adds 15 seconds of waiting, up to 2 minutes.
        delay = min(15 * (failures - settings.LOGIN_SLOWDOWN_AFTER + 1), 120)
        cache.set(_full(f"login-wait:user:{name}"), time.time() + delay, delay)
    if ip_failures >= settings.LOGIN_IP_LOCKOUT_AFTER:
        cache.set(_full(f"login-lock:ip:{ip}"), time.time() + window, window)
    return failures


def record_success(username):
    name = _name(username)
    for key in (f"login-fail:user:{name}", f"login-wait:user:{name}"):
        clear(key)


def unlock(username):
    """Used by the administrator command to unlock someone early."""
    name = _name(username)
    for key in (f"login-fail:user:{name}", f"login-wait:user:{name}", f"login-lock:user:{name}"):
        clear(key)
