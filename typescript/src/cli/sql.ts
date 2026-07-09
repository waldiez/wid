import { resolve } from "node:path";
import { WidGen } from "../index";
import { type Canon } from "./types";

/** Thin SQLite connection wrapper used by CLI helpers. */
export type SqliteDb = {
  exec: (sql: string) => void;
  prepare: (
    sql: string
  ) => {
    get: (...args: unknown[]) => unknown;
    run: (...args: unknown[]) => { changes?: number };
  };
  close?: () => void;
};

/** Constructor signature for SQLite database handles. */
export type SqliteCtor = new (
  path: string,
  options?: { timeout?: number }
) => SqliteDb;

export function resolveNodeSqliteDatabaseSync(): SqliteCtor {
  const proc = (globalThis as { process?: unknown }).process as
    | {
        versions?: { node?: string };
        getBuiltinModule?: (name: string) => unknown;
      }
    | undefined;
  if (!proc?.versions?.node) {
    throw new Error("SQLite requires Node.js");
  }
  const builtin =
    typeof proc.getBuiltinModule === "function"
      ? proc.getBuiltinModule("node:sqlite")
      : null;
  if (builtin && typeof builtin === "object" && "DatabaseSync" in builtin) {
    return (builtin as { DatabaseSync: SqliteCtor }).DatabaseSync;
  }
  throw new Error("node:sqlite unavailable in this Node runtime");
}

export function sqlStatePath(c: Canon): string {
  const dDir =
    c.D && c.D.length > 0 ? resolve(c.D) : resolve(".local/services");
  return resolve(dDir, "wid_state.sqlite");
}

export function sqlStateKey(c: Canon): string {
  return `wid:${c.W}:${c.Z}:${c.T}`;
}

function setupSqlDb(db: SqliteDb, key: string): void {
  db.exec("PRAGMA journal_mode=WAL;");
  db.exec(
    "CREATE TABLE IF NOT EXISTS wid_state (k TEXT PRIMARY KEY, last_tick INTEGER NOT NULL, last_seq INTEGER NOT NULL)"
  );
  db.prepare(
    "INSERT OR IGNORE INTO wid_state(k,last_tick,last_seq) VALUES(?,0,-1)"
  ).run(key);
}

function trySqlAllocate(
  key: string,
  c: Canon,
  selectStmt: { get: (...args: unknown[]) => unknown },
  casStmt: { run: (...args: unknown[]) => { changes?: number } }
): string | undefined {
  const row = selectStmt.get(key) as
    | { last_tick?: number; last_seq?: number }
    | undefined;
  if (
    !row ||
    typeof row.last_tick !== "number" ||
    typeof row.last_seq !== "number"
  ) {
    throw new Error("invalid SQL state row");
  }
  const gen = new WidGen({ W: c.W, Z: c.Z, timeUnit: c.T });
  gen.restoreState(row.last_tick, row.last_seq);
  const id = gen.next();
  const nextState = gen.state;
  const updated = casStmt.run(
    nextState.lastSec,
    nextState.lastSeq,
    key,
    row.last_tick,
    row.last_seq
  );
  if ((updated.changes ?? 0) === 1) {
    return id;
  }
  return undefined;
}

export function sqlAllocateNextWid(c: Canon): string {
  const DatabaseSync = resolveNodeSqliteDatabaseSync();
  const db = new DatabaseSync(sqlStatePath(c), { timeout: 5000 });
  try {
    const key = sqlStateKey(c);
    setupSqlDb(db, key);
    const selectStmt = db.prepare(
      "SELECT last_tick,last_seq FROM wid_state WHERE k=?"
    );
    const casStmt = db.prepare(
      "UPDATE wid_state SET last_tick=?,last_seq=? WHERE k=? AND last_tick=? AND last_seq=?"
    );

    for (let i = 0; i < 256; i += 1) {
      try {
        const id = trySqlAllocate(key, c, selectStmt, casStmt);
        if (id !== undefined) {
          return id;
        }
      } catch (e) {
        const errcode = (e as { errcode?: number }).errcode;
        const msg = (e as Error).message ?? "";
        if (errcode === 5 || msg.includes("database is locked")) {
          continue;
        }
        throw e;
      }
    }
    throw new Error("sql allocation contention: retry budget exhausted");
  } finally {
    db.close?.();
  }
}
