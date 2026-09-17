"""UTC storage and application-local calendar helpers."""
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from ..config import settings


def utc_now() -> datetime:
    """Return a naive UTC timestamp for existing DateTime columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def app_timezone() -> ZoneInfo:
    return ZoneInfo(settings.APP_TIMEZONE)


def local_today() -> date:
    return datetime.now(app_timezone()).date()


def local_day_utc_bounds(value: date | None = None) -> tuple[datetime, datetime]:
    """Return naive UTC boundaries for one calendar day in APP_TIMEZONE."""
    target = value or local_today()
    start_local = datetime.combine(target, time.min, tzinfo=app_timezone())
    end_local = datetime.combine(target, time.max, tzinfo=app_timezone())
    start_utc = start_local.astimezone(timezone.utc).replace(tzinfo=None)
    end_utc = end_local.astimezone(timezone.utc).replace(tzinfo=None)
    return start_utc, end_utc


def utc_timestamp_to_local_date(value: datetime) -> date:
    """Interpret a naive database timestamp as UTC and return its local date."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(app_timezone()).date()
