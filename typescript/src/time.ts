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
