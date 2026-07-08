//! SQL state persistence (`E=sql`): compare-and-swap WID allocation
//! through a shared SQLite database, safe for concurrent multi-process /
//! multi-language writers.

use std::fs;
use std::io::{self, Write};
use std::path::PathBuf;
use std::thread;
use std::time::Duration;

use rusqlite::OptionalExtension;
use wid::WidGen;

use super::args::CanonOpts;
use super::error::{CliError, fail};
use super::service::{resolve_data_dir, workspace_root};

pub(crate) fn sql_state_path(c: &CanonOpts) -> PathBuf {
    let root = workspace_root();
    resolve_data_dir(&root, &c.d).join("wid_state.sqlite")
}

/// The state key is deliberately language-agnostic (`wid:W:Z:T`, no
/// implementation tag): all six implementations share one row per generator
/// shape, so mixing languages on the same database cannot mint duplicate WIDs.
pub(crate) fn sql_state_key(c: &CanonOpts) -> String {
    format!("wid:{}:{}:{}", c.w, c.z, c.t.as_str())
}

/// Open the SQL state database (bundled SQLite; no external `sqlite3` binary),
/// set a busy timeout for cross-process contention, and ensure the schema.
pub(crate) fn sql_open(c: &CanonOpts) -> Result<rusqlite::Connection, String> {
    let db_path = sql_state_path(c);
    let conn = rusqlite::Connection::open(&db_path)
        .map_err(|e| format!("failed to open sql state db: {e}"))?;
    conn.busy_timeout(Duration::from_millis(5000))
        .map_err(|e| format!("sql busy_timeout failed: {e}"))?;
    conn.execute_batch(
        "CREATE TABLE IF NOT EXISTS wid_state (\
             k TEXT PRIMARY KEY, last_tick INTEGER NOT NULL, last_seq INTEGER NOT NULL);",
    )
    .map_err(|e| format!("sql init failed: {e}"))?;
    Ok(conn)
}

/// Allocate the next WID via compare-and-swap on the persisted generator
/// state row.  The UPDATE's WHERE clause encodes the expected previous
/// (last_tick, last_seq); if another process changed the row between our
/// SELECT and UPDATE, `rows_affected` returns 0 and we retry (up to 64
/// times — the same budget used by the Python/Go/TypeScript/C
/// implementations).  The busy timeout absorbs transient lock contention.
/// All values are bound as parameters (no SQL string interpolation).
pub(crate) fn sql_allocate_next_wid(
    conn: &rusqlite::Connection,
    c: &CanonOpts,
    key: &str,
) -> Result<String, String> {
    // Seed the row if it does not exist yet.
    conn.execute(
        "INSERT OR IGNORE INTO wid_state(k,last_tick,last_seq) VALUES(?1,0,-1)",
        rusqlite::params![key],
    )
    .map_err(|e| format!("sql seed failed: {e}"))?;

    for _ in 0..64 {
        let (last_tick, last_seq): (i64, i64) = conn
            .query_row(
                "SELECT last_tick, last_seq FROM wid_state WHERE k=?1",
                [key],
                |row| Ok((row.get(0)?, row.get(1)?)),
            )
            .optional()
            .map_err(|e| format!("sql load failed: {e}"))?
            .unwrap_or((0, -1));

        let mut generator = WidGen::new_with_time_unit(c.w, c.z, c.t).map_err(|e| e.to_string())?;
        generator
            .restore_state(last_tick, last_seq)
            .map_err(|_| "invalid SQL state values".to_string())?;
        let id = generator.next_wid();
        let (next_tick, next_seq) = generator.state();

        let rows = conn
            .execute(
                "UPDATE wid_state SET last_tick=?2, last_seq=?3 \
                 WHERE k=?1 AND last_tick=?4 AND last_seq=?5",
                rusqlite::params![key, next_tick, next_seq, last_tick, last_seq],
            )
            .map_err(|e| format!("sql update failed: {e}"))?;

        if rows == 1 {
            return Ok(id);
        }
    }

    Err("sql allocation contention: retry budget exhausted".to_string())
}

pub(crate) fn run_canonical_sql_next(c: &CanonOpts) -> Result<(), CliError> {
    let root = workspace_root();
    let dd = resolve_data_dir(&root, &c.d);
    fs::create_dir_all(&dd).map_err(|e| fail(format!("failed to create data dir: {e}")))?;
    let conn = sql_open(c).map_err(fail)?;
    let key = sql_state_key(c);
    let id = sql_allocate_next_wid(&conn, c, &key).map_err(fail)?;
    println!("{id}");
    Ok(())
}

pub(crate) fn run_canonical_sql_stream(c: &CanonOpts) -> Result<(), CliError> {
    let root = workspace_root();
    let dd = resolve_data_dir(&root, &c.d);
    fs::create_dir_all(&dd).map_err(|e| fail(format!("failed to create data dir: {e}")))?;
    let conn = sql_open(c).map_err(fail)?;
    let key = sql_state_key(c);
    let mut emitted = 0usize;
    loop {
        if c.n > 0 && emitted >= c.n {
            break;
        }
        let id = sql_allocate_next_wid(&conn, c, &key).map_err(fail)?;
        println!("{id}");
        io::stdout().flush().map_err(|e| fail(e.to_string()))?;
        emitted += 1;
        if c.l_explicit && c.l > 0 && (c.n == 0 || emitted < c.n) {
            thread::sleep(Duration::from_secs(c.l as u64));
        }
    }
    Ok(())
}
