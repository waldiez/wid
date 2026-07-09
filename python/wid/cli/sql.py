"""``E=sql`` generator-state persistence (shared cross-language state row)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from ..core import parse_time_unit
from ..wid import WidGen


def sql_state_path(data_dir: Path) -> Path:
    """Return the SQLite state DB path inside ``data_dir``."""
    return data_dir / "wid_state.sqlite"


def _sql_state_key(w_val: int, z_val: int, time_unit: str) -> str:
    # Deliberately language-agnostic (wid:W:Z:T, no implementation tag): all
    # six implementations share one row per generator shape, so mixing
    # languages on the same database cannot mint duplicate WIDs.
    """Build the language-agnostic state key ``wid:W:Z:T``."""
    return f"wid:{w_val}:{z_val}:{time_unit}"


def sql_allocate_next_wid(w_val: int, z_val: int, time_unit: str, db_path: Path) -> str:
    """Mint one WID via the shared SQLite compare-and-swap state row."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA busy_timeout=5000")
        q = (
            "CREATE TABLE IF NOT EXISTS wid_state ("
            "k TEXT PRIMARY KEY, "
            "last_tick INTEGER NOT NULL, "
            "last_seq INTEGER NOT NULL)"
        )
        conn.execute(q)
        key = _sql_state_key(w_val, z_val, time_unit)
        conn.execute(
            "INSERT OR IGNORE INTO wid_state(k,last_tick,last_seq) VALUES(?,0,-1)",
            (key,),
        )
        conn.commit()

        for _ in range(64):
            row = conn.execute(
                "SELECT last_tick,last_seq FROM wid_state WHERE k=?",
                (key,),
            ).fetchone()
            if row is None:
                raise RuntimeError("invalid SQL state row")

            last_sec = int(row[0])
            last_seq = int(row[1])
            gen = WidGen(
                w=w_val,
                z=z_val,
                time_unit=parse_time_unit(time_unit),
            )
            gen.restore_state(last_sec, last_seq)
            wid_id = gen.next()
            st = gen.state()
            q_s = (
                "UPDATE wid_state SET last_tick=?,last_seq=? "
                "WHERE k=? AND last_tick=? AND last_seq=?"
            )
            q_p = (st.last_sec, st.last_seq, key, last_sec, last_seq)
            cur = conn.execute(q_s, q_p)
            conn.commit()
            if cur.rowcount == 1:
                return wid_id
        raise RuntimeError("sql allocation contention: retry budget exhausted")
    finally:
        conn.close()
