import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
import {
  HLCWidGen,
  parseHlcWid,
  parseWid,
  validateHlcWid,
  validateWid,
  WidGen,
} from "../index";
import { type Canon, type Opts, UsageError } from "./types";
import { parseOpts, parseCanonical } from "./args";
import { runSign, runVerify, runWOtp } from "./crypto";
import { sqlAllocateNextWid } from "./sql";
import { printCompletion } from "./completion";
import { printActions, printHelp } from "./help";

export function runNext(args: string[]): void {
  const opts = parseOpts(args, false, false);
  if (opts.kind === "wid") {
    console.log(
      new WidGen({ W: opts.W, Z: opts.Z, timeUnit: opts.timeUnit }).next()
    );
    return;
  }
  console.log(
    new HLCWidGen({
      node: opts.node,
      W: opts.W,
      Z: opts.Z,
      timeUnit: opts.timeUnit,
    }).next()
  );
}

export function runStream(args: string[]): void {
  const opts = parseOpts(args, true, false);
  if (opts.kind === "wid") {
    const gen = new WidGen({ W: opts.W, Z: opts.Z, timeUnit: opts.timeUnit });
    for (let i = 0; opts.count === 0 || i < opts.count; i += 1) {
      console.log(gen.next());
    }
    return;
  }
  const gen = new HLCWidGen({
    node: opts.node,
    W: opts.W,
    Z: opts.Z,
    timeUnit: opts.timeUnit,
  });
  for (let i = 0; opts.count === 0 || i < opts.count; i += 1) {
    console.log(gen.next());
  }
}

export function runValidate(args: string[]): void {
  if (args.length === 0) {
    throw new UsageError("validate requires an id");
  }
  const id = args[0];
  if (!id) {
    throw new UsageError("parse requires an id");
  }
  const opts = parseOpts(args.slice(1), false, false);
  const ok =
    opts.kind === "wid"
      ? validateWid(id, opts.W, opts.Z, opts.timeUnit)
      : validateHlcWid(id, opts.W, opts.Z, opts.timeUnit);
  console.log(ok ? "true" : "false");
  if (!ok) {
    throw new Error("invalid wid");
  }
}

function runParseWid(id: string, opts: Opts): void {
  const parsed = parseWid(id, opts.W, opts.Z, opts.timeUnit);
  if (!parsed) {
    console.log("null");
    throw new Error("invalid wid");
  }
  if (opts.json) {
    console.log(
      JSON.stringify({
        raw: parsed.raw,
        timestamp: parsed.timestamp.toISOString(),
        sequence: parsed.sequence,
        padding: parsed.padding,
      })
    );
    return;
  }
  console.log(`raw=${parsed.raw}`);
  console.log(`timestamp=${parsed.timestamp.toISOString()}`);
  console.log(`sequence=${parsed.sequence}`);
  console.log(`padding=${parsed.padding ?? ""}`);
}

function runParseHlc(id: string, opts: Opts): void {
  const parsed = parseHlcWid(id, opts.W, opts.Z, opts.timeUnit);
  if (!parsed) {
    console.log("null");
    throw new Error("invalid wid");
  }
  if (opts.json) {
    console.log(
      JSON.stringify({
        raw: parsed.raw,
        timestamp: parsed.timestamp.toISOString(),
        logical_counter: parsed.logicalCounter,
        node: parsed.node,
        padding: parsed.padding,
      })
    );
    return;
  }
  console.log(`raw=${parsed.raw}`);
  console.log(`timestamp=${parsed.timestamp.toISOString()}`);
  console.log(`logical_counter=${parsed.logicalCounter}`);
  console.log(`node=${parsed.node}`);
  console.log(`padding=${parsed.padding ?? ""}`);
}

export function runParse(args: string[]): void {
  if (args.length === 0) {
    throw new UsageError("parse requires an id");
  }
  const id = args[0];
  if (!id) {
    throw new UsageError("parse requires an id");
  }
  const opts = parseOpts(args.slice(1), false, true);

  if (opts.kind === "wid") {
    runParseWid(id, opts);
  } else {
    runParseHlc(id, opts);
  }
}

export function runHealthcheck(args: string[]): void {
  const opts = parseOpts(args, false, true);
  const sample =
    opts.kind === "wid"
      ? new WidGen({ W: opts.W, Z: opts.Z, timeUnit: opts.timeUnit }).next()
      : new HLCWidGen({
          node: opts.node,
          W: opts.W,
          Z: opts.Z,
          timeUnit: opts.timeUnit,
        }).next();

  const ok =
    opts.kind === "wid"
      ? validateWid(sample, opts.W, opts.Z, opts.timeUnit)
      : validateHlcWid(sample, opts.W, opts.Z, opts.timeUnit);

  if (opts.json) {
    console.log(
      JSON.stringify({
        ok,
        kind: opts.kind,
        W: opts.W,
        Z: opts.Z,
        time_unit: opts.timeUnit,
        sample_id: sample,
      })
    );
  } else {
    console.log(
      `ok=${ok ? "true" : "false"} kind=${opts.kind} sample=${sample}`
    );
  }

  if (!ok) {
    throw new Error("healthcheck failed");
  }
}

export function runBench(args: string[]): void {
  const opts = parseOpts(args, true, false);
  const n = opts.count > 0 ? opts.count : 100000;

  const start = process.hrtime.bigint();
  if (opts.kind === "wid") {
    const g = new WidGen({ W: opts.W, Z: opts.Z, timeUnit: opts.timeUnit });
    for (let i = 0; i < n; i += 1) {
      g.next();
    }
  } else {
    const g = new HLCWidGen({
      node: opts.node,
      W: opts.W,
      Z: opts.Z,
      timeUnit: opts.timeUnit,
    });
    for (let i = 0; i < n; i += 1) {
      g.next();
    }
  }
  const secs = Number(process.hrtime.bigint() - start) / 1_000_000_000;
  const s = Math.max(secs, 1e-9);
  console.log(
    JSON.stringify({
      impl: "typescript",
      kind: opts.kind,
      W: opts.W,
      Z: opts.Z,
      time_unit: opts.timeUnit,
      n,
      seconds: s,
      ids_per_sec: n / s,
    })
  );
}

function parseStateMode(c: Canon): string {
  if (c.E.includes("+")) {
    return c.E.split("+", 2)[0] || "";
  }
  if (c.E.includes(",")) {
    return c.E.split(",", 2)[0] || "";
  }
  return c.E;
}

function dataDir(c: Canon): string {
  return c.D && c.D.length > 0 ? resolve(c.D) : resolve(".local/services");
}

function sleepSeconds(sec: number): void {
  if (sec <= 0) {
    return;
  }
  const i32 = new Int32Array(new SharedArrayBuffer(4));
  Atomics.wait(i32, 0, 0, sec * 1000);
}

function handleCanonNext(c: Canon, stateMode: string): number {
  if (stateMode === "sql") {
    console.log(sqlAllocateNextWid(c));
  } else {
    console.log(new WidGen({ W: c.W, Z: c.Z, timeUnit: c.T }).next());
  }
  return 0;
}

function handleCanonStream(c: Canon, stateMode: string): number {
  const genOptions = { W: c.W, Z: c.Z, timeUnit: c.T } as const;
  const gen = stateMode === "sql" ? null : new WidGen(genOptions);
  const max = c.N <= 0 ? Number.POSITIVE_INFINITY : c.N;
  let emitted = 0;
  while (emitted < max) {
    if (stateMode === "sql") {
      console.log(sqlAllocateNextWid(c));
    } else {
      console.log(gen!.next());
    }
    emitted += 1;
    if (emitted < max && c.LExplicit && c.L > 0) {
      sleepSeconds(c.L);
    }
  }
  return 0;
}

function handleCanonHealthcheck(c: Canon): number {
  runHealthcheck([
    "--kind",
    "wid",
    "--W",
    String(c.W),
    "--Z",
    String(c.Z),
    "--time-unit",
    c.T,
    "--json",
  ]);
  return 0;
}

export function runCanonical(args: string[]): number {
  const c = parseCanonical(args);
  if (c.A === "help-actions") {
    printActions();
    return 0;
  }

  const stateMode = parseStateMode(c);
  const canonDataDir = dataDir(c);
  mkdirSync(canonDataDir, { recursive: true });

  switch (c.A) {
    case "next":
      return handleCanonNext(c, stateMode);
    case "stream":
      return handleCanonStream(c, stateMode);
    case "healthcheck":
      return handleCanonHealthcheck(c);
    case "sign":
      return runSign(c);
    case "verify":
      return runVerify(c);
    case "w-otp":
      return runWOtp(c);
    default:
      throw new UsageError(`unknown A=${c.A}`);
  }
}

export function runSelftest(): number {
  const wg = new WidGen({ W: 4, Z: 0, timeUnit: "sec" });
  const a = wg.next();
  const b = wg.next();
  if (!(a < b)) {
    return 1;
  }
  if (!validateWid(a, 4, 0, "sec")) {
    return 1;
  }

  const hg = new HLCWidGen({ node: "node01", W: 4, Z: 0, timeUnit: "sec" });
  const h = hg.next();
  if (!validateHlcWid(h, 4, 0, "sec")) {
    return 1;
  }

  if (validateWid("20260212T091530.0000Z-node01", 4, 0, "sec")) {
    return 1;
  }
  if (validateHlcWid("20260212T091530.0000Z", 4, 0, "sec")) {
    return 1;
  }
  if (!validateWid("20260212T091530123.0000Z", 4, 0, "ms")) {
    return 1;
  }
  if (!validateHlcWid("20260212T091530123.0000Z-node01", 4, 0, "ms")) {
    return 1;
  }
  return 0;
}

function runCommand(cmd: string, rest: string[]): number {
  switch (cmd) {
    case "next":
      runNext(rest);
      return 0;
    case "stream":
      runStream(rest);
      return 0;
    case "validate":
      runValidate(rest);
      return 0;
    case "parse":
      runParse(rest);
      return 0;
    case "healthcheck":
      runHealthcheck(rest);
      return 0;
    case "bench":
      runBench(rest);
      return 0;
    default:
      throw new UsageError(`unknown command: ${cmd}`);
  }
}

function handleMainStaticCmd(cmd: string, rest: string[]): number | undefined {
  if (cmd === "help" || cmd === "-h" || cmd === "--help") {
    printHelp();
    return 0;
  }
  if (cmd === "help-actions") {
    printActions();
    return 0;
  }
  if (cmd === "selftest") {
    return runSelftest();
  }
  if (cmd === "completion") {
    const shell = rest[0] ?? "";
    if (!shell) {
      process.stderr.write("usage: wid completion bash|zsh|fish\n");
      return 1;
    }
    printCompletion(shell);
    return 0;
  }
  return undefined;
}

export function main(): number {
  const args = process.argv.slice(2);
  if (args.length === 0) {
    printHelp();
    return 2;
  }

  if (args.some((a) => a.includes("="))) {
    try {
      return runCanonical(args);
    } catch (e) {
      console.error(`error: ${(e as Error).message}`);
      return e instanceof UsageError ? 2 : 1;
    }
  }

  const [cmd, ...rest] = args;
  if (!cmd) {
    printHelp();
    return 2;
  }
  const staticResult = handleMainStaticCmd(cmd, rest);
  if (staticResult !== undefined) {
    return staticResult;
  }

  try {
    return runCommand(cmd, rest);
  } catch (e) {
    console.error(`error: ${(e as Error).message}`);
    return e instanceof UsageError ? 2 : 1;
  }
}
