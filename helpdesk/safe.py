"""Guards for values that arrive straight from a web address, a cookie or a form field
that isn't a Django form. Anything odd becomes "nothing" instead of an error."""

import re
from urllib.parse import parse_qsl, urlencode

# Control characters (NUL, backspace, escape...) never belong in text people type.
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
MAX_ID = 2**63 - 1


def text(value, limit=None):
    """One line of text: control characters removed, line breaks turned into spaces."""
    value = CONTROL.sub("", str(value or ""))
    value = value.replace("\r", " ").replace("\n", " ").strip()
    return value[:limit] if limit else value


def number(value):
    """'42' -> 42. Letters, '²', '-1', and numbers too big for the database -> None."""
    value = str(value or "").strip()
    if not value.isascii() or not value.isdigit() or len(value) > 19:
        return None
    n = int(value)
    return n if n <= MAX_ID else None


def query_string(value, limit=1000):
    """A saved ticket-list address, rebuilt so it can only ever be name=value pairs."""
    pairs = [(text(k, 40), text(v, 500)) for k, v in parse_qsl(str(value or ""), keep_blank_values=False)]
    return urlencode([(k, v) for k, v in pairs if k and v])[:limit]


class TokenConverter:
    """Private ticket links: letters, digits, - and _ only, of a sane length."""

    regex = "[A-Za-z0-9_-]{16,100}"

    def to_python(self, value):
        return value

    def to_url(self, value):
        return value


class NumberConverter:
    """Ticket numbers and record ids in addresses: up to 18 digits (fits the database)."""

    regex = "[0-9]{1,18}"

    def to_python(self, value):
        return int(value)

    def to_url(self, value):
        return str(value)
