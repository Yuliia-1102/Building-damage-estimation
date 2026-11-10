"""Jinja2 environment shared by all routes: templates folder, Ukrainian reference dictionaries and a few filters.

Keeping this in one place means every page formats money, dates and category names the same way.
"""
from pathlib import Path

from fastapi import Request
from fastapi.responses import HTMLResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape

from core import reference
from web.models import UA_STATUS, Status

HERE = Path(__file__).resolve().parent
env = Environment(
    loader=FileSystemLoader(str(HERE / "templates")),
    autoescape=select_autoescape(["html", "xml"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


def money(value) -> str:
    """2158948 -> '2 158 948'. None -> '—'."""
    if value is None:
        return "—"
    return f"{int(round(value)):,}".replace(",", " ")


def money_short(value) -> str:
    """Compact money for cards: 2158948 -> '2,16 млн', 11000 -> '11 тис.'."""
    if value is None:
        return "—"
    v = float(value)
    if v >= 1_000_000:
        return f"{v / 1_000_000:.2f}".replace(".", ",") + " млн"
    if v >= 1_000:
        return f"{round(v / 1_000)}".replace(",", " ") + " тис."
    return money(v)


def dt(value) -> str:
    if value is None:
        return "—"
    return value.strftime("%d.%m.%Y %H:%M")


def duration(seconds) -> str:
    if seconds is None:
        return "—"
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds} с"
    return f"{seconds // 60} хв {seconds % 60} с"


def pct(value, digits: int = 0) -> str:
    """A ratio (0..1) as a percentage. None (e.g. the roof was not visible) shows as '—'."""
    if value is None:
        return "—"
    v = round(float(value) * 100, digits)
    return (f"{v:.{digits}f}" if digits else f"{int(v)}") + "%"


def m2(value) -> str:
    if value is None:
        return "—"
    return f"{round(float(value))} м²"


def num(value, digits: int = 1) -> str:
    """Round a number, tolerating None."""
    if value is None:
        return "—"
    return f"{round(float(value), digits):g}"


env.filters["money"] = money
env.filters["money_short"] = money_short
env.filters["dt"] = dt
env.filters["duration"] = duration
env.filters["pct"] = pct
env.filters["m2"] = m2
env.filters["num"] = num

from web import config as _webconfig  # noqa: E402

env.globals.update(
    Status=Status,
    UA_STATUS=UA_STATUS,
    max_mb=_webconfig.max_upload_mb(),
    DAMAGE_NAMES_UA=reference.DAMAGE_NAMES_UA,
    CONDITION_NAMES_UA=reference.CONDITION_NAMES_UA,
    ESCALATION_UA=reference.ESCALATION_UA,
    WORK_NAMES_UA=getattr(reference, "WORK_NAMES_UA", {}),
    UNITS_UA=getattr(reference, "UNITS_UA", {}),
    STRUCTURE_NAMES_UA=getattr(reference, "STRUCTURE_NAMES_UA", {}),
    DISCLAIMER_UA=getattr(reference, "DISCLAIMER_UA", ""),
)


def render(template: str, request: Request, **ctx) -> HTMLResponse:
    ctx.setdefault("request", request)
    html = env.get_template(template).render(**ctx)
    return HTMLResponse(html)