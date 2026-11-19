"""Require explicit calendar dates and timestamps for evidence."""

import re
from datetime import date, datetime
from typing import Annotated

from pydantic import AwareDatetime, BeforeValidator


def _calendar_date(value):
    if type(value) is date or (isinstance(value, str) and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value)):
        return value
    raise ValueError("Supply a calendar date in YYYY-MM-DD format.")


def _timestamp(value):
    if isinstance(value, datetime) or (
        isinstance(value, str) and re.match(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt ]", value)
    ):
        return value
    raise ValueError("Supply an ISO timestamp with an explicit timezone.")


EvidenceDate = Annotated[date, BeforeValidator(_calendar_date)]
EvidenceTimestamp = Annotated[AwareDatetime, BeforeValidator(_timestamp)]
