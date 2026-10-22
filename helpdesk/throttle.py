"""Counters for sign-in lockout and portal rate limits, kept in the shared cache.

The server runs several app workers side by side, so two requests can touch the
same counter at the same moment. Each counter change, and each whole sign-in
attempt, holds a lock in the database while it runs, so nothing goes uncounted."""

import hashlib
import time
from contextlib import contextmanager

from django.conf import settings
from django.core.cache import cache
from django.db import DatabaseError, connection

# The cache stores keys of up to 250 characters, including what Django adds in front.
MAX_KEY_LENGTH = 200


def client_ip(request):
    if settings.TRUST_X_FORWARDED_FOR:
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if forwarded:
            # The proxy in front of the app appends the real address last.
            return forwarded.split(",")[-1].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


def _full(key):
    key = f"tixsys:{key}"
    if len(key) > MAX_KEY_LENGTH:
        # A key that long (a 300-character email address can make one) wouldn't be
        # stored at all, so its counter would never count. A fixed-length digest always fits.
        key = "tixsys:sha256:" + hashlib.sha256(key.encode()).hexdigest()
    return key


@contextmanager
def one_at_a_time(key):
    """Runs the block while holding a database lock named after the key. A request in any
    app worker that wants the same key waits until the block ends. (A PostgreSQL advisory
    lock: it locks a name, not a table, and the database frees it if the app worker dies.)"""
    lock_id = int.from_bytes(hashlib.sha256(_full(key).encode()).digest()[:8], "big", signed=True)
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_lock(%s)", [lock_id])
    try:
        yield
    finally:
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(%s)", [lock_id])
        except DatabaseError:
            # The connection broke during the block. Closing it frees the lock for sure.
            connection.close()


def count(key, window_seconds):
    """Add one to a counter that resets window_seconds after its first hit. Returns the new count."""
    with one_at_a_time(key):
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


def sign_in_turn(username):
    """Sign-in attempts for one username take turns, from the lockout check through the
    password (or code) check to counting a failure. Without this, a burst of guesses sent
    at the same moment would all pass the check before any of them was counted."""
    return one_at_a_time(f"sign-in:{_name(username)}")


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
