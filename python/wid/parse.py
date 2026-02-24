"""Parse WIDs."""

# pylint: disable=invalid-name,line-too-long
# flake8: noqa: N803

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

_HEX_LOWER_RE_CACHE: dict[int, re.Pattern[str]] = {}
_WID_BASE_RE_CACHE: dict[tuple[int, str], re.Pattern[str]] = {}
_HLC_BASE_RE_CACHE: dict[tuple[int, str], re.Pattern[str]] = {}

_NODE_RE = re.compile(r"^\S+$")  # no whitespace


@dataclass(frozen=True, slots=True)
class ParsedWid:
    """Parsed WID."""

    raw: str
    timestamp: datetime
    sequence: int
    padding: str | None


@dataclass(frozen=True, slots=True)
class ParsedHlcWid:
    """Parsed HLC WID."""

    raw: str
    timestamp: datetime
    logical_counter: int
    node: str
    padding: str | None


def _hex_re(z: int) -> re.Pattern[str]:
    p = _HEX_LOWER_RE_CACHE.get(z)
    if p is None:
        p = re.compile(rf"^[0-9a-f]{{{z}}}$")
        _HEX_LOWER_RE_CACHE[z] = p
    return p


def _wid_base_re(W: int, time_unit: Literal["sec", "ms"]) -> re.Pattern[str]:
    # Captures: date(8), time(6|9), seq(W), suffix (optional)
    key = (W, time_unit)
    p = _WID_BASE_RE_CACHE.get(key)
    if p is None:
        time_digits = 9 if time_unit == "ms" else 6
        p = re.compile(rf"^(\d{{8}})T(\d{{{time_digits}}})\.(\d{{{W}}})Z(.*)?$")
        _WID_BASE_RE_CACHE[key] = p
    return p


def _hlc_base_re(W: int, time_unit: Literal["sec", "ms"]) -> re.Pattern[str]:
    # Captures: date(8), time(6|9), lc(W), node, suffix (optional)
    key = (W, time_unit)
    p = _HLC_BASE_RE_CACHE.get(key)
    if p is None:
        time_digits = 9 if time_unit == "ms" else 6
        p = re.compile(
            rf"^(\d{{8}})T(\d{{{time_digits}}})\.(\d{{{W}}})Z-([^\s-]+)(.*)?$"
        )
        _HLC_BASE_RE_CACHE[key] = p
    return p


def _parse_ts(
    date_str: str, time_str: str, time_unit: Literal["sec", "ms"] = "sec"
) -> datetime | None:
    try:
        year = int(date_str[0:4])
        month = int(date_str[4:6])
        day = int(date_str[6:8])
        hour = int(time_str[0:2])
        minute = int(time_str[2:4])
        second = int(time_str[4:6])
        millis = int(time_str[6:9]) if time_unit == "ms" else 0
        if millis < 0 or millis > 999:
            return None
        # strict: datetime will raise for invalid calendar values
        return datetime(
            year,
            month,
            day,
            hour,
            minute,
            second,
            millis * 1000,
            tzinfo=timezone.utc,
        )
    except ValueError:
        return None


def validate_wid(
    wid: str, W: int = 4, Z: int = 6, time_unit: Literal["sec", "ms"] = "sec"
) -> bool:
    """Validate a wid."""
    return parse_wid(wid, W=W, Z=Z, time_unit=time_unit) is not None


# pylint: disable=too-many-return-statements
def parse_wid(
    wid: str, W: int = 4, Z: int = 6, time_unit: Literal["sec", "ms"] = "sec"
) -> ParsedWid | None:
    """Try to parse a possible wid."""
    if W <= 0 or Z < 0 or time_unit not in {"sec", "ms"}:
        return None

    m = _wid_base_re(W, time_unit).match(wid)
    if not m:
        return None

    date_str, time_str, seq_str, suffix = (
        m.group(1),
        m.group(2),
        m.group(3),
        m.group(4) or "",
    )
    ts = _parse_ts(date_str, time_str, time_unit)
    if ts is None:
        return None

    seq = int(seq_str)

    padding: str | None = None
    if suffix:
        if not suffix.startswith("-"):
            return None
        seg = suffix[1:]
        if Z == 0:
            # no suffix allowed when Z==0 for WID
            return None
        if not _hex_re(Z).match(seg):
            return None
        padding = seg
    else:
        if Z > 0:
            # allow missing padding even if Z>0 (caller chooses policy)
            padding = None

    return ParsedWid(raw=wid, timestamp=ts, sequence=seq, padding=padding)


def validate_hlc_wid(
    wid: str, W: int = 4, Z: int = 0, time_unit: Literal["sec", "ms"] = "sec"
) -> bool:
    """Validate an HLC WID."""
    return parse_hlc_wid(wid, W=W, Z=Z, time_unit=time_unit) is not None


def parse_hlc_wid(
    wid: str, W: int = 4, Z: int = 0, time_unit: Literal["sec", "ms"] = "sec"
) -> ParsedHlcWid | None:
    """Parse an HLC WID."""
    if W <= 0 or Z < 0 or time_unit not in {"sec", "ms"}:
        return None

    m = _hlc_base_re(W, time_unit).match(wid)
    if not m:
        return None

    date_str, time_str, lc_str, node, suffix = (
        m.group(1),
        m.group(2),
        m.group(3),
        m.group(4),
        m.group(5) or "",
    )
    if not _NODE_RE.match(node):
        return None

    ts = _parse_ts(date_str, time_str, time_unit)
    if ts is None:
        return None

    lc = int(lc_str)

    padding: str | None = None
    if suffix:
        if not suffix.startswith("-"):
            return None
        seg = suffix[1:]
        if Z == 0:
            return None
        if not _hex_re(Z).match(seg):
            return None
        padding = seg

    return ParsedHlcWid(
        raw=wid, timestamp=ts, logical_counter=lc, node=node, padding=padding
    )
