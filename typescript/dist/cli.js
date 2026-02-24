#!/usr/bin/env node
"use strict";

// typescript/src/cli.ts
var import_node_fs = require("fs");
var import_node_path = require("path");
var import_node_child_process = require("child_process");
var import_node_crypto = require("crypto");

// typescript/src/time.ts
function parseTimeUnit(input) {
  if (input === "sec" || input === "ms") {
    return input;
  }
  throw new Error("time-unit must be sec or ms");
}
function timeDigits(unit) {
  return unit === "ms" ? 9 : 6;
}

// typescript/src/wid.ts
var WID_BASE_RE_CACHE = /* @__PURE__ */ new Map();
var HEX_RE_CACHE = /* @__PURE__ */ new Map();
var SCOPE_PATTERN = /^[A-Za-z0-9_]+(?:-[A-Za-z0-9_]+)*$/;
function widBaseRe(W, unit) {
  const key = `${W}:${unit}`;
  const cached = WID_BASE_RE_CACHE.get(key);
  if (cached) return cached;
  const re = new RegExp(`^(\\d{8})T(\\d{${timeDigits(unit)}})\\.(\\d{${W}})Z(.*)?$`);
  WID_BASE_RE_CACHE.set(key, re);
  return re;
}
function hexRe(Z) {
  const cached = HEX_RE_CACHE.get(Z);
  if (cached) return cached;
  const re = new RegExp(`^[0-9a-f]{${Z}}$`);
  HEX_RE_CACHE.set(Z, re);
  return re;
}
function bytesToHex(bytes) {
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}
function randomHexChars(Z) {
  if (!globalThis.crypto?.getRandomValues) {
    throw new Error("Secure random generator unavailable in this runtime");
  }
  const bytes = new Uint8Array(Math.ceil(Z / 2));
  globalThis.crypto.getRandomValues(bytes);
  return bytesToHex(bytes).slice(0, Z);
}
function parseSuffix(suffix, Z) {
  if (!suffix) {
    return { scope: null, padding: null };
  }
  if (!suffix.startsWith("-")) {
    return null;
  }
  const body = suffix.slice(1);
  if (!body) {
    return null;
  }
  let scope = null;
  let padding = null;
  if (Z > 0) {
    const splitAt = body.lastIndexOf("-");
    if (splitAt >= 0) {
      const maybeScope = body.slice(0, splitAt);
      const maybePadding = body.slice(splitAt + 1);
      if (hexRe(Z).test(maybePadding)) {
        padding = maybePadding;
        scope = maybeScope || null;
      } else if (maybePadding.length === Z && /^[0-9A-Fa-f]+$/.test(maybePadding)) {
        return null;
      } else {
        scope = body;
      }
    } else if (hexRe(Z).test(body)) {
      padding = body;
    } else if (body.length === Z && /^[0-9A-Fa-f]+$/.test(body)) {
      return null;
    } else {
      scope = body;
    }
  } else {
    scope = body;
  }
  if (scope !== null && !SCOPE_PATTERN.test(scope)) {
    return null;
  }
  if (padding !== null && !hexRe(Z).test(padding)) {
    return null;
  }
  return { scope, padding };
}
function parseTimestamp(dateStr, timeStr, timeUnit) {
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
function parseCore(wid, W, Z, timeUnit) {
  if (W <= 0 || Z < 0) return null;
  const match = widBaseRe(W, timeUnit).exec(wid);
  if (!match) return null;
  const [, dateStr, timeStr, seqStr, suffixRaw] = match;
  const suffix = suffixRaw ?? "";
  const timestamp = parseTimestamp(dateStr, timeStr, timeUnit);
  if (!timestamp) return null;
  const parsedSuffix = parseSuffix(suffix, Z);
  if (!parsedSuffix) return null;
  return {
    raw: wid,
    timestamp,
    sequence: parseInt(seqStr, 10),
    scope: parsedSuffix.scope,
    padding: parsedSuffix.padding
  };
}
function validateWid(wid, W = 4, Z = 6, timeUnit = "sec") {
  return parseCore(wid, W, Z, timeUnit) !== null;
}
function parseWid(wid, W = 4, Z = 6, timeUnit = "sec") {
  return parseCore(wid, W, Z, timeUnit);
}
var WidGen = class {
  /** Create a generator with optional persistence and precision control. */
  constructor(options = {}) {
    this.lastSec = 0;
    this.lastSeq = -1;
    this.cachedSec = -1;
    this.cachedTs = "";
    const {
      W = 4,
      Z = 6,
      scope,
      timeUnit = "sec",
      stateStore,
      stateKey = "wid",
      autoPersist = false
    } = options;
    if (W <= 0) throw new Error("W must be > 0");
    if (Z < 0) throw new Error("Z must be >= 0");
    if (scope && !SCOPE_PATTERN.test(scope)) {
      throw new Error("Invalid scope format");
    }
    this.W = W;
    this.Z = Z;
    this.scope = scope ?? null;
    this.timeUnit = timeUnit;
    this.maxSeq = Math.pow(10, W) - 1;
    this.stateStore = stateStore ?? null;
    this.stateKey = stateKey;
    this.autoPersist = autoPersist;
    if (this.autoPersist && this.stateStore) {
      const loaded = this.stateStore.load(this.stateKey);
      if (loaded && Number.isFinite(loaded.lastSec) && Number.isFinite(loaded.lastSeq) && loaded.lastSec >= 0 && loaded.lastSeq >= -1) {
        this.lastSec = loaded.lastSec;
        this.lastSeq = loaded.lastSeq;
      }
    }
  }
  persistState() {
    if (!this.autoPersist || !this.stateStore) return;
    try {
      this.stateStore.save(this.stateKey, { lastSec: this.lastSec, lastSeq: this.lastSeq });
    } catch {
    }
  }
  tsForTick(tick) {
    if (tick !== this.cachedSec) {
      this.cachedSec = tick;
      const sec = this.timeUnit === "ms" ? Math.floor(tick / 1e3) : tick;
      const ms = this.timeUnit === "ms" ? tick % 1e3 : 0;
      const d = new Date(sec * 1e3);
      const year = d.getUTCFullYear();
      const month = String(d.getUTCMonth() + 1).padStart(2, "0");
      const day = String(d.getUTCDate()).padStart(2, "0");
      const hour = String(d.getUTCHours()).padStart(2, "0");
      const minute = String(d.getUTCMinutes()).padStart(2, "0");
      const second = String(d.getUTCSeconds()).padStart(2, "0");
      const milli = String(ms).padStart(3, "0");
      this.cachedTs = this.timeUnit === "ms" ? `${year}${month}${day}T${hour}${minute}${second}${milli}` : `${year}${month}${day}T${hour}${minute}${second}`;
    }
    return this.cachedTs;
  }
  nowTick() {
    if (this.timeUnit === "ms") {
      return Date.now();
    }
    return Math.floor(Date.now() / 1e3);
  }
  next() {
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
    if (this.scope) {
      wid += `-${this.scope}`;
    }
    if (this.Z > 0) {
      wid += `-${randomHexChars(this.Z)}`;
    }
    this.persistState();
    return wid;
  }
  nextN(n) {
    return Array.from({ length: n }, () => this.next());
  }
  get state() {
    return { lastSec: this.lastSec, lastSeq: this.lastSeq };
  }
  restoreState(lastSec, lastSeq) {
    this.lastSec = lastSec;
    this.lastSeq = lastSeq;
    this.persistState();
  }
};

// typescript/src/hlc.ts
var HLC_BASE_RE_CACHE = /* @__PURE__ */ new Map();
var HEX_RE_CACHE2 = /* @__PURE__ */ new Map();
var NODE_RE = /^[A-Za-z0-9_]+$/;
function hlcBaseRe(W, unit) {
  const key = `${W}:${unit}`;
  const cached = HLC_BASE_RE_CACHE.get(key);
  if (cached) return cached;
  const re = new RegExp(`^(\\d{8})T(\\d{${timeDigits(unit)}})\\.(\\d{${W}})Z-([A-Za-z0-9_]+)(.*)$`);
  HLC_BASE_RE_CACHE.set(key, re);
  return re;
}
function hexRe2(Z) {
  const cached = HEX_RE_CACHE2.get(Z);
  if (cached) return cached;
  const re = new RegExp(`^[0-9a-f]{${Z}}$`);
  HEX_RE_CACHE2.set(Z, re);
  return re;
}
function randomHexChars2(Z) {
  if (!globalThis.crypto?.getRandomValues) {
    throw new Error("Secure random generator unavailable in this runtime");
  }
  const bytes = new Uint8Array(Math.ceil(Z / 2));
  globalThis.crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("").slice(0, Z);
}
function isValidNode(node) {
  return NODE_RE.test(node);
}
function parseTimestamp2(dateStr, timeStr, timeUnit) {
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
function validateHlcWid(wid, W = 4, Z = 0, timeUnit = "sec") {
  return parseHlcWid(wid, W, Z, timeUnit) !== null;
}
function parseHlcWid(wid, W = 4, Z = 0, timeUnit = "sec") {
  if (W <= 0 || Z < 0) return null;
  const match = hlcBaseRe(W, timeUnit).exec(wid);
  if (!match) return null;
  const [, dateStr, timeStr, lcStr, node, suffixRaw] = match;
  const suffix = suffixRaw ?? "";
  if (!isValidNode(node)) return null;
  const timestamp = parseTimestamp2(dateStr, timeStr, timeUnit);
  if (!timestamp) return null;
  const logicalCounter = parseInt(lcStr, 10);
  let padding = null;
  if (suffix) {
    if (!suffix.startsWith("-")) return null;
    const seg = suffix.slice(1);
    if (Z === 0) return null;
    if (!hexRe2(Z).test(seg)) return null;
    padding = seg;
  }
  return { raw: wid, timestamp, logicalCounter, node, padding };
}
var HLCWidGen = class {
  constructor(options) {
    this.pt = 0;
    this.lc = 0;
    this.cachedTick = -1;
    this.cachedTs = "";
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
  nowTick() {
    if (this.timeUnit === "ms") {
      return Date.now();
    }
    return Math.floor(Date.now() / 1e3);
  }
  tsForTick(tick) {
    if (tick !== this.cachedTick) {
      this.cachedTick = tick;
      const sec = this.timeUnit === "ms" ? Math.floor(tick / 1e3) : tick;
      const ms = this.timeUnit === "ms" ? tick % 1e3 : 0;
      const d = new Date(sec * 1e3);
      const year = d.getUTCFullYear();
      const mo = String(d.getUTCMonth() + 1).padStart(2, "0");
      const dy = String(d.getUTCDate()).padStart(2, "0");
      const hr = String(d.getUTCHours()).padStart(2, "0");
      const mi = String(d.getUTCMinutes()).padStart(2, "0");
      const sc = String(d.getUTCSeconds()).padStart(2, "0");
      const milli = String(ms).padStart(3, "0");
      this.cachedTs = this.timeUnit === "ms" ? `${year}${mo}${dy}T${hr}${mi}${sc}${milli}` : `${year}${mo}${dy}T${hr}${mi}${sc}`;
    }
    return this.cachedTs;
  }
  rollover() {
    if (this.lc > this.maxLC) {
      this.pt += 1;
      this.lc = 0;
    }
  }
  observe(remotePT, remoteLC) {
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
  next() {
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
      wid += `-${randomHexChars2(this.Z)}`;
    }
    return wid;
  }
  nextN(n) {
    return Array.from({ length: n }, () => this.next());
  }
  get state() {
    return { pt: this.pt, lc: this.lc };
  }
  restoreState(pt, lc) {
    if (pt < 0 || lc < 0) throw new Error("invalid state");
    this.pt = pt;
    this.lc = lc;
  }
};

// typescript/src/manifest.ts
var MANIFEST_MAGIC = new Uint8Array([83, 89, 78, 77]);
var MAX_MANIFEST_SIZE = 64 * 1024;

// typescript/src/cli.ts
var LOCAL_SERVICE_TRANSPORTS = /* @__PURE__ */ new Set(["mqtt", "ws", "redis", "null", "stdout"]);
function printHelp() {
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
function printActions() {
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
function parseIntStrict(value, name) {
  const n = Number.parseInt(value, 10);
  if (!Number.isFinite(n) || Number.isNaN(n)) throw new Error(`invalid integer for ${name}`);
  return n;
}
function parseOpts(args, allowCount) {
  const opts = {
    kind: "wid",
    node: process.env.NODE ?? "ts",
    W: 4,
    Z: 6,
    timeUnit: "sec",
    count: 0,
    json: false
  };
  for (let i = 0; i < args.length; i += 1) {
    const arg = args[i];
    switch (arg) {
      case "--kind":
        if (i + 1 >= args.length) throw new Error("missing value for --kind");
        opts.kind = args[++i];
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
function runNext(args) {
  const opts = parseOpts(args, false);
  if (opts.kind === "wid") {
    console.log(new WidGen({ W: opts.W, Z: opts.Z, timeUnit: opts.timeUnit }).next());
    return;
  }
  console.log(new HLCWidGen({ node: opts.node, W: opts.W, Z: opts.Z, timeUnit: opts.timeUnit }).next());
}
function runStream(args) {
  const opts = parseOpts(args, true);
  if (opts.kind === "wid") {
    const gen2 = new WidGen({ W: opts.W, Z: opts.Z, timeUnit: opts.timeUnit });
    for (let i = 0; opts.count === 0 || i < opts.count; i += 1) console.log(gen2.next());
    return;
  }
  const gen = new HLCWidGen({ node: opts.node, W: opts.W, Z: opts.Z, timeUnit: opts.timeUnit });
  for (let i = 0; opts.count === 0 || i < opts.count; i += 1) console.log(gen.next());
}
function runValidate(args) {
  if (args.length === 0) throw new Error("validate requires an id");
  const id = args[0];
  const opts = parseOpts(args.slice(1), false);
  const ok = opts.kind === "wid" ? validateWid(id, opts.W, opts.Z, opts.timeUnit) : validateHlcWid(id, opts.W, opts.Z, opts.timeUnit);
  console.log(ok ? "true" : "false");
  if (!ok) throw new Error("invalid wid");
}
function runParse(args) {
  if (args.length === 0) throw new Error("parse requires an id");
  const id = args[0];
  const opts = parseOpts(args.slice(1), false);
  if (opts.kind === "wid") {
    const parsed2 = parseWid(id, opts.W, opts.Z, opts.timeUnit);
    if (!parsed2) {
      console.log("null");
      throw new Error("invalid wid");
    }
    if (opts.json) {
      console.log(
        JSON.stringify({
          raw: parsed2.raw,
          timestamp: parsed2.timestamp.toISOString(),
          sequence: parsed2.sequence,
          padding: parsed2.padding
        })
      );
      return;
    }
    console.log(`raw=${parsed2.raw}`);
    console.log(`timestamp=${parsed2.timestamp.toISOString()}`);
    console.log(`sequence=${parsed2.sequence}`);
    console.log(`padding=${parsed2.padding ?? ""}`);
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
        padding: parsed.padding
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
function runHealthcheck(args) {
  const opts = parseOpts(args, false);
  const sample = opts.kind === "wid" ? new WidGen({ W: opts.W, Z: opts.Z, timeUnit: opts.timeUnit }).next() : new HLCWidGen({ node: opts.node, W: opts.W, Z: opts.Z, timeUnit: opts.timeUnit }).next();
  const ok = opts.kind === "wid" ? validateWid(sample, opts.W, opts.Z, opts.timeUnit) : validateHlcWid(sample, opts.W, opts.Z, opts.timeUnit);
  if (opts.json) {
    console.log(
      JSON.stringify({
        ok,
        kind: opts.kind,
        W: opts.W,
        Z: opts.Z,
        time_unit: opts.timeUnit,
        sample_id: sample
      })
    );
  } else {
    console.log(`ok=${ok ? "true" : "false"} kind=${opts.kind} sample=${sample}`);
  }
  if (!ok) throw new Error("healthcheck failed");
}
function runBench(args) {
  const opts = parseOpts(args, true);
  const n = opts.count > 0 ? opts.count : 1e5;
  const start = process.hrtime.bigint();
  if (opts.kind === "wid") {
    const g = new WidGen({ W: opts.W, Z: opts.Z, timeUnit: opts.timeUnit });
    for (let i = 0; i < n; i += 1) g.next();
  } else {
    const g = new HLCWidGen({ node: opts.node, W: opts.W, Z: opts.Z, timeUnit: opts.timeUnit });
    for (let i = 0; i < n; i += 1) g.next();
  }
  const secs = Number(process.hrtime.bigint() - start) / 1e9;
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
      ids_per_sec: n / s
    })
  );
}
function parseCanonical(args) {
  const out = {
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
    N: 0
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
  out.A = out.A === "id" || out.A === "default" ? "next" : out.A === "hc" ? "healthcheck" : out.A === "raf" ? "saf" : out.A === "waf" || out.A === "wraf" ? "saf-wid" : out.A === "witr" ? "wir" : out.A === "wim" ? "wism" : out.A === "wih" ? "wihp" : out.A === "wip" ? "wipr" : out.A;
  if (out.W <= 0) throw new Error("W must be > 0");
  if (out.Z < 0 || out.N < 0 || out.L < 0) throw new Error("Z/N/L must be >= 0");
  if (!["auto", "mqtt", "ws", "redis", "null", "stdout"].includes(out.R)) {
    throw new Error("invalid R transport");
  }
  return out;
}
function defaultValueFor(key) {
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
function b64urlEncode(buf) {
  return buf.toString("base64").replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}
function b64urlDecode(s) {
  let std = s.replace(/-/g, "+").replace(/_/g, "/");
  const m = std.length % 4;
  if (m === 2) std += "==";
  else if (m === 3) std += "=";
  else if (m === 1) throw new Error("invalid base64url signature length");
  return Buffer.from(std, "base64");
}
function buildSignVerifyMessage(c) {
  const wid = c.WID ?? "";
  if (!wid) throw new Error("WID=<wid_string> required");
  const parts = [Buffer.from(wid, "utf8")];
  if (c.DATA && c.DATA.length > 0) {
    if (!(0, import_node_fs.existsSync)(c.DATA)) throw new Error(`data file not found: ${c.DATA}`);
    parts.push((0, import_node_fs.readFileSync)(c.DATA));
  }
  return Buffer.concat(parts);
}
function runSign(c) {
  const keyPath = c.KEY ?? "";
  if (!keyPath) throw new Error("KEY=<private_key_path> required for A=sign");
  if (!(0, import_node_fs.existsSync)(keyPath)) throw new Error(`private key file not found: ${keyPath}`);
  const message = buildSignVerifyMessage(c);
  const key = (0, import_node_crypto.createPrivateKey)((0, import_node_fs.readFileSync)(keyPath));
  const sig = (0, import_node_crypto.sign)(null, message, key);
  const out = b64urlEncode(sig);
  if (c.OUT && c.OUT.length > 0) (0, import_node_fs.writeFileSync)(c.OUT, out, "utf8");
  else console.log(out);
  return 0;
}
function runVerify(c) {
  const keyPath = c.KEY ?? "";
  const sigText = c.SIG ?? "";
  if (!keyPath) throw new Error("KEY=<public_key_path> required for A=verify");
  if (!sigText) throw new Error("SIG=<signature_string> required for A=verify");
  if (!(0, import_node_fs.existsSync)(keyPath)) throw new Error(`public key file not found: ${keyPath}`);
  const message = buildSignVerifyMessage(c);
  const key = (0, import_node_crypto.createPublicKey)((0, import_node_fs.readFileSync)(keyPath));
  const ok = (0, import_node_crypto.verify)(null, message, key, b64urlDecode(sigText));
  if (ok) {
    console.log("Signature valid.");
    return 0;
  }
  console.error("Signature invalid.");
  return 1;
}
function resolveWOtpSecret(raw) {
  if ((0, import_node_fs.existsSync)(raw)) return (0, import_node_fs.readFileSync)(raw, "utf8").trim();
  return raw.trim();
}
function computeWOtp(secret, wid, digits) {
  const digest = (0, import_node_crypto.createHmac)("sha256", Buffer.from(secret, "utf8")).update(Buffer.from(wid, "utf8")).digest();
  const binary = digest.readUInt32BE(0);
  const mod = 10 ** digits;
  return String(binary % mod).padStart(digits, "0");
}
function wotpWidTickMs(wid) {
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
function runWOtp(c) {
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
    if (delta < 0 && -delta > maxFutureSec * 1e3) throw new Error("OTP invalid: WID timestamp is too far in the future");
    if (delta >= 0 && maxAgeSec > 0 && delta > maxAgeSec * 1e3) throw new Error("OTP invalid: WID timestamp is too old");
  }
  const got = Buffer.from(code, "utf8");
  const exp = Buffer.from(otp, "utf8");
  const ok = got.length === exp.length && (0, import_node_crypto.timingSafeEqual)(got, exp);
  if (ok) {
    console.log("OTP valid.");
    return 0;
  }
  console.error("OTP invalid.");
  return 1;
}
function parseStateAndTransport(c) {
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
function runtimeDir() {
  return (0, import_node_path.resolve)(".local/wid/typescript");
}
function runtimePidFile() {
  return (0, import_node_path.resolve)(runtimeDir(), "service.pid");
}
function runtimeLogFile() {
  return (0, import_node_path.resolve)(runtimeDir(), "service.log");
}
function dataDir(c) {
  return c.D && c.D.length > 0 ? (0, import_node_path.resolve)(c.D) : (0, import_node_path.resolve)(".local/services");
}
function resolveNodeSqliteDatabaseSync() {
  const proc = globalThis.process;
  if (!proc?.versions?.node) throw new Error("SQLite requires Node.js");
  const builtin = typeof proc.getBuiltinModule === "function" ? proc.getBuiltinModule("node:sqlite") : null;
  if (builtin && typeof builtin === "object" && "DatabaseSync" in builtin) {
    return builtin.DatabaseSync;
  }
  throw new Error("node:sqlite unavailable in this Node runtime");
}
function sqlStatePath(c) {
  return (0, import_node_path.resolve)(dataDir(c), "wid_state.sqlite");
}
function sqlStateKey(c) {
  return `wid:ts:${c.W}:${c.Z}:${c.T}`;
}
function sqlAllocateNextWid(c) {
  const DatabaseSync = resolveNodeSqliteDatabaseSync();
  const db = new DatabaseSync(sqlStatePath(c), { timeout: 5e3 });
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
        const row = selectStmt.get(key);
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
        const msg = e.message ?? "";
        if (msg.includes("database is locked")) continue;
        throw e;
      }
    }
    throw new Error("sql allocation contention: retry budget exhausted");
  } finally {
    db.close?.();
  }
}
function readPid(file) {
  try {
    const value = (0, import_node_fs.readFileSync)(file, "utf-8").trim();
    if (!value) return null;
    const pid = Number.parseInt(value, 10);
    return Number.isNaN(pid) || pid <= 0 ? null : pid;
  } catch {
    return null;
  }
}
function pidAlive(pid) {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}
function sleepSeconds(sec) {
  if (sec <= 0) return;
  const i32 = new Int32Array(new SharedArrayBuffer(4));
  Atomics.wait(i32, 0, 0, sec * 1e3);
}
function runDiscover() {
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
        "duplex"
      ],
      transports: ["auto", "mqtt", "ws", "redis", "null", "stdout"]
    })
  );
  return 0;
}
function runScaffold(c) {
  if (!c.D || c.D.length === 0) throw new Error("D=<name> required for A=scaffold");
  const root = (0, import_node_path.resolve)(c.D);
  (0, import_node_fs.mkdirSync)((0, import_node_path.resolve)(root, "state"), { recursive: true });
  (0, import_node_fs.mkdirSync)((0, import_node_path.resolve)(root, "logs"), { recursive: true });
  console.log(`scaffolded ${root}`);
  return 0;
}
function runStatus() {
  const pidFile = runtimePidFile();
  const logFile = runtimeLogFile();
  const pid = readPid(pidFile);
  if (pid !== null && pidAlive(pid)) {
    console.log(`wid-typescript status=running pid=${pid} log=${logFile}`);
    return 0;
  }
  try {
    (0, import_node_fs.unlinkSync)(pidFile);
  } catch {
  }
  console.log("wid-typescript status=stopped");
  return 0;
}
function runLogs() {
  const logFile = runtimeLogFile();
  if (!(0, import_node_fs.existsSync)(logFile)) {
    console.log("wid-typescript logs: empty");
    return 0;
  }
  process.stdout.write((0, import_node_fs.readFileSync)(logFile, "utf-8"));
  return 0;
}
function runStop() {
  const pidFile = runtimePidFile();
  const pid = readPid(pidFile);
  if (pid === null || !pidAlive(pid)) {
    try {
      (0, import_node_fs.unlinkSync)(pidFile);
    } catch {
    }
    console.log("wid-typescript stop: not running");
    return 0;
  }
  try {
    process.kill(pid, "SIGTERM");
  } catch (e) {
    throw new Error(`failed to stop pid=${pid}: ${e.message}`);
  }
  try {
    (0, import_node_fs.unlinkSync)(pidFile);
  } catch {
  }
  console.log(`wid-typescript stop: stopped pid=${pid}`);
  return 0;
}
function daemonCanonicalArgs(c, action) {
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
    `N=${c.N}`
  ];
}
function runStart(c) {
  const dir = runtimeDir();
  (0, import_node_fs.mkdirSync)(dir, { recursive: true });
  const pidFile = runtimePidFile();
  const logFile = runtimeLogFile();
  const existing = readPid(pidFile);
  if (existing !== null && pidAlive(existing)) {
    console.log(`wid-typescript start: already-running pid=${existing} log=${logFile}`);
    return 0;
  }
  (0, import_node_fs.mkdirSync)((0, import_node_path.dirname)(logFile), { recursive: true });
  const fd = (0, import_node_fs.openSync)(logFile, "a");
  const child = (0, import_node_child_process.spawn)(process.execPath, [process.argv[1], "__daemon", ...daemonCanonicalArgs(c, "run")], {
    detached: true,
    stdio: ["ignore", fd, fd]
  });
  (0, import_node_fs.closeSync)(fd);
  child.unref();
  (0, import_node_fs.writeFileSync)(pidFile, `${child.pid}
`, "utf-8");
  console.log(`wid-typescript start: started pid=${child.pid} log=${logFile}`);
  return 0;
}
function runServiceLoop(c, action) {
  const { stateMode, transport: rawTransport } = parseStateAndTransport(c);
  let transport = rawTransport === "auto" ? "mqtt" : rawTransport;
  if (["saf-wid", "wir", "wism", "wihp", "wipr", "duplex"].includes(action) && !LOCAL_SERVICE_TRANSPORTS.has(transport)) {
    throw new Error(`invalid transport for A=${action}: ${transport}`);
  }
  const dir = dataDir(c);
  (0, import_node_fs.mkdirSync)(dir, { recursive: true });
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
            data_dir: dir
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
            data_dir: dir
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
            state_mode: stateMode
          })
        );
      }
    }
    if (i < max && c.L > 0) sleepSeconds(c.L);
  }
  return 0;
}
function runNativeOrchestration(c) {
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
function runCanonical(args) {
  const c = parseCanonical(args);
  if (c.A === "help-actions") {
    printActions();
    return 0;
  }
  const { stateMode } = parseStateAndTransport(c);
  const canonDataDir = dataDir(c);
  (0, import_node_fs.mkdirSync)(canonDataDir, { recursive: true });
  const genOptions = { W: c.W, Z: c.Z, timeUnit: c.T };
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
        console.log(gen.next());
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
      "--json"
    ]);
    return 0;
  }
  if (c.A === "sign") return runSign(c);
  if (c.A === "verify") return runVerify(c);
  if (c.A === "w-otp") return runWOtp(c);
  return runNativeOrchestration(c);
}
function runSelftest() {
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
function main() {
  const args = process.argv.slice(2);
  if (args.length === 0) {
    printHelp();
    return 2;
  }
  if (args[0] === "__daemon") {
    try {
      return runCanonical(args.slice(1));
    } catch (e) {
      console.error(`error: ${e.message}`);
      return 1;
    }
  }
  if (args.some((a) => a.includes("="))) {
    try {
      return runCanonical(args);
    } catch (e) {
      console.error(`error: ${e.message}`);
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
    console.error(`error: ${e.message}`);
    return 1;
  }
}
process.exit(main());
//# sourceMappingURL=cli.js.map