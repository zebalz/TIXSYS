from django import template
from django.utils import timezone

register = template.Library()


@register.filter
def readable_on(hex_color):
    """Black or white text, whichever reads better on the given color."""
    try:
        value = hex_color.lstrip("#")
        r, g, b = (int(value[i : i + 2], 16) / 255 for i in (0, 2, 4))
    except (ValueError, AttributeError):
        return "#ffffff"

    def channel(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    luminance = 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)
    return "#14202b" if luminance > 0.45 else "#ffffff"


@register.filter
def age(value):
    """Short age like 3d, 5h, 12m."""
    if not value:
        return ""
    seconds = int((timezone.now() - value).total_seconds())
    if seconds < 3600:
        return f"{max(seconds // 60, 1)}m"
    if seconds < 86400:
        return f"{seconds // 3600}h"
    return f"{seconds // 86400}d"


@register.filter
def initials(user):
    if not user:
        return ""
    first = (user.first_name or user.username or "?")[:1]
    last = (user.last_name or "")[:1]
    return (first + last).upper()
