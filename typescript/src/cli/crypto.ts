import { existsSync, readFileSync, writeFileSync } from "node:fs";
import {
  createHmac,
  createPrivateKey,
  createPublicKey,
  sign as cryptoSign,
  timingSafeEqual,
  verify as cryptoVerify,
} from "node:crypto";
import { WidGen } from "../index";
import { type Canon, UsageError } from "./types";

export function b64urlEncode(buf: Buffer): string {
  return buf
    .toString("base64")
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/g, "");
}

export function b64urlDecode(s: string): Buffer {
  let std = s.replace(/-/g, "+").replace(/_/g, "/");
  const m = std.length % 4;
  if (m === 2) {
    std += "==";
  } else if (m === 3) {
    std += "=";
  } else if (m === 1) {
    throw new Error("invalid base64url signature length");
  }
  return Buffer.from(std, "base64");
}

export function buildSignVerifyMessage(c: Canon): Buffer {
  const wid = c.WID ?? "";
  if (!wid) {
    throw new UsageError("WID=<wid_string> required");
  }
  const widBuf = Buffer.from(wid, "utf8");
  const header = Buffer.from(`wid-sig-v1:${widBuf.length}:`, "ascii");
  const parts: Buffer[] = [header, widBuf];
  if (c.DATA && c.DATA.length > 0) {
    if (!existsSync(c.DATA)) {
      throw new Error(`data file not found: ${c.DATA}`);
    }
    parts.push(readFileSync(c.DATA));
  }
  return Buffer.concat(parts);
}

export function runSign(c: Canon): number {
  const keyPath = c.KEY ?? "";
  if (!keyPath) {
    throw new UsageError("KEY=<private_key_path> required for A=sign");
  }
  if (!existsSync(keyPath)) {
    throw new Error(`private key file not found: ${keyPath}`);
  }
  const message = buildSignVerifyMessage(c);
  const key = createPrivateKey(readFileSync(keyPath));
  const sig = cryptoSign(null, message, key);
  const out = b64urlEncode(sig);
  if (c.OUT && c.OUT.length > 0) {
    writeFileSync(c.OUT, out, "utf8");
  } else {
    console.log(out);
  }
  return 0;
}

export function runVerify(c: Canon): number {
  const keyPath = c.KEY ?? "";
  const sigText = c.SIG ?? "";
  if (!keyPath) {
    throw new UsageError("KEY=<public_key_path> required for A=verify");
  }
  if (!sigText) {
    throw new UsageError("SIG=<signature_string> required for A=verify");
  }
  if (!existsSync(keyPath)) {
    throw new Error(`public key file not found: ${keyPath}`);
  }
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

export function resolveWOtpSecret(raw: string): string {
  if (existsSync(raw)) {
    return readFileSync(raw, "utf8").trim();
  }
  return raw.trim();
}

export function computeWOtp(
  secret: string,
  wid: string,
  digits: number
): string {
  const digest = createHmac("sha256", Buffer.from(secret, "utf8"))
    .update(Buffer.from(wid, "utf8"))
    .digest();
  const binary = digest.readUInt32BE(0);
  const mod = 10 ** digits;
  return String(binary % mod).padStart(digits, "0");
}

function parseWotpDateParts(date: string, time: string) {
  const [y, mo, d] = [
    date.slice(0, 4),
    date.slice(4, 6),
    date.slice(6, 8),
  ].map(Number);
  const [hh, mm, ss] = [
    time.slice(0, 2),
    time.slice(2, 4),
    time.slice(4, 6),
  ].map(Number);
  const ms = time.length === 9 ? Number(time.slice(6, 9)) : 0;
  return { y, mo, d, hh, mm, ss, ms };
}

function validateWidDt(wid: string, invalid: string) {
  const ts = wid.split(".", 1)[0];
  if (!ts) {
    throw new Error(invalid);
  }
  const tIdx = ts.indexOf("T");
  if (tIdx < 0) {
    throw new Error(invalid);
  }
  const date = ts.slice(0, tIdx);
  const time = ts.slice(tIdx + 1);
  if (date.length !== 8 || (time.length !== 6 && time.length !== 9)) {
    throw new Error(invalid);
  }
  if (!/^[0-9]+$/.test(date) || !/^[0-9]+$/.test(time)) {
    throw new Error(invalid);
  }
  return { date, time };
}

export function wotpWidTickMs(wid: string): number {
  const invalid = "WID timestamp is invalid for time-window verification";

  const { date, time } = validateWidDt(wid, invalid);

  const { y, mo, d, hh, mm, ss, ms } = parseWotpDateParts(date, time);
  if (y === undefined || mo === undefined || hh === undefined || isNaN(y) || isNaN(mo) || isNaN(hh)) {
   throw new Error(invalid);
  }
  const dt = new Date(0);
  dt.setUTCFullYear(y, mo - 1, d);
  dt.setUTCHours(hh, mm, ss, ms);
  const tick = dt.getTime();
  if (!Number.isFinite(tick)) {
    throw new Error(invalid);
  }
  return tick;
}

export function runWOtp(c: Canon): number {
  const mode = (c.MODE ?? "gen").toLowerCase();
  if (mode !== "gen" && mode !== "verify") {
    throw new UsageError("MODE must be gen or verify for A=w-otp");
  }
  if (!c.KEY || c.KEY.length === 0) {
    throw new UsageError("KEY=<secret_or_path> required for A=w-otp");
  }
  const secret = resolveWOtpSecret(c.KEY);
  if (!secret) {
    throw new UsageError("w-otp secret cannot be empty");
  }
  const digits = c.DIGITS ?? 6;
  if (!Number.isInteger(digits) || digits < 4 || digits > 10) {
    throw new UsageError("DIGITS must be an integer between 4 and 10");
  }

  if (mode === "gen") {
    return runWOtpGen(c, secret, digits);
  } else {
    return runWOtpVerify(c, secret, digits);
  }
}

function runWOtpGen(c: Canon, secret: string, digits: number): number {
  let wid = c.WID ?? "";
  if (!wid) {
    wid = new WidGen({ W: c.W, Z: c.Z, timeUnit: c.T }).next();
  }
  const otp = computeWOtp(secret, wid, digits);
  console.log(JSON.stringify({ wid, otp, digits }));
  return 0;
}

function validateWotpVerifyParams(
  c: Canon,
  wid: string,
  code: string
): { maxAgeSec: number; maxFutureSec: number } {
  if (!wid) {
    throw new UsageError("WID=<wid_string> required for A=w-otp MODE=verify");
  }
  const maxAgeSec = c.MAX_AGE_SEC ?? 0;
  const maxFutureSec = c.MAX_FUTURE_SEC ?? 5;
  if (!Number.isInteger(maxAgeSec) || maxAgeSec < 0) {
    throw new UsageError("MAX_AGE_SEC must be a non-negative integer");
  }
  if (!Number.isInteger(maxFutureSec) || maxFutureSec < 0) {
    throw new UsageError("MAX_FUTURE_SEC must be a non-negative integer");
  }
  if (!code) {
    throw new UsageError("CODE=<otp_code> required for A=w-otp MODE=verify");
  }
  return { maxAgeSec, maxFutureSec };
}

function verifyWotpTimeWindow(
  wid: string,
  maxAgeSec: number,
  maxFutureSec: number
): void {
  if (maxAgeSec > 0 || maxFutureSec > 0) {
    const widMs = wotpWidTickMs(wid);
    const delta = Date.now() - widMs;
    if (delta < 0 && -delta > maxFutureSec * 1000) {
      throw new Error("OTP invalid: WID timestamp is too far in the future");
    }
    if (delta >= 0 && maxAgeSec > 0 && delta > maxAgeSec * 1000) {
      throw new Error("OTP invalid: WID timestamp is too old");
    }
  }
}

function runWOtpVerify(c: Canon, secret: string, digits: number): number {
  const wid = c.WID ?? "";
  const code = c.CODE ?? "";
  const { maxAgeSec, maxFutureSec } = validateWotpVerifyParams(c, wid, code);

  const otp = computeWOtp(secret, wid, digits);
  verifyWotpTimeWindow(wid, maxAgeSec, maxFutureSec);

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
