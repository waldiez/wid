/** Supported time-precision units for WID/HLC generators. */
export type TimeUnit = "sec" | "ms";

/** Parse a user-supplied time unit, rejecting anything but "sec"/"ms". */
export function parseTimeUnit(input: string): TimeUnit {
  if (input === "sec" || input === "ms") {
    return input;
  }
  throw new Error("time-unit must be sec or ms");
}

/** Number of digits in the timestamp's time field (HHMMSS or HHMMSSmmm). */
export function timeDigits(unit: TimeUnit): number {
  return unit === "ms" ? 9 : 6;
}

/** Largest second tick that still formats as a 4-digit year (9999-12-31T23:59:59Z). */
export const MAX_SEC_TICK = 253402300799;

/**
 * Saturate a tick to the formattable range instead of emitting malformed
 * >8-digit-year IDs: a corrupted resume state (e.g. a hand-edited SQL row)
 * degrades to a pinned timestamp, matching the Rust implementation.
 */
export function clampTick(tick: number, unit: TimeUnit): number {
  const max = unit === "ms" ? MAX_SEC_TICK * 1000 + 999 : MAX_SEC_TICK;
  if (tick < 0) return 0;
  if (tick > max) return max;
  return tick;
}

/** Cache for padding-hex validation patterns keyed by width. Shared by the
 * WID and HLC-WID parsers (each used to carry an identical private copy). */
const HEX_RE_CACHE = new Map<number, RegExp>();

/** Compiled `^[0-9a-f]{Z}$` pattern for the random-pad suffix. */
export function hexRe(Z: number): RegExp {
  const cached = HEX_RE_CACHE.get(Z);
  if (cached) return cached;
  const re = new RegExp(`^[0-9a-f]{${Z}}$`);
  HEX_RE_CACHE.set(Z, re);
  return re;
}

/** Z random lowercase hex chars from the runtime CSPRNG. Shared by the WID
 * and HLC-WID generators (each used to carry an identical private copy). */
export function randomHexChars(Z: number): string {
  if (!globalThis.crypto?.getRandomValues) {
    throw new Error("Secure random generator unavailable in this runtime");
  }
  const bytes = new Uint8Array(Math.ceil(Z / 2));
  globalThis.crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0"))
    .join("")
    .slice(0, Z);
}

/**
 * Format an (already clamped) tick as the WID timestamp field
 * (`YYYYMMDDTHHMMSS` or `YYYYMMDDTHHMMSSmmm`). Pure; the per-generator
 * last-tick cache stays in the generators, which used to duplicate this body.
 */
export function formatTickTimestamp(tick: number, unit: TimeUnit): string {
  const sec = unit === "ms" ? Math.floor(tick / 1000) : tick;
  const ms = unit === "ms" ? tick % 1000 : 0;
  const d = new Date(sec * 1000);
  const year = d.getUTCFullYear();
  const month = String(d.getUTCMonth() + 1).padStart(2, "0");
  const day = String(d.getUTCDate()).padStart(2, "0");
  const hour = String(d.getUTCHours()).padStart(2, "0");
  const minute = String(d.getUTCMinutes()).padStart(2, "0");
  const second = String(d.getUTCSeconds()).padStart(2, "0");
  const base = `${year}${month}${day}T${hour}${minute}${second}`;
  return unit === "ms" ? `${base}${String(ms).padStart(3, "0")}` : base;
}

/**
 * Parse the WID timestamp fields (YYYYMMDD + HHMMSS[mmm]) into a UTC Date;
 * null if the fields do not name a real calendar moment. Shared by the WID
 * and HLC-WID parsers.
 */
export function parseWidTimestamp(
  dateStr: string,
  timeStr: string,
  timeUnit: TimeUnit
): Date | null {
  const year = parseInt(dateStr.slice(0, 4), 10);
  const month = parseInt(dateStr.slice(4, 6), 10);
  const day = parseInt(dateStr.slice(6, 8), 10);
  const hour = parseInt(timeStr.slice(0, 2), 10);
  const minute = parseInt(timeStr.slice(2, 4), 10);
  const second = parseInt(timeStr.slice(4, 6), 10);
  const millis = timeUnit === "ms" ? parseInt(timeStr.slice(6, 9), 10) : 0;

  // SPEC.md: valid years are 0001-9999 (Python's datetime cannot represent
  // year 0, so all implementations reject it uniformly).
  if (year < 1) return null;
  if (month < 1 || month > 12) return null;
  if (day < 1 || day > 31) return null;
  if (hour > 23 || minute > 59 || second > 59) return null;
  if (millis < 0 || millis > 999) return null;

  const timestamp = new Date(Date.UTC(year, month - 1, day, hour, minute, second, millis));
  // Date.UTC maps years 0-99 to 1900-1999; pin the literal 4-digit year so
  // e.g. 0050 parses as year 50 (matching Rust/Python/Go), not 1950.
  timestamp.setUTCFullYear(year, month - 1, day);
  if (isNaN(timestamp.getTime())) return null;
  if (
    timestamp.getUTCFullYear() !== year ||
    timestamp.getUTCMonth() + 1 !== month ||
    timestamp.getUTCDate() !== day
  ) {
    return null;
  }
  return timestamp;
}
