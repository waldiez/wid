/**
 * WID (Waldiez Identifier) generation and validation.
 * Format: YYYYMMDDTHHMMSS[mmm].<seqW>Z[-<padZ>]
 */

import {
  type TimeUnit,
  clampTick,
  formatTickTimestamp,
  hexRe,
  parseWidTimestamp,
  randomHexChars,
  timeDigits,
} from "./time";

/**
 * Maximum sequence/logical-counter width. 10^18 - 1 is the largest all-nines
 * value that fits in an int64 (10^19 overflows), so W > 18 cannot be
 * represented by the i64-based implementations and is rejected uniformly
 * across all six languages.
 */
export const MAX_W = 18;
/** Maximum padding width (hex chars); matches the C implementation's WID_MAX_Z. */
export const MAX_Z = 64;

/** Parsed WID components after a successful parse. */
export interface ParsedWid {
  /** Raw identifier string that was parsed. */
  raw: string;
  /** UTC timestamp extracted from the WID envelope. */
  timestamp: Date;
  /** Sequential component embedded in the identifier. */
  /**
   * Sequential component embedded in the identifier. Note: JS numbers are
   * IEEE-754 doubles, so values above 2^53 (sequences with 16+ digits) lose
   * precision here; validation itself is exact (string/regex based).
   */
  sequence: number;
  /** Optional padding hex string when Z > 0. */
  padding: string | null;
}

/** In-memory snapshot of the last seen second/sequence for a generator. */
export interface WidStateSnapshot {
  lastSec: number;
  lastSeq: number;
}

/** Storage contract consumed by `WidGen` when persistence is enabled. */
export interface WidStateStore {
  load(key: string): WidStateSnapshot | null;
  save(key: string, state: WidStateSnapshot): void;
}

/** Basic in-memory store that keeps Wid state during runtime. */
export class MemoryWidStateStore implements WidStateStore {
  private readonly memory = new Map<string, WidStateSnapshot>();

  load(key: string): WidStateSnapshot | null {
    const hit = this.memory.get(key);
    return hit ? { ...hit } : null;
  }

  save(key: string, state: WidStateSnapshot): void {
    this.memory.set(key, { ...state });
  }
}

/** Browser localStorage-backed store; falls back to no-op outside browsers. */
class BrowserLocalStorageWidStateStore implements WidStateStore {
  private readonly prefix: string;

  constructor(prefix = "wid") {
    this.prefix = prefix;
  }

  private keyOf(key: string): string {
    return `${this.prefix}:${key}`;
  }

  private localStorageLike():
    | { getItem: (k: string) => string | null; setItem: (k: string, v: string) => void }
    | null {
    const g = globalThis as unknown as Record<string, unknown>;
    const ls = g.localStorage as
      | { getItem: (k: string) => string | null; setItem: (k: string, v: string) => void }
      | undefined;
    return ls ?? null;
  }

  load(key: string): WidStateSnapshot | null {
    const ls = this.localStorageLike();
    if (!ls) return null;
    const raw = ls.getItem(this.keyOf(key));
    if (!raw) return null;
    try {
      const parsed = JSON.parse(raw) as Partial<WidStateSnapshot>;
      if (
        typeof parsed.lastSec === "number" &&
        Number.isFinite(parsed.lastSec) &&
        typeof parsed.lastSeq === "number" &&
        Number.isFinite(parsed.lastSeq)
      ) {
        return { lastSec: parsed.lastSec, lastSeq: parsed.lastSeq };
      }
    } catch {
      return null;
    }
    return null;
  }

  save(key: string, state: WidStateSnapshot): void {
    const ls = this.localStorageLike();
    if (!ls) return;
    ls.setItem(this.keyOf(key), JSON.stringify(state));
  }
}

/**
 * Creates a browser localStorage-backed state store.
 * In non-browser runtimes this behaves as a no-op store.
 */
/** Factory that wires the browser storage-backed Wid store for web runtimes. */
export function createBrowserWidStateStore(prefix = "wid"): WidStateStore {
  return new BrowserLocalStorageWidStateStore(prefix);
}

/**
 * SQLite-backed store for Node environments that support `node:sqlite`.
 *
 * Warning: `save()` is a plain last-writer-wins upsert, so this store is safe
 * for a **single process** persisting/resuming its own generator only. It does
 * not serialize concurrent writers: two processes generating against the same
 * database can interleave and mint duplicate WIDs. For multi-process /
 * multi-language coordination use the CLI's `E=sql` mode, which allocates each
 * WID through a compare-and-swap on the state row.
 */
class NodeSqliteWidStateStore implements WidStateStore {
  private readonly db: {
    exec: (sql: string) => void;
    prepare: (sql: string) => { get: (...args: unknown[]) => unknown; run: (...args: unknown[]) => unknown };
    close?: () => void;
  };
  private readonly prefix: string;

  constructor(databasePath: string, prefix = "wid") {
    this.prefix = prefix;
    /** Node sqlite constructor used for CLI persistence. */
    const DatabaseSync = resolveNodeSqliteDatabaseSync();
    this.db = new DatabaseSync(databasePath);
    this.db.exec(
      "CREATE TABLE IF NOT EXISTS wid_state (k TEXT PRIMARY KEY, last_tick INTEGER NOT NULL, last_seq INTEGER NOT NULL)"
    );
  }

  private fullKey(key: string): string {
    return `${this.prefix}:${key}`;
  }

  load(key: string): WidStateSnapshot | null {
    const row = this.db
      .prepare("SELECT last_tick, last_seq FROM wid_state WHERE k = ?")
      .get(this.fullKey(key)) as { last_tick?: number; last_seq?: number } | undefined;
    if (!row) return null;
    if (typeof row.last_tick !== "number" || typeof row.last_seq !== "number") return null;
    return { lastSec: row.last_tick, lastSeq: row.last_seq };
  }

  save(key: string, state: WidStateSnapshot): void {
    this.db
      .prepare(
        "INSERT INTO wid_state (k, last_tick, last_seq) VALUES (?, ?, ?) ON CONFLICT(k) DO UPDATE SET last_tick=excluded.last_tick, last_seq=excluded.last_seq"
      )
      .run(this.fullKey(key), state.lastSec, state.lastSeq);
  }

  close(): void {
    this.db.close?.();
  }
}

function resolveNodeSqliteDatabaseSync(): new (path: string) => {
  exec: (sql: string) => void;
  prepare: (sql: string) => { get: (...args: unknown[]) => unknown; run: (...args: unknown[]) => unknown };
  close?: () => void;
} {
  const proc = (globalThis as { process?: unknown }).process as
    | { versions?: { node?: string }; getBuiltinModule?: (name: string) => unknown }
    | undefined;
  if (!proc?.versions?.node) {
    throw new Error("SQLite state store requires Node.js");
  }

  const builtin = typeof proc.getBuiltinModule === "function" ? proc.getBuiltinModule("node:sqlite") : null;
  if (builtin && typeof builtin === "object" && "DatabaseSync" in builtin) {
    return (builtin as { DatabaseSync: new (path: string) => NodeSqliteWidStateStore["db"] }).DatabaseSync;
  }

  throw new Error("node:sqlite unavailable in this Node runtime");
}

/**
 * Node factory that requires the `node:sqlite` module for persistence.
 * Single-process only — see {@link NodeSqliteWidStateStore}'s warning about
 * concurrent writers; multi-process coordination is the CLI `E=sql` path.
 */
export function createNodeSqliteWidStateStore(databasePath: string, prefix = "wid"): WidStateStore {
  return new NodeSqliteWidStateStore(databasePath, prefix);
}

/** Configuration options accepted by `WidGen`. */
export interface WidGenOptions {
  /** Width of the sequence segment (default 4). */
  W?: number;
  /** Padding length (default 6). */
  Z?: number;
  /** Time unit precision, either `sec` or `ms`. */
  timeUnit?: TimeUnit;
  /** Optional persistence layer for generator state. */
  stateStore?: WidStateStore;
  /** Key used when storing state. */
  stateKey?: string;
  /** Persist state after each generation when true. */
  autoPersist?: boolean;
}

/** Extended configuration for streaming helpers around `WidGen`. */
export interface AsyncWidStreamOptions extends WidGenOptions {
  /** Number of IDs to emit (0 for infinite). */
  count?: number;
  /** Delay between emits in milliseconds. */
  intervalMs?: number;
}

/** Cache of regex instances for base WID formats per width/unit. */
const WID_BASE_RE_CACHE = new Map<string, RegExp>();

function widBaseRe(W: number, unit: TimeUnit): RegExp {
  const key = `${W}:${unit}`;
  const cached = WID_BASE_RE_CACHE.get(key);
  if (cached) return cached;
  const re = new RegExp(`^(\\d{8})T(\\d{${timeDigits(unit)}})\\.(\\d{${W}})Z(.*)?$`);
  WID_BASE_RE_CACHE.set(key, re);
  return re;
}

/**
 * Parse the optional suffix of a plain WID. Per the spec
 * (`WID ::= TIMESTAMP "." SEQ "Z" [ "-" PAD ]`) a plain WID has no node/scope
 * segment — the only permitted suffix is `-<padZ>` lowercase-hex padding, and
 * only when Z > 0. Anything else (an HLC node, uppercase hex, non-hex, or a
 * suffix when Z = 0) is rejected, matching the reference implementation and the
 * other language implementations. Node identifiers belong to HLC-WID (see
 * `hlc.ts`).
 */
function parsePadding(suffix: string, Z: number): { padding: string | null } | null {
  if (!suffix) {
    return { padding: null };
  }
  if (Z <= 0) {
    return null;
  }
  if (!suffix.startsWith("-")) {
    return null;
  }
  const body = suffix.slice(1);
  if (!hexRe(Z).test(body)) {
    return null;
  }
  return { padding: body };
}

function parseCore(wid: string, W: number, Z: number, timeUnit: TimeUnit): ParsedWid | null {
  if (W <= 0 || W > MAX_W || Z < 0 || Z > MAX_Z) return null;

  const match = widBaseRe(W, timeUnit).exec(wid);
  if (!match) return null;

  const [, dateStr, timeStr, seqStr, suffixRaw] = match;
  const suffix = suffixRaw ?? "";

  const timestamp = parseWidTimestamp(dateStr, timeStr, timeUnit);
  if (!timestamp) return null;

  const parsedSuffix = parsePadding(suffix, Z);
  if (!parsedSuffix) return null;

  return {
    raw: wid,
    timestamp,
    sequence: parseInt(seqStr, 10),
    padding: parsedSuffix.padding,
  };
}

/** Validate a plain WID string against the given W/Z/time-unit shape. */
export function validateWid(wid: string, W = 4, Z = 6, timeUnit: TimeUnit = "sec"): boolean {
  return parseCore(wid, W, Z, timeUnit) !== null;
}

/** Parse a plain WID into its fields; null if it does not conform. */
export function parseWid(wid: string, W = 4, Z = 6, timeUnit: TimeUnit = "sec"): ParsedWid | null {
  return parseCore(wid, W, Z, timeUnit);
}

/** Mint one WID from a throwaway generator (async convenience). */
export async function asyncNextWid(options: WidGenOptions = {}): Promise<string> {
  return new WidGen(options).next();
}

/** Stream WIDs asynchronously; count 0 means unbounded. */
export async function* asyncWidStream(
  options: AsyncWidStreamOptions = {}
): AsyncGenerator<string> {
  const { count = 0, intervalMs = 0, ...genOpts } = options;
  if (count < 0) throw new Error("count must be >= 0");
  if (intervalMs < 0) throw new Error("intervalMs must be >= 0");

  const gen = new WidGen(genOpts);
  let emitted = 0;
  while (count === 0 || emitted < count) {
    yield gen.next();
    emitted += 1;
    if (intervalMs > 0) {
      await new Promise((resolve) => setTimeout(resolve, intervalMs));
    }
  }
}

/** Stateful generator for WID IDs that keeps monotonicity guarantees. */
export class WidGen {
  private readonly W: number;
  private readonly Z: number;
  private readonly timeUnit: TimeUnit;
  private readonly maxSeq: number;
  private readonly stateStore: WidStateStore | null;
  private readonly stateKey: string;
  private readonly autoPersist: boolean;

  private lastSec = 0;
  private lastSeq = -1;
  private cachedSec = -1;
  private cachedTs = "";

  /** Create a generator with optional persistence and precision control. */
  constructor(options: WidGenOptions = {}) {
    const {
      W = 4,
      Z = 6,
      timeUnit = "sec",
      stateStore,
      stateKey = "wid",
      autoPersist = false,
    } = options;

    // Bounds match all six implementations: W > 18 would overflow an int64
    // sequence; Z > 64 exceeds the C implementation's WID_MAX_Z.
    if (W <= 0 || W > MAX_W) throw new Error("W must be between 1 and 18");
    if (Z < 0 || Z > MAX_Z) throw new Error("Z must be between 0 and 64");

    this.W = W;
    this.Z = Z;
    this.timeUnit = timeUnit;
    // 10^W - 1 is not exactly representable above 2^53 (Math.pow(10,18) - 1
    // evaluates to 10^18). Cap at MAX_SAFE_INTEGER - 1 so `seq > maxSeq`
    // still triggers rollover before `seq + 1` stops incrementing.
    this.maxSeq = Math.min(Math.pow(10, W) - 1, Number.MAX_SAFE_INTEGER - 1);
    this.stateStore = stateStore ?? null;
    this.stateKey = stateKey;
    this.autoPersist = autoPersist;

    if (this.autoPersist && this.stateStore) {
      const loaded = this.stateStore.load(this.stateKey);
      if (
        loaded &&
        Number.isFinite(loaded.lastSec) &&
        Number.isFinite(loaded.lastSeq) &&
        loaded.lastSec >= 0 &&
        loaded.lastSeq >= -1
      ) {
        this.lastSec = loaded.lastSec;
        this.lastSeq = loaded.lastSeq;
      }
    }
  }

  private persistState(): void {
    if (!this.autoPersist || !this.stateStore) return;
    try {
      this.stateStore.save(this.stateKey, { lastSec: this.lastSec, lastSeq: this.lastSeq });
    } catch {
      // Keep generator functional even if persistence fails.
    }
  }

  private tsForTick(rawTick: number): string {
    // Saturate instead of formatting a malformed >8-digit-year ID: a
    // corrupted resume state degrades to a pinned timestamp (see clampTick).
    const tick = clampTick(rawTick, this.timeUnit);
    if (tick !== this.cachedSec) {
      this.cachedSec = tick;
      this.cachedTs = formatTickTimestamp(tick, this.timeUnit);
    }
    return this.cachedTs;
  }

  private nowTick(): number {
    if (this.timeUnit === "ms") {
      return Date.now();
    }
    return Math.floor(Date.now() / 1000);
  }

  next(): string {
    const now = this.nowTick();
    let tick = now > this.lastSec ? now : this.lastSec;
    let seq = tick === this.lastSec ? this.lastSeq + 1 : 0;

    if (seq > this.maxSeq) {
      tick += 1;
      seq = 0;
    }

    this.lastSec = tick;
    this.lastSeq = seq;

    const ts = this.tsForTick(tick);
    const seqStr = String(seq).padStart(this.W, "0");
    let wid = `${ts}.${seqStr}Z`;

    if (this.Z > 0) {
      wid += `-${randomHexChars(this.Z)}`;
    }

    this.persistState();
    return wid;
  }

  nextN(n: number): string[] {
    return Array.from({ length: n }, () => this.next());
  }

  get state(): WidStateSnapshot {
    return { lastSec: this.lastSec, lastSeq: this.lastSeq };
  }

  restoreState(lastSec: number, lastSeq: number): void {
    this.lastSec = lastSec;
    this.lastSeq = lastSeq;
    this.persistState();
  }
}
