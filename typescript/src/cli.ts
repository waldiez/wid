#!/usr/bin/env node

import { closeSync, existsSync, mkdirSync, openSync, readFileSync, unlinkSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { spawn } from "node:child_process";
import { createHmac, createPrivateKey, createPublicKey, sign as cryptoSign, timingSafeEqual, verify as cryptoVerify } from "node:crypto";
import {
  HLCWidGen,
  parseHlcWid,
  parseWid,
  validateHlcWid,
  validateWid,
  WidGen,
} from "./index";
import { parseTimeUnit, type TimeUnit } from "./time";

/** CLI mode selector for WID vs HLC workflows. */
type Kind = "wid" | "hlc";

/** Parsed CLI options that drive each command. */
interface Opts {
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
interface Canon {
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

/** Allowed transports recognized by the CLI. */
const LOCAL_SERVICE_TRANSPORTS = new Set(["mqtt", "ws", "redis", "null", "stdout"]);

function printHelp(): void {
  console.error(`wid - WID/HLC-WID generator CLI

Usage:
  wid next [--kind wid|hlc] [--node <name>] [--W <n>] [--Z <n>] [--time-unit sec|ms]
  wid stream [--kind wid|hlc] [--node <name>] [--W <n>] [--Z <n>] [--time-unit sec|ms] [--count <n>]
  wid validate <id> [--kind wid|hlc] [--W <n>] [--Z <n>] [--time-unit sec|ms]
  wid parse <id> [--kind wid|hlc] [--W <n>] [--Z <n>] [--time-unit sec|ms] [--json]
  wid healthcheck [--kind wid|hlc] [--node <name>] [--W <n>] [--Z <n>] [--time-unit sec|ms] [--json]
  wid bench [--kind wid|hlc] [--node <name>] [--W <n>] [--Z <n>] [--time-unit sec|ms] [--count <n>]

Canonical mode:
  wid W=# A=# L=# D=# I=# E=# Z=# T=sec|ms R=auto|mqtt|ws|redis|null|stdout N=#
  wid A=w-otp MODE=gen|verify KEY=<secret|path> [WID=<wid>] [CODE=<otp>] [DIGITS=6] [MAX_AGE_SEC=0] [MAX_FUTURE_SEC=5]
  For A=stream: N=0 means infinite stream
  E supports: state | stateless | sql`);
}

function printActions(): void {
  console.log(`wid action matrix

Core ID:
  A=next | A=stream | A=healthcheck | A=sign | A=verify | A=w-otp

Service lifecycle (native):
  A=discover | A=scaffold | A=run | A=start | A=stop | A=status | A=logs

Service modules (native):
  A=saf      (alias: raf)
  A=saf-wid  (aliases: waf, wraf)
  A=wir      (alias: witr)
  A=wism     (alias: wim)
  A=wihp     (alias: wih)
  A=wipr     (alias: wip)
  A=duplex

Help:
  A=help-actions`);
}

function parseIntStrict(value: string, name: string): number {
  const n = Number.parseInt(value, 10);
  if (!Number.isFinite(n) || Number.isNaN(n)) throw new Error(`invalid integer for ${name}`);
  return n;
}

function parseOpts(args: string[], allowCount: boolean): Opts {
  const opts: Opts = {
    kind: "wid",
    node: process.env.NODE ?? "ts",
    W: 4,
    Z: 6,
    timeUnit: "sec",
    count: 0,
    json: false,
  };

  for (let i = 0; i < args.length; i += 1) {
    const arg = args[i];
    switch (arg) {
      case "--kind":
        if (i + 1 >= args.length) throw new Error("missing value for --kind");
        opts.kind = args[++i] as Kind;
        break;
      case "--node":
        if (i + 1 >= args.length) throw new Error("missing value for --node");
        opts.node = args[++i];
        break;
      case "--W":
        if (i + 1 >= args.length) throw new Error("missing value for --W");
        opts.W = parseIntStrict(args[++i], "--W");
        break;
      case "--Z":
        if (i + 1 >= args.length) throw new Error("missing value for --Z");
        opts.Z = parseIntStrict(args[++i], "--Z");
        break;
      case "--time-unit":
      case "--T":
        if (i + 1 >= args.length) throw new Error("missing value for --time-unit");
        opts.timeUnit = parseTimeUnit(args[++i]);
        break;
      case "--count":
        if (!allowCount) throw new Error("unknown flag: --count");
        if (i + 1 >= args.length) throw new Error("missing value for --count");
        opts.count = parseIntStrict(args[++i], "--count");
        break;
      case "--json":
        opts.json = true;
        break;
      default:
        throw new Error(`unknown flag: ${arg}`);
    }
  }

  if (opts.kind !== "wid" && opts.kind !== "hlc") throw new Error("--kind must be one of: wid, hlc");
  if (opts.W <= 0) throw new Error("W must be > 0");
  if (opts.Z < 0) throw new Error("Z must be >= 0");
  if (opts.count < 0) throw new Error("count must be >= 0");
  return opts;
}

function runNext(args: string[]): void {
  const opts = parseOpts(args, false);
  if (opts.kind === "wid") {
    console.log(new WidGen({ W: opts.W, Z: opts.Z, timeUnit: opts.timeUnit }).next());
    return;
  }
  console.log(new HLCWidGen({ node: opts.node, W: opts.W, Z: opts.Z, timeUnit: opts.timeUnit }).next());
}

function runStream(args: string[]): void {
  const opts = parseOpts(args, true);
  if (opts.kind === "wid") {
    const gen = new WidGen({ W: opts.W, Z: opts.Z, timeUnit: opts.timeUnit });
    for (let i = 0; opts.count === 0 || i < opts.count; i += 1) console.log(gen.next());
    return;
  }
  const gen = new HLCWidGen({ node: opts.node, W: opts.W, Z: opts.Z, timeUnit: opts.timeUnit });
  for (let i = 0; opts.count === 0 || i < opts.count; i += 1) console.log(gen.next());
}

function runValidate(args: string[]): void {
  if (args.length === 0) throw new Error("validate requires an id");
  const id = args[0];
  const opts = parseOpts(args.slice(1), false);
  const ok =
    opts.kind === "wid"
      ? validateWid(id, opts.W, opts.Z, opts.timeUnit)
      : validateHlcWid(id, opts.W, opts.Z, opts.timeUnit);
  console.log(ok ? "true" : "false");
  if (!ok) throw new Error("invalid wid");
}

function runParse(args: string[]): void {
  if (args.length === 0) throw new Error("parse requires an id");
  const id = args[0];
  const opts = parseOpts(args.slice(1), false);

  if (opts.kind === "wid") {
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
    return;
  }

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

function runHealthcheck(args: string[]): void {
  const opts = parseOpts(args, false);
  const sample =
    opts.kind === "wid"
      ? new WidGen({ W: opts.W, Z: opts.Z, timeUnit: opts.timeUnit }).next()
      : new HLCWidGen({ node: opts.node, W: opts.W, Z: opts.Z, timeUnit: opts.timeUnit }).next();

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
    console.log(`ok=${ok ? "true" : "false"} kind=${opts.kind} sample=${sample}`);
  }

  if (!ok) throw new Error("healthcheck failed");
}

function runBench(args: string[]): void {
  const opts = parseOpts(args, true);
  const n = opts.count > 0 ? opts.count : 100000;

  const start = process.hrtime.bigint();
  if (opts.kind === "wid") {
    const g = new WidGen({ W: opts.W, Z: opts.Z, timeUnit: opts.timeUnit });
    for (let i = 0; i < n; i += 1) g.next();
  } else {
    const g = new HLCWidGen({ node: opts.node, W: opts.W, Z: opts.Z, timeUnit: opts.timeUnit });
    for (let i = 0; i < n; i += 1) g.next();
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

function parseCanonical(args: string[]): Canon {
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
  };

  for (const arg of args) {
    const [k, vRaw] = arg.split("=", 2);
    if (!vRaw) throw new Error(`expected KEY=VALUE, got '${arg}'`);
    const v = vRaw === "#" ? defaultValueFor(k) : vRaw;

    switch (k) {
      case "A":
        out.A = v.toLowerCase();
        break;
      case "W":
        out.W = parseIntStrict(v, "W");
        break;
      case "L":
        out.L = parseIntStrict(v, "L");
        break;
      case "D":
        out.D = v;
        break;
      case "I":
        out.I = v;
        break;
      case "E":
        out.E = v;
        break;
      case "Z":
        out.Z = parseIntStrict(v, "Z");
        break;
      case "T":
        out.T = parseTimeUnit(v);
        break;
      case "R":
        out.R = v;
        break;
      case "M":
        out.M = ["1", "true", "yes", "y", "on"].includes(v.toLowerCase());
        break;
      case "N":
        out.N = parseIntStrict(v, "N");
        break;
      case "WID":
        out.WID = v;
        break;
      case "KEY":
        out.KEY = v;
        break;
      case "SIG":
        out.SIG = v;
        break;
      case "DATA":
        out.DATA = v;
        break;
      case "OUT":
        out.OUT = v;
        break;
      case "MODE":
        out.MODE = v;
        break;
      case "CODE":
        out.CODE = v;
        break;
      case "DIGITS":
        out.DIGITS = parseIntStrict(v, "DIGITS");
        break;
      case "MAX_AGE_SEC":
        out.MAX_AGE_SEC = parseIntStrict(v, "MAX_AGE_SEC");
        break;
      case "MAX_FUTURE_SEC":
        out.MAX_FUTURE_SEC = parseIntStrict(v, "MAX_FUTURE_SEC");
        break;
      default:
        throw new Error(`unknown key: ${k}`);
    }
  }

  if (out.M) out.T = "ms";

  out.A =
    out.A === "id" || out.A === "default"
      ? "next"
      : out.A === "hc"
      ? "healthcheck"
      : out.A === "raf"
      ? "saf"
      : out.A === "waf" || out.A === "wraf"
      ? "saf-wid"
      : out.A === "witr"
      ? "wir"
      : out.A === "wim"
      ? "wism"
      : out.A === "wih"
      ? "wihp"
      : out.A === "wip"
      ? "wipr"
      : out.A;

  if (out.W <= 0) throw new Error("W must be > 0");
  if (out.Z < 0 || out.N < 0 || out.L < 0) throw new Error("Z/N/L must be >= 0");
  if (!["auto", "mqtt", "ws", "redis", "null", "stdout"].includes(out.R)) {
    throw new Error("invalid R transport");
  }

  return out;
}

function defaultValueFor(key: string): string {
  switch (key) {
    case "A":
      return "next";
    case "W":
      return "4";
    case "L":
      return "3600";
    case "D":
      return "";
    case "I":
      return "auto";
    case "E":
      return "state";
    case "Z":
      return "6";
    case "T":
      return "sec";
    case "R":
      return "auto";
    case "M":
      return "false";
    case "N":
      return "0";
    case "WID":
    case "KEY":
    case "SIG":
    case "DATA":
    case "OUT":
    case "MODE":
    case "CODE":
      return "";
    case "DIGITS":
      return "6";
    case "MAX_AGE_SEC":
      return "0";
    case "MAX_FUTURE_SEC":
      return "5";
    default:
      return "";
  }
}

function b64urlEncode(buf: Buffer): string {
  return buf.toString("base64").replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

function b64urlDecode(s: string): Buffer {
  let std = s.replace(/-/g, "+").replace(/_/g, "/");
  const m = std.length % 4;
  if (m === 2) std += "==";
  else if (m === 3) std += "=";
  else if (m === 1) throw new Error("invalid base64url signature length");
  return Buffer.from(std, "base64");
}

function buildSignVerifyMessage(c: Canon): Buffer {
  const wid = c.WID ?? "";
  if (!wid) throw new Error("WID=<wid_string> required");
  const parts: Buffer[] = [Buffer.from(wid, "utf8")];
  if (c.DATA && c.DATA.length > 0) {
    if (!existsSync(c.DATA)) throw new Error(`data file not found: ${c.DATA}`);
    parts.push(readFileSync(c.DATA));
  }
  return Buffer.concat(parts);
}

function runSign(c: Canon): number {
  const keyPath = c.KEY ?? "";
  if (!keyPath) throw new Error("KEY=<private_key_path> required for A=sign");
  if (!existsSync(keyPath)) throw new Error(`private key file not found: ${keyPath}`);
  const message = buildSignVerifyMessage(c);
  const key = createPrivateKey(readFileSync(keyPath));
  const sig = cryptoSign(null, message, key);
  const out = b64urlEncode(sig);
  if (c.OUT && c.OUT.length > 0) writeFileSync(c.OUT, out, "utf8");
  else console.log(out);
  return 0;
}

function runVerify(c: Canon): number {
  const keyPath = c.KEY ?? "";
  const sigText = c.SIG ?? "";
  if (!keyPath) throw new Error("KEY=<public_key_path> required for A=verify");
  if (!sigText) throw new Error("SIG=<signature_string> required for A=verify");
  if (!existsSync(keyPath)) throw new Error(`public key file not found: ${keyPath}`);
  const message = buildSignVerifyMessage(c);
  const key = createPublicKey(readFileSync(keyPath));
  const ok = cryptoVerify(null, message, key, b64urlDecode(sigText));
  if (ok) {
    console.log("Signature valid.");
    return 0;
  }
  console.error("Signature invalid.");
  return 1;
}

function resolveWOtpSecret(raw: string): string {
  if (existsSync(raw)) return readFileSync(raw, "utf8").trim();
  return raw.trim();
}

function computeWOtp(secret: string, wid: string, digits: number): string {
  const digest = createHmac("sha256", Buffer.from(secret, "utf8")).update(Buffer.from(wid, "utf8")).digest();
  const binary = digest.readUInt32BE(0);
  const mod = 10 ** digits;
  return String(binary % mod).padStart(digits, "0");
}

function wotpWidTickMs(wid: string): number {
  const m = /^(\d{8})T(\d{6})(\d{3})?\.[0-9]+Z/.exec(wid);
  if (!m) throw new Error("WID timestamp is invalid for time-window verification");
  const date = m[1];
  const hms = m[2];
  const ms = m[3] ?? "000";
  const y = Number(date.slice(0, 4));
  const mo = Number(date.slice(4, 6));
  const d = Number(date.slice(6, 8));
  const hh = Number(hms.slice(0, 2));
  const mm = Number(hms.slice(2, 4));
  const ss = Number(hms.slice(4, 6));
  const msec = Number(ms);
  const tick = Date.UTC(y, mo - 1, d, hh, mm, ss, msec);
  if (!Number.isFinite(tick)) throw new Error("WID timestamp is invalid for time-window verification");
  return tick;
}

function runWOtp(c: Canon): number {
  const mode = (c.MODE ?? "gen").toLowerCase();
  if (mode !== "gen" && mode !== "verify") throw new Error("MODE must be gen or verify for A=w-otp");
  if (!c.KEY || c.KEY.length === 0) throw new Error("KEY=<secret_or_path> required for A=w-otp");
  const secret = resolveWOtpSecret(c.KEY);
  if (!secret) throw new Error("w-otp secret cannot be empty");
  const digits = c.DIGITS ?? 6;
  if (!Number.isInteger(digits) || digits < 4 || digits > 10) throw new Error("DIGITS must be an integer between 4 and 10");
  const maxAgeSec = c.MAX_AGE_SEC ?? 0;
  const maxFutureSec = c.MAX_FUTURE_SEC ?? 5;
  if (!Number.isInteger(maxAgeSec) || maxAgeSec < 0) throw new Error("MAX_AGE_SEC must be a non-negative integer");
  if (!Number.isInteger(maxFutureSec) || maxFutureSec < 0) throw new Error("MAX_FUTURE_SEC must be a non-negative integer");

  let wid = c.WID ?? "";
  if (!wid && mode === "gen") wid = new WidGen({ W: c.W, Z: c.Z, timeUnit: c.T }).next();
  if (!wid) throw new Error("WID=<wid_string> required for A=w-otp MODE=verify");

  const otp = computeWOtp(secret, wid, digits);
  if (mode === "gen") {
    console.log(JSON.stringify({ wid, otp, digits }));
    return 0;
  }

  const code = c.CODE ?? "";
  if (!code) throw new Error("CODE=<otp_code> required for A=w-otp MODE=verify");
  if (maxAgeSec > 0 || maxFutureSec > 0) {
    const widMs = wotpWidTickMs(wid);
    const nowMs = Date.now();
    const delta = nowMs - widMs;
    if (delta < 0 && -delta > maxFutureSec * 1000) throw new Error("OTP invalid: WID timestamp is too far in the future");
    if (delta >= 0 && maxAgeSec > 0 && delta > maxAgeSec * 1000) throw new Error("OTP invalid: WID timestamp is too old");
  }
  const got = Buffer.from(code, "utf8");
  const exp = Buffer.from(otp, "utf8");
  const ok = got.length === exp.length && timingSafeEqual(got, exp);
  if (ok) {
    console.log("OTP valid.");
    return 0;
  }
  console.error("OTP invalid.");
  return 1;
}

function parseStateAndTransport(c: Canon): { stateMode: string; transport: string } {
  let stateMode = c.E;
  let transport = c.R;
  if (c.E.includes("+")) {
    const [left, right] = c.E.split("+", 2);
    stateMode = left;
    if (transport === "auto") transport = right;
  } else if (c.E.includes(",")) {
    const [left, right] = c.E.split(",", 2);
    stateMode = left;
    if (transport === "auto") transport = right;
  }
  return { stateMode, transport };
}

function runtimeDir(): string {
  return resolve(".local/wid/typescript");
}

function runtimePidFile(): string {
  return resolve(runtimeDir(), "service.pid");
}

function runtimeLogFile(): string {
  return resolve(runtimeDir(), "service.log");
}

function dataDir(c: Canon): string {
  return c.D && c.D.length > 0 ? resolve(c.D) : resolve(".local/services");
}

/** Thin SQLite connection wrapper used by CLI helpers. */
type SqliteDb = {
  exec: (sql: string) => void;
  prepare: (sql: string) => { get: (...args: unknown[]) => unknown; run: (...args: unknown[]) => { changes?: number } };
  close?: () => void;
};

/** Constructor signature for SQLite database handles. */
type SqliteCtor = new (path: string, options?: { timeout?: number }) => SqliteDb;

function resolveNodeSqliteDatabaseSync(): SqliteCtor {
  const proc = (globalThis as { process?: unknown }).process as
    | { versions?: { node?: string }; getBuiltinModule?: (name: string) => unknown }
    | undefined;
  if (!proc?.versions?.node) throw new Error("SQLite requires Node.js");
  const builtin = typeof proc.getBuiltinModule === "function" ? proc.getBuiltinModule("node:sqlite") : null;
  if (builtin && typeof builtin === "object" && "DatabaseSync" in builtin) {
    return (builtin as { DatabaseSync: SqliteCtor }).DatabaseSync;
  }
  throw new Error("node:sqlite unavailable in this Node runtime");
}

function sqlStatePath(c: Canon): string {
  return resolve(dataDir(c), "wid_state.sqlite");
}

function sqlStateKey(c: Canon): string {
  return `wid:ts:${c.W}:${c.Z}:${c.T}`;
}

function sqlAllocateNextWid(c: Canon): string {
  /** Node sqlite constructor used for state persistence. */
  const DatabaseSync = resolveNodeSqliteDatabaseSync();
  const db = new DatabaseSync(sqlStatePath(c), { timeout: 5000 });
  try {
    db.exec("PRAGMA journal_mode=WAL;");
    db.exec(
      "CREATE TABLE IF NOT EXISTS wid_state (k TEXT PRIMARY KEY, last_sec INTEGER NOT NULL, last_seq INTEGER NOT NULL)"
    );
    const key = sqlStateKey(c);
    db.prepare("INSERT OR IGNORE INTO wid_state(k,last_sec,last_seq) VALUES(?,0,-1)").run(key);
    const selectStmt = db.prepare("SELECT last_sec,last_seq FROM wid_state WHERE k=?");
    const casStmt = db.prepare("UPDATE wid_state SET last_sec=?,last_seq=? WHERE k=? AND last_sec=? AND last_seq=?");

    for (let i = 0; i < 256; i += 1) {
      try {
        const row = selectStmt.get(key) as { last_sec?: number; last_seq?: number } | undefined;
        if (!row || typeof row.last_sec !== "number" || typeof row.last_seq !== "number") {
          throw new Error("invalid SQL state row");
        }
        const gen = new WidGen({ W: c.W, Z: c.Z, timeUnit: c.T });
        gen.restoreState(row.last_sec, row.last_seq);
        const id = gen.next();
        const nextState = gen.state;
        const updated = casStmt.run(nextState.lastSec, nextState.lastSeq, key, row.last_sec, row.last_seq);
        if ((updated.changes ?? 0) === 1) return id;
      } catch (e) {
        const msg = (e as Error).message ?? "";
        if (msg.includes("database is locked")) continue;
        throw e;
      }
    }
    throw new Error("sql allocation contention: retry budget exhausted");
  } finally {
    db.close?.();
  }
}

function readPid(file: string): number | null {
  try {
    const value = readFileSync(file, "utf-8").trim();
    if (!value) return null;
    const pid = Number.parseInt(value, 10);
    return Number.isNaN(pid) || pid <= 0 ? null : pid;
  } catch {
    return null;
  }
}

function pidAlive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

function sleepSeconds(sec: number): void {
  if (sec <= 0) return;
  const i32 = new Int32Array(new SharedArrayBuffer(4));
  Atomics.wait(i32, 0, 0, sec * 1000);
}

function runDiscover(): number {
  console.log(
    JSON.stringify({
      impl: "typescript",
      orchestration: "native",
      actions: [
        "discover",
        "scaffold",
        "run",
        "start",
        "stop",
        "status",
        "logs",
        "saf",
        "saf-wid",
        "wir",
        "wism",
        "wihp",
        "wipr",
        "duplex",
      ],
      transports: ["auto", "mqtt", "ws", "redis", "null", "stdout"],
    })
  );
  return 0;
}

function runScaffold(c: Canon): number {
  if (!c.D || c.D.length === 0) throw new Error("D=<name> required for A=scaffold");
  const root = resolve(c.D);
  mkdirSync(resolve(root, "state"), { recursive: true });
  mkdirSync(resolve(root, "logs"), { recursive: true });
  console.log(`scaffolded ${root}`);
  return 0;
}

function runStatus(): number {
  const pidFile = runtimePidFile();
  const logFile = runtimeLogFile();
  const pid = readPid(pidFile);
  if (pid !== null && pidAlive(pid)) {
    console.log(`wid-typescript status=running pid=${pid} log=${logFile}`);
    return 0;
  }
  try {
    unlinkSync(pidFile);
  } catch {}
  console.log("wid-typescript status=stopped");
  return 0;
}

function runLogs(): number {
  const logFile = runtimeLogFile();
  if (!existsSync(logFile)) {
    console.log("wid-typescript logs: empty");
    return 0;
  }
  process.stdout.write(readFileSync(logFile, "utf-8"));
  return 0;
}

function runStop(): number {
  const pidFile = runtimePidFile();
  const pid = readPid(pidFile);
  if (pid === null || !pidAlive(pid)) {
    try {
      unlinkSync(pidFile);
    } catch {}
    console.log("wid-typescript stop: not running");
    return 0;
  }
  try {
    process.kill(pid, "SIGTERM");
  } catch (e) {
    throw new Error(`failed to stop pid=${pid}: ${(e as Error).message}`);
  }
  try {
    unlinkSync(pidFile);
  } catch {}
  console.log(`wid-typescript stop: stopped pid=${pid}`);
  return 0;
}

function daemonCanonicalArgs(c: Canon, action: string): string[] {
  return [
    `A=${action}`,
    `W=${c.W}`,
    `L=${c.L}`,
    `D=${c.D.length > 0 ? c.D : "#"}`,
    `I=${c.I}`,
    `E=${c.E}`,
    `Z=${c.Z}`,
    `T=${c.T}`,
    `R=${c.R}`,
    `M=${c.M ? "true" : "false"}`,
    `N=${c.N}`,
  ];
}

function runStart(c: Canon): number {
  const dir = runtimeDir();
  mkdirSync(dir, { recursive: true });
  const pidFile = runtimePidFile();
  const logFile = runtimeLogFile();

  const existing = readPid(pidFile);
  if (existing !== null && pidAlive(existing)) {
    console.log(`wid-typescript start: already-running pid=${existing} log=${logFile}`);
    return 0;
  }

  mkdirSync(dirname(logFile), { recursive: true });
  const fd = openSync(logFile, "a");
  const child = spawn(process.execPath, [process.argv[1]!, "__daemon", ...daemonCanonicalArgs(c, "run")], {
    detached: true,
    stdio: ["ignore", fd, fd],
  });
  closeSync(fd);
  child.unref();
  writeFileSync(pidFile, `${child.pid}\n`, "utf-8");
  console.log(`wid-typescript start: started pid=${child.pid} log=${logFile}`);
  return 0;
}

function runServiceLoop(c: Canon, action: string): number {
  const { stateMode, transport: rawTransport } = parseStateAndTransport(c);
  let transport = rawTransport === "auto" ? "mqtt" : rawTransport;
  if (
    ["saf-wid", "wir", "wism", "wihp", "wipr", "duplex"].includes(action) &&
    !LOCAL_SERVICE_TRANSPORTS.has(transport)
  ) {
    throw new Error(`invalid transport for A=${action}: ${transport}`);
  }

  const dir = dataDir(c);
  mkdirSync(dir, { recursive: true });
  const logLevel = process.env.LOG_LEVEL || "INFO";
  const max = c.N <= 0 ? Number.POSITIVE_INFINITY : c.N;
  const gen = new WidGen({ W: c.W, Z: c.Z, timeUnit: c.T });

  let i = 0;
  while (i < max) {
    i += 1;
    const wid = gen.next();
    if (transport !== "null") {
      if (["saf-wid", "wism", "wihp", "wipr"].includes(action)) {
        console.log(
          JSON.stringify({
            impl: "typescript",
            action,
            tick: i,
            transport,
            W: c.W,
            Z: c.Z,
            time_unit: c.T,
            wid,
            interval: c.L,
            log_level: logLevel,
            data_dir: dir,
          })
        );
      } else if (action === "duplex") {
        const bTransport = c.I !== "auto" && LOCAL_SERVICE_TRANSPORTS.has(c.I) ? c.I : "ws";
        console.log(
          JSON.stringify({
            impl: "typescript",
            action: "duplex",
            tick: i,
            a_transport: transport,
            b_transport: bTransport,
            interval: c.L,
            data_dir: dir,
          })
        );
      } else {
        console.log(
          JSON.stringify({
            impl: "typescript",
            action,
            tick: i,
            transport,
            interval: c.L,
            log_level: logLevel,
            data_dir: dir,
            state_mode: stateMode,
          })
        );
      }
    }
    if (i < max && c.L > 0) sleepSeconds(c.L);
  }
  return 0;
}

function runNativeOrchestration(c: Canon): number {
  switch (c.A) {
    case "discover":
      return runDiscover();
    case "scaffold":
      return runScaffold(c);
    case "run":
      return runServiceLoop(c, "run");
    case "start":
      return runStart(c);
    case "stop":
      return runStop();
    case "status":
      return runStatus();
    case "logs":
      return runLogs();
    case "saf":
      return runServiceLoop(c, "saf");
    case "saf-wid":
      return runServiceLoop(c, "saf-wid");
    case "wir":
      return runServiceLoop(c, "wir");
    case "wism":
      return runServiceLoop(c, "wism");
    case "wihp":
      return runServiceLoop(c, "wihp");
    case "wipr":
      return runServiceLoop(c, "wipr");
    case "duplex":
      return runServiceLoop(c, "duplex");
    default:
      throw new Error(`unknown A=${c.A}`);
  }
}

function runCanonical(args: string[]): number {
  const c = parseCanonical(args);
  if (c.A === "help-actions") {
    printActions();
    return 0;
  }

  const { stateMode } = parseStateAndTransport(c);
  const canonDataDir = dataDir(c);
  mkdirSync(canonDataDir, { recursive: true });
  const genOptions = { W: c.W, Z: c.Z, timeUnit: c.T } as const;

  if (c.A === "next") {
    if (stateMode === "sql") {
      console.log(sqlAllocateNextWid(c));
    } else {
      console.log(new WidGen(genOptions).next());
    }
    return 0;
  }

  if (c.A === "stream") {
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
      if (emitted < max && c.L > 0) sleepSeconds(c.L);
    }
    return 0;
  }

  if (c.A === "healthcheck") {
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

  if (c.A === "sign") return runSign(c);
  if (c.A === "verify") return runVerify(c);
  if (c.A === "w-otp") return runWOtp(c);

  return runNativeOrchestration(c);
}

function printCompletion(shell: string): void {
  if (shell === "bash") {
    process.stdout.write(
      `_wid_complete() {
  local cur="\${COMP_WORDS[COMP_CWORD]}"
  local cmds="next stream healthcheck validate parse help-actions bench selftest completion"
  if [[ "$cur" == *=* ]]; then
    local key="\${cur%%=*}" val="\${cur#*=}" vals=""
    case "$key" in
      A) vals="next stream healthcheck sign verify w-otp discover scaffold run start stop status logs saf saf-wid wir wism wihp wipr duplex help-actions" ;;
      T) vals="sec ms" ;;
      I) vals="auto sh bash" ;;
      E) vals="state stateless sql" ;;
      R) vals="auto mqtt ws redis null stdout" ;;
      M) vals="true false" ;;
    esac
    local IFS=$'\\n'
    COMPREPLY=(\$(for v in $vals; do [[ "$v" == "$val"* ]] && printf '%s\\n' "\${key}=\${v}"; done))
  else
    local kv="A= W= Z= T= N= L= D= I= E= R= M="
    COMPREPLY=(\$(compgen -W "$cmds $kv" -- "$cur"))
  fi
}
complete -o nospace -F _wid_complete wid-ts
`
    );
  } else if (shell === "zsh") {
    process.stdout.write(
      `#compdef wid-ts
_wid_complete() {
  local cur="\${words[-1]}"
  local -a cmds=(next stream healthcheck validate parse help-actions bench selftest completion)
  if [[ "$cur" == *=* ]]; then
    local key="\${cur%%=*}"
    local -a vals=()
    case "$key" in
      A) vals=(next stream healthcheck sign verify w-otp discover scaffold run start stop status logs saf saf-wid wir wism wihp wipr duplex help-actions) ;;
      T) vals=(sec ms) ;;
      I) vals=(auto sh bash) ;;
      E) vals=(state stateless sql) ;;
      R) vals=(auto mqtt ws redis null stdout) ;;
      M) vals=(true false) ;;
    esac
    compadd -P "\${key}=" -- "\${vals[@]}"
  else
    compadd -- "\${cmds[@]}" A= W= Z= T= N= L= D= I= E= R= M=
  fi
}
_wid_complete "$@"
compdef _wid_complete wid-ts
`
    );
  } else if (shell === "fish") {
    process.stdout.write(
      `complete -c wid-ts -e
complete -c wid-ts -f -n 'not __fish_seen_subcommand_from next stream healthcheck validate parse help-actions bench selftest completion' -a next -d 'Emit one WID'
complete -c wid-ts -f -n 'not __fish_seen_subcommand_from next stream healthcheck validate parse help-actions bench selftest completion' -a stream -d 'Stream WIDs continuously'
complete -c wid-ts -f -n 'not __fish_seen_subcommand_from next stream healthcheck validate parse help-actions bench selftest completion' -a healthcheck -d 'Generate and validate a sample WID'
complete -c wid-ts -f -n 'not __fish_seen_subcommand_from next stream healthcheck validate parse help-actions bench selftest completion' -a validate -d 'Validate a WID string'
complete -c wid-ts -f -n 'not __fish_seen_subcommand_from next stream healthcheck validate parse help-actions bench selftest completion' -a parse -d 'Parse a WID string'
complete -c wid-ts -f -n 'not __fish_seen_subcommand_from next stream healthcheck validate parse help-actions bench selftest completion' -a help-actions -d 'Show canonical action matrix'
complete -c wid-ts -f -n 'not __fish_seen_subcommand_from next stream healthcheck validate parse help-actions bench selftest completion' -a completion -d 'Print shell completion script'
complete -c wid-ts -f -a 'A=next A=stream A=healthcheck A=sign A=verify A=w-otp A=start A=stop A=status A=logs A=help-actions' -d 'Action'
complete -c wid-ts -f -a 'T=sec T=ms' -d 'Time unit'
complete -c wid-ts -f -a 'I=auto I=sh I=bash' -d 'Input source'
complete -c wid-ts -f -a 'E=state E=stateless E=sql' -d 'State mode'
complete -c wid-ts -f -a 'R=auto R=mqtt R=ws R=redis R=null R=stdout' -d 'Transport'
complete -c wid-ts -f -a 'M=true M=false' -d 'Milliseconds mode'
complete -c wid-ts -f -a 'W=' -d 'Sequence width'
complete -c wid-ts -f -a 'Z=' -d 'Padding length'
complete -c wid-ts -f -a 'N=' -d 'Count'
complete -c wid-ts -f -a 'L=' -d 'Interval seconds'
`
    );
  } else {
    process.stderr.write(`error: unknown shell '${shell}'. Use: wid completion bash|zsh|fish\n`);
    process.exit(1);
  }
}

function runSelftest(): number {
  const wg = new WidGen({ W: 4, Z: 0, timeUnit: "sec" });
  const a = wg.next();
  const b = wg.next();
  if (!(a < b)) return 1;
  if (!validateWid(a, 4, 0, "sec")) return 1;

  const hg = new HLCWidGen({ node: "node01", W: 4, Z: 0, timeUnit: "sec" });
  const h = hg.next();
  if (!validateHlcWid(h, 4, 0, "sec")) return 1;

  if (validateWid("20260212T091530.0000Z-node01", 4, 0, "sec")) return 1;
  if (validateHlcWid("20260212T091530.0000Z", 4, 0, "sec")) return 1;
  if (!validateWid("20260212T091530123.0000Z", 4, 0, "ms")) return 1;
  if (!validateHlcWid("20260212T091530123.0000Z-node01", 4, 0, "ms")) return 1;
  return 0;
}

function main(): number {
  const args = process.argv.slice(2);
  if (args.length === 0) {
    printHelp();
    return 2;
  }

  if (args[0] === "__daemon") {
    try {
      return runCanonical(args.slice(1));
    } catch (e) {
      console.error(`error: ${(e as Error).message}`);
      return 1;
    }
  }

  if (args.some((a) => a.includes("="))) {
    try {
      return runCanonical(args);
    } catch (e) {
      console.error(`error: ${(e as Error).message}`);
      return 1;
    }
  }

  const [cmd, ...rest] = args;
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

  try {
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
        throw new Error(`unknown command: ${cmd}`);
    }
  } catch (e) {
    console.error(`error: ${(e as Error).message}`);
    return 1;
  }
}

process.exit(main());
