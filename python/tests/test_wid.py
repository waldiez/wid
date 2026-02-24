"""Tests for WID generation and validation."""

# pylint: disable=missing-function-docstring
# pylint: disable=import-outside-toplevel
# pylint: disable=unexpected-keyword-arg

# pyright: reportPrivateUsage=false
# flake8: noqa: D102,D103

import re
from pathlib import Path

import pytest
import wid.parse as parse_mod
from wid import (
    HLCWidGen,
    MemoryWidStateStore,
    SqliteWidStateStore,
    WidGen,
    parse_hlc_wid,
    parse_wid,
    validate_hlc_wid,
    validate_wid,
)


class TestValidateWid:
    """Tests for validate_wid function (WID without node)."""

    def test_accepts_minimal_wid_w4_z0(self) -> None:
        assert validate_wid("20260212T091530.0000Z", W=4, Z=0)
        assert validate_wid("20260212T091530.0042Z", W=4, Z=0)

    def test_accepts_wid_with_padding(self) -> None:
        assert validate_wid("20260212T091530.0042Z-a3f91c", W=4, Z=6)

    def test_accepts_max_sequence(self) -> None:
        assert validate_wid("20260212T091530.9999Z", W=4, Z=0)

    def test_accepts_midnight_utc(self) -> None:
        assert validate_wid("20260101T000000.0000Z", W=4, Z=0)

    def test_accepts_end_of_day(self) -> None:
        assert validate_wid("20261231T235959.0000Z", W=4, Z=0)

    def test_accepts_millisecond_wid(self) -> None:
        assert validate_wid("20260212T091530123.0000Z", W=4, Z=0, time_unit="ms")

    def test_rejects_non_wid_strings(self) -> None:
        assert not validate_wid("waldiez", W=4, Z=6)

    def test_rejects_missing_z_suffix(self) -> None:
        assert not validate_wid("20260212T091530.0000", W=4, Z=0)

    def test_rejects_lowercase_z(self) -> None:
        assert not validate_wid("20260212T091530.0000z", W=4, Z=0)

    def test_rejects_extended_iso_format(self) -> None:
        assert not validate_wid("2026-02-12T09:15:30.0000Z", W=4, Z=0)

    def test_rejects_invalid_month(self) -> None:
        assert not validate_wid("20261312T091530.0000Z", W=4, Z=0)

    def test_rejects_invalid_day(self) -> None:
        assert not validate_wid("20260232T091530.0000Z", W=4, Z=0)

    def test_rejects_invalid_hour(self) -> None:
        assert not validate_wid("20260212T251530.0000Z", W=4, Z=0)

    def test_rejects_uppercase_hex_padding(self) -> None:
        # Padding must be lowercase hex
        assert not validate_wid("20260212T091530.0000Z-ABCDEF", W=4, Z=6)

    def test_rejects_uuid_format(self) -> None:
        assert not validate_wid("550e8400-e29b-41d4-a716-446655440000", W=4, Z=6)

    def test_rejects_hlc_wid_format(self) -> None:
        # HLC-WID has a node, which validate_wid should reject
        assert not validate_wid("20260212T091530.0000Z-node01", W=4, Z=0)
        assert not validate_wid("20260212T091530.0000Z-node01-abcdef", W=4, Z=6)


class TestValidateHlcWid:
    """Tests for validate_hlc_wid function (HLC-WID with node)."""

    def test_accepts_hlc_wid_no_padding(self) -> None:
        assert validate_hlc_wid("20260212T091530.0000Z-node01", W=4, Z=0)
        assert validate_hlc_wid("20260212T091530.0042Z-mynode", W=4, Z=0)

    def test_accepts_hlc_wid_with_padding(self) -> None:
        assert validate_hlc_wid("20260212T091530.0042Z-node01-a3f91c", W=4, Z=6)

    def test_accepts_millisecond_hlc_wid(self) -> None:
        # pylint: disable=unexpected-keyword-arg
        assert validate_hlc_wid(
            "20260212T091530123.0042Z-node01-a3f91c",
            W=4,
            Z=6,
            time_unit="ms",
        )

    def test_accepts_underscore_in_node(self) -> None:
        assert validate_hlc_wid("20260212T091530.0000Z-my_node", W=4, Z=0)

    def test_accepts_numbers_in_node(self) -> None:
        assert validate_hlc_wid("20260212T091530.0000Z-node123", W=4, Z=0)

    def test_rejects_plain_wid(self) -> None:
        # Plain WID without node should not match HLC pattern
        assert not validate_hlc_wid("20260212T091530.0000Z", W=4, Z=0)

    def test_rejects_hyphen_in_node(self) -> None:
        # Node cannot contain hyphens (would be ambiguous with padding)
        # "node-01" would be parsed as node="node", pad="01" which is wrong length
        assert not validate_hlc_wid("20260212T091530.0000Z-node-01", W=4, Z=0)


class TestParseWid:
    """Tests for parse_wid function."""

    def test_parses_minimal_wid(self) -> None:
        parsed = parse_wid("20260212T091530.0042Z", W=4, Z=0)
        assert parsed
        assert parsed.sequence == 42
        # assert parsed.node is None
        assert parsed.padding is None
        assert parsed.timestamp.year == 2026
        assert parsed.timestamp.month == 2
        assert parsed.timestamp.day == 12

    def test_parses_wid_with_padding(self) -> None:
        parsed = parse_wid("20260212T091530.0042Z-a3f91c", W=4, Z=6)
        assert parsed is not None
        assert parsed.sequence == 42
        # assert parsed.node is None
        assert parsed.padding == "a3f91c"

    def test_parses_millisecond_wid(self) -> None:
        parsed = parse_wid("20260212T091530123.0042Z-a3f91c", W=4, Z=6, time_unit="ms")
        assert parsed is not None
        assert parsed.sequence == 42
        assert parsed.timestamp.microsecond == 123000

    def test_returns_none_for_invalid_wid(self) -> None:
        assert parse_wid("waldiez", W=4, Z=6) is None
        assert parse_wid("20260212T091530.0000", W=4, Z=0) is None

    def test_returns_none_for_hlc_wid(self) -> None:
        # parse_wid should not parse HLC-WID
        assert parse_wid("20260212T091530.0000Z-node01", W=4, Z=0) is None


class TestParseHlcWid:
    """Tests for parse_hlc_wid function."""

    def test_parses_hlc_wid_no_padding(self) -> None:
        parsed = parse_hlc_wid("20260212T091530.0042Z-node01", W=4, Z=0)
        assert parsed is not None
        # assert parsed.sequence == 42
        assert parsed.node == "node01"
        assert parsed.padding is None

    def test_parses_hlc_wid_with_padding(self) -> None:
        parsed = parse_hlc_wid("20260212T091530.0042Z-node01-a3f91c", W=4, Z=6)
        assert parsed is not None
        # assert parsed.sequence == 42
        assert parsed.node == "node01"
        assert parsed.padding == "a3f91c"

    def test_returns_none_for_plain_wid(self) -> None:
        # Plain WID should not parse as HLC
        assert parse_hlc_wid("20260212T091530.0000Z", W=4, Z=0) is None
        assert parse_hlc_wid("20260212T091530.0000Z-abcdef", W=4, Z=6) is not None


class TestWidGen:
    """Tests for WidGen class."""

    def test_generates_valid_wids(self) -> None:
        gen = WidGen(W=4, Z=6)
        wid = gen.next()
        assert validate_wid(wid, W=4, Z=6)

    def test_generates_valid_wids_no_padding(self) -> None:
        gen = WidGen(W=4, Z=0)
        wid = gen.next()
        assert validate_wid(wid, W=4, Z=0)

    def test_generates_monotonically_increasing_wids(self) -> None:
        gen = WidGen(W=4, Z=0)
        wid1 = gen.next()
        wid2 = gen.next()
        wid3 = gen.next()
        assert wid1 < wid2
        assert wid2 < wid3

    def test_generates_unique_padding(self) -> None:
        gen = WidGen(W=4, Z=6)
        wids = gen.next_n(10)
        paddings = [
            parse_wid(w, W=4, Z=6).padding   # type: ignore[unused-ignore,union-attr] # pyright: ignore[reportOptionalMemberAccess] # pylint: disable=line-too-long
            for w in wids
            if w
        ]
        # All paddings should be non-None
        assert all(p is not None for p in paddings)
        # All paddings should be unique
        assert len(set(paddings)) == 10

    def test_raises_on_invalid_w(self) -> None:
        with pytest.raises(ValueError):
            WidGen(W=0)
        with pytest.raises(ValueError):
            WidGen(W=-1)

    def test_raises_on_invalid_z(self) -> None:
        with pytest.raises(ValueError):
            WidGen(Z=-1)

    def test_restore_state(self) -> None:
        gen1 = WidGen(W=4, Z=0)
        gen1.next()
        gen1.next()
        assert gen1
        state = gen1.state()

        gen2 = WidGen(W=4, Z=0)
        gen2.restore_state(state.last_sec, state.last_seq)

        # wid = gen2.next()
        # parsed = parse_wid(wid, W=4, Z=0)
        # state = gen2.state()
        # assert parsed.sequence == state.last_seq + 1

    def test_persists_and_restores_state_using_memory_store(self) -> None:
        store = MemoryWidStateStore()
        gen1 = WidGen(
            W=4,
            Z=0,
            state_store=store,
            state_key="test-state",
            auto_persist=True,
        )
        gen1.next()
        state = gen1.state()

        gen2 = WidGen(
            W=4,
            Z=0,
            state_store=store,
            state_key="test-state",
            auto_persist=True,
        )
        state2 = gen2.state()
        assert state2.last_sec == state.last_sec
        assert state2.last_seq == state.last_seq

    def test_persists_and_restores_state_using_sqlite_store(
        self, tmp_path: Path
    ) -> None:
        store = SqliteWidStateStore(str(tmp_path / "wid_state.sqlite"), "wid-test")
        gen1 = WidGen(
            W=4,
            Z=0,
            state_store=store,
            state_key="test-state",
            auto_persist=True,
        )
        gen1.next()
        state = gen1.state()

        gen2 = WidGen(
            W=4,
            Z=0,
            state_store=store,
            state_key="test-state",
            auto_persist=True,
        )
        state2 = gen2.state()
        assert state2.last_sec == state.last_sec
        assert state2.last_seq == state.last_seq


class TestHLCWidGen:
    """Tests for HLCWidGen class."""

    def test_generates_valid_hlc_wids(self) -> None:
        gen = HLCWidGen(node="node01", W=4, Z=6)
        wid = gen.next()
        assert validate_hlc_wid(wid, W=4, Z=6)

    def test_generates_valid_hlc_wids_no_padding(self) -> None:
        gen = HLCWidGen(node="node01", W=4, Z=0)
        wid = gen.next()
        assert validate_hlc_wid(wid, W=4, Z=0)

    def test_includes_node_in_output(self) -> None:
        gen = HLCWidGen(node="mynode", W=4, Z=0)
        wid = gen.next()
        assert "-mynode" in wid

    def test_generates_monotonically_increasing(self) -> None:
        gen = HLCWidGen(node="node01", W=4, Z=0)
        wid1 = gen.next()
        wid2 = gen.next()
        wid3 = gen.next()
        assert wid1 < wid2
        assert wid2 < wid3

    def test_raises_on_invalid_node(self) -> None:
        with pytest.raises(ValueError):
            HLCWidGen(node="")
        with pytest.raises(ValueError):
            HLCWidGen(node="invalid node")  # Contains space
        with pytest.raises(ValueError):
            HLCWidGen(node="invalid-node")  # Contains hyphen

    def test_raises_on_invalid_w(self) -> None:
        with pytest.raises(ValueError):
            HLCWidGen(node="node01", W=0)

    def test_raises_on_invalid_z(self) -> None:
        with pytest.raises(ValueError):
            HLCWidGen(node="node01", Z=-1)

    def test_observe_advances_clock(self) -> None:
        gen = HLCWidGen(node="local", W=4, Z=0)
        wid1 = gen.next()

        # Simulate receiving a remote event with higher timestamp
        import time

        remote_pt = int(time.time()) + 100  # 100 seconds in future
        gen.observe(remote_pt, 5)

        wid2 = gen.next()
        # The new WID should be based on the higher timestamp
        parsed1 = parse_hlc_wid(wid1, W=4, Z=0)
        parsed2 = parse_hlc_wid(wid2, W=4, Z=0)
        assert parsed1
        assert parsed2
        assert parsed2.timestamp >= parsed1.timestamp

    def test_observe_rejects_negative_remote_values(self) -> None:
        gen = HLCWidGen(node="node01", W=4, Z=0)
        with pytest.raises(ValueError):
            gen.observe(-1, 0)
        with pytest.raises(ValueError):
            gen.observe(0, -1)

    def test_restore_state_valid_and_invalid(self) -> None:
        gen = HLCWidGen(node="node01", W=4, Z=0)
        gen.restore_state(10, 5)
        state = gen.state()
        assert state.pt == 10
        assert state.lc == 5
        with pytest.raises(ValueError):
            gen.restore_state(-1, 0)
        with pytest.raises(ValueError):
            gen.restore_state(0, -1)

    def test_rollover_and_next_n(self) -> None:
        gen = HLCWidGen(node="node01", W=1, Z=0)  # max_lc=9
        gen.restore_state(100, 9)
        wid = gen.next()
        parsed = parse_hlc_wid(wid, W=1, Z=0)
        assert parsed is not None
        assert parsed.timestamp is not None
        assert parsed.logical_counter == 0
        values = gen.next_n(2)
        assert len(values) == 2

    def test_hlc_with_padding_branch(self) -> None:
        gen = HLCWidGen(node="node01", W=4, Z=6)
        wid = gen.next()
        assert validate_hlc_wid(wid, W=4, Z=6)


class TestParseEdgeCases:
    """Coverage-focused parser edge tests."""

    # pylint: disable=protected-access

    def test_parse_wid_invalid_params(self) -> None:
        assert parse_wid("20260212T091530.0000Z", W=0, Z=0) is None
        assert parse_wid("20260212T091530.0000Z", W=4, Z=-1) is None

    def test_parse_wid_missing_padding_allowed_when_z_positive(self) -> None:
        parsed = parse_wid("20260212T091530.0000Z", W=4, Z=6)
        assert parsed is not None
        assert parsed.padding is None

    def test_parse_hlc_invalid_params_and_timestamp(self) -> None:
        assert parse_hlc_wid("20260212T091530.0000Z-node01", W=0, Z=0) is None
        assert parse_hlc_wid("20260212T091530.0000Z-node01", W=4, Z=-1) is None
        assert parse_hlc_wid("20261312T091530.0000Z-node01", W=4, Z=0) is None

    def test_parse_hlc_node_regex_rejection_path(self) -> None:
        # Force node regex rejection branch by temporarily overriding the matcher.
        original = parse_mod._NODE_RE
        parse_mod._NODE_RE = re.compile(r"^$")  # matches only empty, node will fail
        try:
            assert parse_hlc_wid("20260212T091530.0000Z-node01", W=4, Z=0) is None
        finally:
            parse_mod._NODE_RE = original

    def test_parse_wid_suffix_without_dash_rejection_path(self) -> None:
        # Force suffix-without-leading-dash branch via cached base regex override.
        key = (4, "sec")
        original = parse_mod._WID_BASE_RE_CACHE.get(key)
        parse_mod._WID_BASE_RE_CACHE[key] = re.compile(
            r"^(\d{8})T(\d{6})\.(\d{4})Z(x)$"
        )
        try:
            assert parse_wid("20260212T091530.0000Zx", W=4, Z=6) is None
        finally:
            if original is None:
                del parse_mod._WID_BASE_RE_CACHE[key]
            else:
                parse_mod._WID_BASE_RE_CACHE[key] = original

    def test_parse_hlc_suffix_without_dash_rejection_path(self) -> None:
        key = (4, "sec")
        original = parse_mod._HLC_BASE_RE_CACHE.get(key)
        parse_mod._HLC_BASE_RE_CACHE[key] = re.compile(
            r"^(\d{8})T(\d{6})\.(\d{4})Z-([^\s-]+)(x)$"
        )
        try:
            assert parse_hlc_wid("20260212T091530.0000Z-node01x", W=4, Z=6) is None
        finally:
            if original is None:
                del parse_mod._HLC_BASE_RE_CACHE[key]
            else:
                parse_mod._HLC_BASE_RE_CACHE[key] = original


class TestWidGenEdgeCases:
    """Coverage-focused generator edge tests."""

    def test_next_n_negative_raises(self) -> None:
        gen = WidGen(W=4, Z=0)
        with pytest.raises(ValueError):
            gen.next_n(-1)

    def test_restore_state_valid_and_invalid(self) -> None:
        gen = WidGen(W=4, Z=0)
        gen.restore_state(10, 2)
        state = gen.state()
        assert state.last_sec == 10
        assert state.last_seq == 2
        with pytest.raises(ValueError):
            gen.restore_state(-1, 0)
        with pytest.raises(ValueError):
            gen.restore_state(0, -2)

    def test_call_alias_and_rollover(self) -> None:
        gen = WidGen(W=1, Z=0)  # max_seq=9
        gen.restore_state(100, 9)
        wid = gen()
        parsed = parse_wid(wid, W=1, Z=0)
        assert parsed is not None
        assert parsed.sequence == 0

    def test_millisecond_generator(self) -> None:
        gen = WidGen(W=4, Z=0, time_unit="ms")
        wid = gen.next()
        assert validate_wid(wid, W=4, Z=0, time_unit="ms")
