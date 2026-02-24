/**
 * HLC-WID (Hybrid Logical Clock WID) generation, validation, and parsing.
 * Format: YYYYMMDDTHHMMSS[mmm].<lcW>Z-<node>[-<padZ>]
 */

import { type TimeUnit, timeDigits } from "./time";

/** Parsed components of an HLC-WID after a successful parse. */
export interface ParsedHlcWid {
  /** Raw HLC-WID string. */
  raw: string;
  /** UTC timestamp portion of the HLC-WID. */
  timestamp: Date;
  /** Logical clock counter embedded in the HLC-WID. */
  logicalCounter: number;
  /** Node identifier appended to the HLC-WID. */
  node: string;
  /** Optional padding when Z > 0. */
  padding: string | null;
}

/** Minimal Hybrid Logical Clock state snapshot. */
export interface HLCState {
  /** Physical timestamp used by the generator. */
  pt: number;
  /** Logical counter component. */
  lc: number;
}

/** Configuration options for `HLCWidGen`. */
export interface HLCWidGenOptions {
  /** Unique node identifier suffix. */
  node: string;
  /** Width of the logical counter (default 4). */
  W?: number;
  /** Optional padding length (default 0). */
  Z?: number;
  /** Time precision (defaults to `sec`). */
  timeUnit?: TimeUnit;
}

/** Cache for HLC-WID regex instances per width/time unit pair. */
const HLC_BASE_RE_CACHE = new Map<string, RegExp>();
/** Cache for hex validation patterns keyed by padding length. */
const HEX_RE_CACHE = new Map<number, RegExp>();
/** Node identifier pattern reused by HLC generators. */
const NODE_RE = /^[A-Za-z0-9_]+$/;

function hlcBaseRe(W: number, unit: TimeUnit): RegExp {
  const key = `${W}:${unit}`;
  const cached = HLC_BASE_RE_CACHE.get(key);
  if (cached) return cached;
  const re = new RegExp(`^(\\d{8})T(\\d{${timeDigits(unit)}})\\.(\\d{${W}})Z-([A-Za-z0-9_]+)(.*)$`);
  HLC_BASE_RE_CACHE.set(key, re);
  return re;
}

function hexRe(Z: number): RegExp {
  const cached = HEX_RE_CACHE.get(Z);
  if (cached) return cached;
  const re = new RegExp(`^[0-9a-f]{${Z}}$`);
  HEX_RE_CACHE.set(Z, re);
  return re;
}

function randomHexChars(Z: number): string {
  if (!globalThis.crypto?.getRandomValues) {
    throw new Error("Secure random generator unavailable in this runtime");
  }
  const bytes = new Uint8Array(Math.ceil(Z / 2));
  globalThis.crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0"))
    .join("")
    .slice(0, Z);
}

function isValidNode(node: string): boolean {
  return NODE_RE.test(node);
}

function parseTimestamp(dateStr: string, timeStr: string, timeUnit: TimeUnit): Date | null {
  const year = parseInt(dateStr.slice(0, 4), 10);
  const month = parseInt(dateStr.slice(4, 6), 10);
  const day = parseInt(dateStr.slice(6, 8), 10);
  const hour = parseInt(timeStr.slice(0, 2), 10);
  const minute = parseInt(timeStr.slice(2, 4), 10);
  const second = parseInt(timeStr.slice(4, 6), 10);
  const millis = timeUnit === "ms" ? parseInt(timeStr.slice(6, 9), 10) : 0;

  if (month < 1 || month > 12) return null;
  if (day < 1 || day > 31) return null;
  if (hour > 23 || minute > 59 || second > 59) return null;
  if (millis < 0 || millis > 999) return null;

  const timestamp = new Date(Date.UTC(year, month - 1, day, hour, minute, second, millis));
  if (isNaN(timestamp.getTime())) return null;
  if (timestamp.getUTCDate() !== day || timestamp.getUTCMonth() + 1 !== month) return null;
  return timestamp;
}

export function validateHlcWid(
  wid: string,
  W = 4,
  Z = 0,
  timeUnit: TimeUnit = "sec"
): boolean {
  return parseHlcWid(wid, W, Z, timeUnit) !== null;
}

export function parseHlcWid(
  wid: string,
  W = 4,
  Z = 0,
  timeUnit: TimeUnit = "sec"
): ParsedHlcWid | null {
  if (W <= 0 || Z < 0) return null;

  const match = hlcBaseRe(W, timeUnit).exec(wid);
  if (!match) return null;

  const [, dateStr, timeStr, lcStr, node, suffixRaw] = match;
  const suffix = suffixRaw ?? "";

  if (!isValidNode(node)) return null;

  const timestamp = parseTimestamp(dateStr, timeStr, timeUnit);
  if (!timestamp) return null;

  const logicalCounter = parseInt(lcStr, 10);

  let padding: string | null = null;
  if (suffix) {
    if (!suffix.startsWith("-")) return null;
    const seg = suffix.slice(1);
    if (Z === 0) return null;
    if (!hexRe(Z).test(seg)) return null;
    padding = seg;
  }

  return { raw: wid, timestamp, logicalCounter, node, padding };
}

/** Generator for HLC-WIDs that keeps the logical counter monotonic. */
export class HLCWidGen {
  private readonly W: number;
  private readonly Z: number;
  private readonly node: string;
  private readonly timeUnit: TimeUnit;
  private readonly maxLC: number;
  private pt = 0;
  private lc = 0;
  private cachedTick = -1;
  private cachedTs = "";

  constructor(options: HLCWidGenOptions) {
    const { node, W = 4, Z = 0, timeUnit = "sec" } = options;
    if (W <= 0) throw new Error("W must be > 0");
    if (Z < 0) throw new Error("Z must be >= 0");
    if (!isValidNode(node)) {
      throw new Error("node must match [A-Za-z0-9_]+");
    }
    this.W = W;
    this.Z = Z;
    this.node = node;
    this.timeUnit = timeUnit;
    this.maxLC = Math.pow(10, W) - 1;
  }

  private nowTick(): number {
    if (this.timeUnit === "ms") {
      return Date.now();
    }
    return Math.floor(Date.now() / 1000);
  }

  private tsForTick(tick: number): string {
    if (tick !== this.cachedTick) {
      this.cachedTick = tick;
      const sec = this.timeUnit === "ms" ? Math.floor(tick / 1000) : tick;
      const ms = this.timeUnit === "ms" ? tick % 1000 : 0;
      const d = new Date(sec * 1000);
      const year = d.getUTCFullYear();
      const mo = String(d.getUTCMonth() + 1).padStart(2, "0");
      const dy = String(d.getUTCDate()).padStart(2, "0");
      const hr = String(d.getUTCHours()).padStart(2, "0");
      const mi = String(d.getUTCMinutes()).padStart(2, "0");
      const sc = String(d.getUTCSeconds()).padStart(2, "0");
      const milli = String(ms).padStart(3, "0");
      this.cachedTs =
        this.timeUnit === "ms"
          ? `${year}${mo}${dy}T${hr}${mi}${sc}${milli}`
          : `${year}${mo}${dy}T${hr}${mi}${sc}`;
    }
    return this.cachedTs;
  }

  private rollover(): void {
    if (this.lc > this.maxLC) {
      this.pt += 1;
      this.lc = 0;
    }
  }

  observe(remotePT: number, remoteLC: number): void {
    if (remotePT < 0 || remoteLC < 0) {
      throw new Error("remote values must be non-negative");
    }
    const now = this.nowTick();
    const newPT = Math.max(now, this.pt, remotePT);

    if (newPT === this.pt && newPT === remotePT) {
      this.lc = Math.max(this.lc, remoteLC) + 1;
    } else if (newPT === this.pt) {
      this.lc += 1;
    } else if (newPT === remotePT) {
      this.lc = remoteLC + 1;
    } else {
      this.lc = 0;
    }
    this.pt = newPT;
    this.rollover();
  }

  next(): string {
    const now = this.nowTick();
    if (now > this.pt) {
      this.pt = now;
      this.lc = 0;
    } else {
      this.lc += 1;
    }
    this.rollover();

    const ts = this.tsForTick(this.pt);
    const lcStr = String(this.lc).padStart(this.W, "0");
    let wid = `${ts}.${lcStr}Z-${this.node}`;
    if (this.Z > 0) {
      wid += `-${randomHexChars(this.Z)}`;
    }
    return wid;
  }

  nextN(n: number): string[] {
    return Array.from({ length: n }, () => this.next());
  }

  get state(): HLCState {
    return { pt: this.pt, lc: this.lc };
  }

  restoreState(pt: number, lc: number): void {
    if (pt < 0 || lc < 0) throw new Error("invalid state");
    this.pt = pt;
    this.lc = lc;
  }
}

export async function asyncNextHlcWid(options: HLCWidGenOptions): Promise<string> {
  return new HLCWidGen(options).next();
}

export async function* asyncHlcWidStream(
  options: HLCWidGenOptions & { count?: number; intervalMs?: number }
): AsyncGenerator<string> {
  const { count = 0, intervalMs = 0, ...genOpts } = options;
  if (count < 0) throw new Error("count must be >= 0");
  if (intervalMs < 0) throw new Error("intervalMs must be >= 0");
  const gen = new HLCWidGen(genOpts);
  let emitted = 0;
  while (count === 0 || emitted < count) {
    yield gen.next();
    emitted++;
    if (intervalMs > 0) {
      await new Promise((resolve) => setTimeout(resolve, intervalMs));
    }
  }
}
