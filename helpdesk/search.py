"""Ticket search for staff.

One search box, Gmail/Jira style:

    printer jam                 tickets with both words (word forms count: "print" finds "printing")
    "blue screen"               the exact phrase
    vpn OR wifi                 either word
    outlook -calendar           leave out tickets with a word
    status:resolved             a field (see FIELDS below); put quotes around values with spaces
    -status:closed              leave out a field value
    opened:2026-09-01..2026-09-30   opened:<7d   resolved:>30d   updated:today
    has:attachment  has:internal  is:open  is:mine

Words and phrases are matched with PostgreSQL full-text search against the
summary, description, requester details and every note. Field filters become
ordinary database filters. Nothing here builds SQL by hand.
"""

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from django.contrib.postgres.aggregates import StringAgg
from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector
from django.db.models import CharField, Exists, F, OuterRef, Q, Subquery, TextField, Value
from django.db.models.functions import Cast, Coalesce, Replace
from django.utils import timezone

from . import safe
from .models import Attachment, Note, Status, Ticket

CONFIG = "english"
# Bump this when search_document() changes, so servers re-index every ticket on their next start.
VERSION = 2
MAX_TICKET_NUMBER = 2_147_483_647  # the largest number the database column holds

FIELD_HELP = [
    ("status:", 'status:resolved, status:"waiting on employee"'),
    ("assignee:", "assignee:marcus, assignee:me, assignee:none"),
    ("board:", "board:database"),
    ("category:", "category:printer"),
    ("priority:", "priority:high"),
    ("requester:", "requester:grace (name or email)"),
    ("location:", 'location:"room 210"'),
    ("from:", "from:phone, from:portal, from:walkup, from:text"),
    ("opened:", "opened:2026-09-01..2026-09-30, opened:<7d, opened:>30d, opened:today"),
    ("resolved:", "resolved:<14d, resolved:2026-10"),
    ("updated:", "updated:<2d"),
    ("has:", "has:attachment, has:internal, has:resolution, has:reply"),
    ("is:", "is:open, is:closed, is:unassigned, is:mine"),
]

TOKEN_RE = re.compile(
    r"""
    \s*
    (?P<neg>-)?
    (?:
        (?P<field>[A-Za-z]+):(?:"(?P<fquoted>[^"]*)"?|(?P<fvalue>[^\s"]*))
      | "(?P<phrase>[^"]*)"?
      | (?P<word>[^\s"]+)
    )
    """,
    re.VERBOSE,
)
LEXEME_RE = re.compile(r"[^\W_]+")  # letters and digits only, so nothing can act as a search operator


@dataclass
class ParsedSearch:
    text: str = ""
    tsquery: str = ""  # raw to_tsquery input, built only from letter/digit pieces
    filters: Q = field(default_factory=Q)
    chips: list = field(default_factory=list)  # human-readable pieces, for showing what was searched
    problems: list = field(default_factory=list)
    numbers: list = field(default_factory=list)

    @property
    def has_text(self):
        return bool(self.tsquery)


def _lexemes(text):
    return LEXEME_RE.findall(text.lower())


def _term(text, prefix=True):
    """One word or phrase as tsquery text, or '' if nothing searchable is left."""
    parts = _lexemes(text)
    if not parts:
        return ""
    if len(parts) == 1:
        return f"{parts[0]}:*" if prefix else parts[0]
    joined = " <-> ".join([*parts[:-1], f"{parts[-1]}:*" if prefix else parts[-1]])
    return f"({joined})"


# --- Dates ---------------------------------------------------------------------

REL_RE = re.compile(r"^(\d+)([dwmy])$")


def _relative(value):
    match = REL_RE.match(value)
    if not match or len(match.group(1)) > 5:
        return None
    n, unit = int(match.group(1)), match.group(2)
    days = min({"d": 1, "w": 7, "m": 30, "y": 365}[unit] * n, 365 * 100)  # at most 100 years back
    return timezone.now() - timedelta(days=days)


def _day_start(d):
    return timezone.make_aware(datetime.combine(d, time.min))


def _parse_day_or_month(value):
    """'2026-09-01' -> (start, end) of that day; '2026-09' -> that month; 'today'/'yesterday'."""
    today = timezone.localdate()
    if value == "today":
        return _day_start(today), _day_start(today + timedelta(days=1))
    if value == "yesterday":
        return _day_start(today - timedelta(days=1)), _day_start(today)
    try:
        if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
            d = date.fromisoformat(value)
            if not 1900 <= d.year <= 2999:
                return None
            return _day_start(d), _day_start(d + timedelta(days=1))
        if re.fullmatch(r"[0-9]{4}-[0-9]{2}", value):
            year, month = map(int, value.split("-"))
            if not 1900 <= year <= 2999:
                return None
            first = date(year, month, 1)
            nxt = date(year + (month == 12), month % 12 + 1, 1)
            return _day_start(first), _day_start(nxt)
    except (ValueError, OverflowError):
        return None
    return None


def _date_filter(column, value):
    """Returns (Q, readable) or (None, problem)."""
    v = value.strip().lower()
    for op in (">=", "<=", ">", "<"):
        if v.startswith(op):
            rest = v[len(op) :]
            rel = _relative(rest)
            if rel is not None:
                # <7d means "within the last 7 days"; >30d means "more than 30 days ago".
                if op.startswith("<"):
                    return Q(**{f"{column}__gte": rel}), f"in the last {rest}"
                return Q(**{f"{column}__lt": rel}), f"more than {rest} ago"
            span = _parse_day_or_month(rest)
            if span:
                start, end = span
                lookup = {">": ("gte", end), ">=": ("gte", start), "<": ("lt", start), "<=": ("lt", end)}[op]
                return Q(**{f"{column}__{lookup[0]}": lookup[1]}), f"{op} {rest}"
            return None, f"Couldn't read the date '{value}'. Use 2026-09-01, 2026-09, 7d, 2w or today."
    if ".." in v:
        a, b = v.split("..", 1)
        span_a, span_b = _parse_day_or_month(a), _parse_day_or_month(b)
        if span_a and span_b:
            return Q(**{f"{column}__gte": span_a[0], f"{column}__lt": span_b[1]}), f"{a} to {b}"
        return None, f"Couldn't read the date range '{value}'. Use 2026-09-01..2026-09-30."
    rel = _relative(v)
    if rel is not None:
        return Q(**{f"{column}__gte": rel}), f"in the last {v}"
    span = _parse_day_or_month(v)
    if span:
        return Q(**{f"{column}__gte": span[0], f"{column}__lt": span[1]}), v
    return None, f"Couldn't read the date '{value}'. Use 2026-09-01, 2026-09, 7d, 2w or today."


# --- Field filters -------------------------------------------------------------

SOURCE_ALIASES = {
    "portal": Ticket.PORTAL,
    "web": Ticket.PORTAL,
    "phone": Ticket.PHONE,
    "call": Ticket.PHONE,
    "text": Ticket.TEXT,
    "sms": Ticket.TEXT,
    "walkup": Ticket.WALKUP,
    "walk-up": Ticket.WALKUP,
    "walk": Ticket.WALKUP,
    "email": Ticket.EMAIL,
    "other": Ticket.OTHER,
}
IS_VALUES = {
    "open": ~Q(status__kind__in=Status.DONE_KINDS),
    "closed": Q(status__kind__in=Status.DONE_KINDS),
    "done": Q(status__kind__in=Status.DONE_KINDS),
    "resolved": Q(status__kind=Status.RESOLVED),
    "new": Q(status__kind=Status.NEW),
    "waiting": Q(status__kind=Status.WAITING),
    "unassigned": Q(assignee__isnull=True),
    "assigned": Q(assignee__isnull=False),
}


def _field_filter(name, value, user):
    """Returns (Q, readable) or (None, problem). name is already lower-case."""
    v = value.strip()
    lv = v.lower()
    if not v:
        return None, f"'{name}:' needs a value, like {name}:something."
    if name == "status":
        return Q(status__name__icontains=v) | Q(status__kind=lv.replace(" ", "_")), f"status {v}"
    if name in ("assignee", "assigned", "tech"):
        if lv in ("none", "nobody", "unassigned"):
            return Q(assignee__isnull=True), "unassigned"
        if lv == "me" and user is not None:
            return Q(assignee=user), "assigned to me"
        return (
            Q(assignee__first_name__icontains=v)
            | Q(assignee__last_name__icontains=v)
            | Q(assignee__username__icontains=v),
            f"assigned to {v}",
        )
    if name == "board":
        return Q(board__name__icontains=v), f"board {v}"
    if name == "category":
        if lv == "none":
            return Q(category__isnull=True), "no category"
        return Q(category__name__icontains=v), f"category {v}"
    if name == "priority":
        keys = {key for key, label in Ticket.PRIORITY_CHOICES if key == lv or label.lower() == lv}
        if not keys:
            return None, f"Priority is low, medium, high or critical, not '{v}'."
        return Q(priority__in=keys), f"priority {lv}"
    if name in ("requester", "from_person", "who"):
        return Q(requester_name__icontains=v) | Q(requester_email__icontains=v), f"requester {v}"
    if name == "email":
        return Q(requester_email__icontains=v), f"email {v}"
    if name == "location":
        return Q(location__icontains=v), f"location {v}"
    if name in ("from", "source", "via"):
        source = SOURCE_ALIASES.get(lv)
        if not source:
            return None, f"from: is portal, phone, text, walkup or email, not '{v}'."
        return Q(source=source), f"came in by {dict(Ticket.SOURCE_CHOICES)[source].lower()}"
    if name in ("opened", "created"):
        return _date_filter("created_at", v)
    if name in ("resolved", "closed"):
        return _date_filter("resolved_at", v)
    if name == "updated":
        return _date_filter("updated_at", v)
    if name == "has":
        if lv in ("attachment", "attachments", "file", "files", "screenshot", "screenshots"):
            return Q(Exists(Attachment.objects.filter(ticket=OuterRef("pk")))), "has files"
        if lv in ("internal", "resolution", "discussion"):
            return Q(Exists(Note.objects.filter(ticket=OuterRef("pk"), kind=lv))), f"has {lv} note"
        if lv in ("reply", "replies"):
            return Q(Exists(Note.objects.filter(ticket=OuterRef("pk"), from_requester=True))), "has employee reply"
        if lv in ("note", "notes"):
            return Q(Exists(Note.objects.filter(ticket=OuterRef("pk")))), "has notes"
        return None, f"has: is attachment, internal, resolution, reply or notes, not '{v}'."
    if name == "is":
        if lv == "mine" and user is not None:
            return Q(assignee=user), "mine"
        if lv in IS_VALUES:
            return IS_VALUES[lv], lv
        return None, f"is: is open, closed, resolved, new, waiting, unassigned or mine, not '{v}'."
    if name in ("number", "ticket"):
        digits = v.lstrip("#")
        if safe.number(digits) is not None and int(digits) <= MAX_TICKET_NUMBER:
            return Q(number=int(digits)), f"#{digits}"
        return None, f"number: needs a ticket number, not '{v}'."
    return None, None  # not a field we know: the caller treats it as words


KNOWN_FIELDS = {
    "status",
    "assignee",
    "assigned",
    "tech",
    "board",
    "category",
    "priority",
    "requester",
    "who",
    "email",
    "location",
    "from",
    "source",
    "via",
    "opened",
    "created",
    "resolved",
    "closed",
    "updated",
    "has",
    "is",
    "number",
    "ticket",
}


def parse(query, user=None):
    result = ParsedSearch(text=safe.text(query, 500))
    groups = []  # each group is a list of alternatives joined by OR
    group_chips = []  # index into result.chips for each group
    pending_or = False
    for match in TOKEN_RE.finditer(result.text[:500]):
        neg = bool(match.group("neg"))
        name = (match.group("field") or "").lower()
        if name and name in KNOWN_FIELDS:
            value = match.group("fquoted") if match.group("fquoted") is not None else match.group("fvalue") or ""
            q, readable = _field_filter(name, value, user)
            if q is None:
                result.problems.append(readable)
                continue
            result.filters &= ~q if neg else q
            result.chips.append(("not " if neg else "") + readable)
            pending_or = False
            continue

        if match.group("phrase") is not None:
            raw, is_phrase = match.group("phrase"), True
        elif name:  # unknown "word:thing" - search it as words
            raw, is_phrase = match.group(0).strip().lstrip("-"), True
        else:
            raw, is_phrase = match.group("word") or "", False

        if not is_phrase and raw == "OR":
            pending_or = bool(groups)
            continue
        if not is_phrase and re.fullmatch(r"#?[0-9]{1,10}", raw) and int(raw.lstrip("#")) <= MAX_TICKET_NUMBER:
            result.numbers.append(int(raw.lstrip("#")))
        term = _term(raw)
        if not term:
            continue
        piece = f"!{term}" if neg else term
        label = f'"{raw}"' if is_phrase else raw
        if pending_or and groups:
            groups[-1].append(piece)
            i = group_chips[-1]
            result.chips[i] = result.chips[i] + " or " + label
        else:
            groups.append([piece])
            group_chips.append(len(result.chips))
            result.chips.append(("without " if neg else "") + label)
        pending_or = False

    result.tsquery = " & ".join(g[0] if len(g) == 1 else "(" + " | ".join(g) + ")" for g in groups)
    return result


# --- Search index --------------------------------------------------------------


def search_document():
    """The expression stored in Ticket.search_vector."""
    notes = (
        Note.objects.filter(ticket=OuterRef("pk"))
        .values("ticket")
        .annotate(all_notes=StringAgg("body", delimiter=" "))
        .values("all_notes")
    )
    return (
        SearchVector(Cast("number", CharField()), weight="A", config=CONFIG)
        + SearchVector("summary", weight="A", config=CONFIG)
        + SearchVector("description", weight="B", config=CONFIG)
        # "Wi-Fi" also as "wifi", "e-mail" as "email": people type them both ways.
        + SearchVector(
            Replace("description", Value("-"), Value(""), output_field=TextField()), weight="C", config=CONFIG
        )
        + SearchVector("requester_name", "requester_email", "location", weight="C", config=CONFIG)
        + SearchVector(
            Coalesce(Subquery(notes[:1], output_field=TextField()), Value(""), output_field=TextField()),
            weight="D",
            config=CONFIG,
        )
    )


def refresh(ticket_ids):
    """Rebuild the search index for these tickets. Called after every change."""
    ids = list(ticket_ids)
    if ids:
        Ticket.objects.filter(pk__in=ids).update(search_vector=search_document())


def apply(queryset, parsed):
    """Filter (and annotate rank on) a ticket queryset with a parsed search."""
    qs = queryset.filter(parsed.filters)
    if parsed.has_text:
        query = SearchQuery(parsed.tsquery, search_type="raw", config=CONFIG)
        match = Q(search_vector=query)
        if parsed.numbers:
            match |= Q(number__in=parsed.numbers)
        qs = qs.filter(match).annotate(rank=SearchRank(F("search_vector"), query))
    return qs
