import { MAX_W, MAX_Z } from "../wid";
import {
  CLI_NODE_RE,
  defaultValueFor,
  parseIntStrict,
  parseTimeUnitArg,
  type Canon,
  type Kind,
  type Opts,
  UsageError,
} from "./types";

type OptHandler = (
  nextArg: string | undefined,
  opts: Opts,
  flags: { zExplicit: boolean }
) => number;

const optHandlers: Record<string, OptHandler> = {
  "--kind": (nextArg, opts) => {
    if (!nextArg) {
      throw new UsageError("missing value for --kind");
    }
    opts.kind = nextArg as Kind;
    return 1;
  },
  "--node": (nextArg, opts) => {
    if (!nextArg) {
      throw new UsageError("missing value for --node");
    }
    opts.node = nextArg;
    return 1;
  },
  "--W": (nextArg, opts) => {
    if (!nextArg) {
      throw new UsageError("missing value for --W");
    }
    opts.W = parseIntStrict(nextArg, "--W");
    return 1;
  },
  "--Z": (nextArg, opts, flags) => {
    if (!nextArg) {
      throw new UsageError("missing value for --Z");
    }
    opts.Z = parseIntStrict(nextArg, "--Z");
    flags.zExplicit = true;
    return 1;
  },
  "--time-unit": (nextArg, opts) => {
    if (!nextArg) {
      throw new UsageError("missing value for --time-unit");
    }
    opts.timeUnit = parseTimeUnitArg(nextArg);
    return 1;
  },
  "--T": (nextArg, opts) => {
    if (!nextArg) {
      throw new UsageError("missing value for --time-unit");
    }
    opts.timeUnit = parseTimeUnitArg(nextArg);
    return 1;
  },
};

function parseSingleOpt(
  arg: string,
  nextArg: string | undefined,
  opts: Opts,
  flags: { zExplicit: boolean },
  allowCount: boolean,
  allowJson: boolean
): number {
  if (arg === "--count") {
    if (!allowCount) {
      throw new UsageError("unknown flag: --count");
    }
    if (!nextArg) {
      throw new UsageError("missing value for --count");
    }
    opts.count = parseIntStrict(nextArg, "--count");
    return 1;
  }
  if (arg === "--json") {
    if (!allowJson) {
      throw new UsageError("unknown flag: --json");
    }
    opts.json = true;
    return 0;
  }
  const handler = optHandlers[arg];
  if (!handler) {
    throw new UsageError(`unknown flag: ${arg}`);
  }
  return handler(nextArg, opts, flags);
}

function validateOpts(opts: Opts, zExplicit: boolean): void {
  if (opts.kind !== "wid" && opts.kind !== "hlc") {
    throw new UsageError("--kind must be one of: wid, hlc");
  }
  if (opts.W <= 0 || opts.W > MAX_W) {
    throw new UsageError("W must be between 1 and 18");
  }
  if (opts.Z < 0 || opts.Z > MAX_Z) {
    throw new UsageError("Z must be between 0 and 64");
  }
  if (opts.count < 0) {
    throw new UsageError("count must be >= 0");
  }
  if (opts.kind === "hlc" && !CLI_NODE_RE.test(opts.node)) {
    throw new UsageError("invalid node");
  }
  // HLC-WID defaults to Z=0 (no random padding) per spec convention;
  // plain WID keeps Z=6. An explicit --Z always wins.
  if (opts.kind === "hlc" && !zExplicit) {
    opts.Z = 0;
  }
}

export function parseOpts(
  args: string[],
  allowCount: boolean,
  allowJson: boolean
): Opts {
  const opts: Opts = {
    kind: "wid",
    node: process.env.NODE ?? "ts",
    W: 4,
    Z: 6,
    timeUnit: "sec",
    count: 0,
    json: false,
  };

  const flags = { zExplicit: false };
  for (let i = 0; i < args.length; i += 1) {
    const argI = args[i];
    if (!argI) {
      continue;
    }
    const consumed = parseSingleOpt(
      argI,
      args[i + 1],
      opts,
      flags,
      allowCount,
      allowJson
    );
    i += consumed;
  }

  validateOpts(opts, flags.zExplicit);
  return opts;
}

type CanonHandler = (v: string, out: Canon, vRaw: string) => void;

const canonHandlers: Record<string, CanonHandler> = {
  A: (v, out) => {
    out.A = v.toLowerCase();
  },
  W: (v, out) => {
    out.W = parseIntStrict(v, "W");
  },
  L: (v, out, vRaw) => {
    out.L = parseIntStrict(v, "L");
    out.LExplicit = vRaw !== "#";
  },
  D: (v, out) => {
    out.D = v;
  },
  I: (v, out) => {
    out.I = v;
  },
  E: (v, out) => {
    out.E = v;
  },
  Z: (v, out) => {
    out.Z = parseIntStrict(v, "Z");
  },
  T: (v, out) => {
    out.T = parseTimeUnitArg(v);
  },
  R: (v, out) => {
    out.R = v;
  },
  M: (v, out) => {
    out.M = ["1", "true", "yes", "y", "on"].includes(v.toLowerCase());
  },
  N: (v, out) => {
    out.N = parseIntStrict(v, "N");
  },
  WID: (v, out) => {
    out.WID = v;
  },
  KEY: (v, out) => {
    out.KEY = v;
  },
  SIG: (v, out) => {
    out.SIG = v;
  },
  DATA: (v, out) => {
    out.DATA = v;
  },
  OUT: (v, out) => {
    out.OUT = v;
  },
  MODE: (v, out) => {
    out.MODE = v;
  },
  CODE: (v, out) => {
    out.CODE = v;
  },
  DIGITS: (v, out) => {
    out.DIGITS = parseIntStrict(v, "DIGITS");
  },
  MAX_AGE_SEC: (v, out) => {
    out.MAX_AGE_SEC = parseIntStrict(v, "MAX_AGE_SEC");
  },
  MAX_FUTURE_SEC: (v, out) => {
    out.MAX_FUTURE_SEC = parseIntStrict(v, "MAX_FUTURE_SEC");
  },
};

function parseSingleCanonKey(
  k: string,
  v: string,
  out: Canon,
  vRaw: string
): void {
  const handler = canonHandlers[k];
  if (!handler) {
    throw new UsageError(`unknown key: ${k}`);
  }
  handler(v, out, vRaw);
}

function validateCanon(out: Canon): void {
  if (out.W <= 0 || out.W > MAX_W) {
    throw new UsageError("W must be between 1 and 18");
  }
  if (out.Z < 0 || out.Z > MAX_Z) {
    throw new UsageError("Z must be between 0 and 64");
  }
  if (out.N < 0 || out.L < 0) {
    throw new UsageError("N/L must be >= 0");
  }
  if (!["auto", "null", "stdout"].includes(out.R)) {
    throw new UsageError(
      `transport R=${out.R} is only available in the Rust implementation (services/transports are Rust-only)`
    );
  }
}

export function parseCanonical(args: string[]): Canon {
  const out: Canon = {
    A: "next",
    W: 4,
    L: 3600,
    D: "",
    I: "auto",
    E: "state",
    Z: 6,
    T: "sec",
    R: "auto",
    M: false,
    N: 0,
    LExplicit: false,
  };

  for (const arg of args) {
    const eq = arg.indexOf("=");
    if (eq < 0) {
      throw new UsageError(`expected KEY=VALUE, got '${arg}'`);
    }
    const k = arg.slice(0, eq);
    const vRaw = arg.slice(eq + 1);
    const v = vRaw === "#" ? defaultValueFor(k) : vRaw;

    parseSingleCanonKey(k, v, out, vRaw);
  }

  if (out.M) {
    out.T = "ms";
  }

  out.A =
    out.A === "id" || out.A === "default"
      ? "next"
      : out.A === "hc"
      ? "healthcheck"
      : out.A;

  validateCanon(out);

  return out;
}
