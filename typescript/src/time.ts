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
