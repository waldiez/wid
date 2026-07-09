import { parseTimeUnit, type TimeUnit } from "../time";

/**
 * Malformed invocation (unknown command/flag/key/action, missing required
 * value, out-of-range parameter). Exits 2 per the shared cross-language
 * contract (spec/quick-usage.md "Exit codes"); operational failures exit 1.
 */
export class UsageError extends Error {}

/** Node charset check shared with the generators ([A-Za-z0-9_]+). */
export const CLI_NODE_RE = /^[A-Za-z0-9_]+$/;

/** CLI wrapper for parseTimeUnit: a bad time unit is a usage error. */
export function parseTimeUnitArg(value: string): TimeUnit {
  try {
    return parseTimeUnit(value);
  } catch (e) {
    throw new UsageError((e as Error).message);
  }
}

/** CLI mode selector for WID vs HLC workflows. */
export type Kind = "wid" | "hlc";

/** Parsed CLI options that drive each command. */
export interface Opts {
  /** Operation kind (wid or hlc). */
  kind: Kind;
  node: string;
  W: number;
  Z: number;
  timeUnit: TimeUnit;
  count: number;
  json: boolean;
}

/** Canonical mode parameters sent on CLI helpers. */
export interface Canon {
  A: string;
  W: number;
  L: number;
  D: string;
  I: string;
  E: string;
  Z: number;
  T: TimeUnit;
  R: string;
  M: boolean;
  N: number;
  /**
   * True only for a real L=<n> (not omitted, not the L=# placeholder).
   * A=stream treats an unset L as 0 (no sleep); the 3600 default applies
   * to the Rust-only service loops, not streaming.
   */
  LExplicit: boolean;
  WID?: string;
  KEY?: string;
  SIG?: string;
  DATA?: string;
  OUT?: string;
  MODE?: string;
  CODE?: string;
  DIGITS?: number;
  MAX_AGE_SEC?: number;
  MAX_FUTURE_SEC?: number;
}

export function parseIntStrict(value: string, name: string): number {
  // Number.parseInt("2+2", 10) parses the prefix and yields 2; the whole
  // string must be an integer so garbage is an error, never a silent guess.
  if (!/^-?[0-9]+$/.test(value)) {
    throw new UsageError(`invalid integer for ${name}`);
  }
  return Number.parseInt(value, 10);
}

const defaultsMap: Record<string, string> = {
  A: "next",
  W: "4",
  L: "3600",
  D: "",
  I: "auto",
  E: "state",
  Z: "6",
  T: "sec",
  R: "auto",
  M: "false",
  N: "0",
  WID: "",
  KEY: "",
  SIG: "",
  DATA: "",
  OUT: "",
  MODE: "",
  CODE: "",
  DIGITS: "6",
  MAX_AGE_SEC: "0",
  MAX_FUTURE_SEC: "5",
};

export function defaultValueFor(key: string): string {
  return defaultsMap[key] ?? "";
}
