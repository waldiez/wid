/**
 * SYNAPSE Manifest-Based Binary Files.
 */

/** Fixed header bytes used by SYNAPSE files. */
export const MANIFEST_MAGIC = new Uint8Array([0x53, 0x59, 0x4e, 0x4d]); // SYNM
/** Current manifest version published in all files. */
export const MANIFEST_VERSION = 1;
/** Maximum allowed manifest payload size in bytes. */
export const MAX_MANIFEST_SIZE = 64 * 1024;
/** Length of the SYNAPSE file header (magic + version + length). */
const HEADER_SIZE = 10;

/** Supported data media types stored inside a manifest. */
export enum DataType {
  Unknown = 'unknown',
  Text = 'text/plain',
  Json = 'application/json',
  Binary = 'application/octet-stream',
}

/** Shape of a manifest when decoding/encoding JSON representations. */
export interface ManifestData {
  id: string;
  version?: number;
  node?: string;
  data_type?: string;
  data_size?: number;
  data_hash?: string;
  metadata?: Record<string, unknown>;
}

function concatBytes(parts: Uint8Array[]): Uint8Array {
  const total = parts.reduce((acc, p) => acc + p.length, 0);
  const out = new Uint8Array(total);
  let offset = 0;
  for (const p of parts) {
    out.set(p, offset);
    offset += p.length;
  }
  return out;
}

function equalBytes(a: Uint8Array, b: Uint8Array): boolean {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i += 1) {
    if (a[i] !== b[i]) return false;
  }
  return true;
}

function toHex(bytes: Uint8Array): string {
  return Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('');
}

async function sha256Hex(data: Uint8Array): Promise<string> {
  if (!globalThis.crypto?.subtle) {
    throw new Error('Web Crypto API (crypto.subtle) is unavailable in this runtime');
  }
  // @ts-expect-error sth with Uint8Array
  const digest = await globalThis.crypto.subtle.digest('SHA-256', data);
  return toHex(new Uint8Array(digest));
}

function utf8Encode(s: string): Uint8Array {
  return new TextEncoder().encode(s);
}

function utf8Decode(bytes: Uint8Array): string {
  return new TextDecoder().decode(bytes);
}

/** Lightweight wrapper around manifest metadata with serialization helpers. */
export class Manifest {
  id: string;
  version: number;
  node: string;
  data_type: string;
  data_size: number;
  data_hash: string;
  metadata: Record<string, unknown>;

  constructor(data: ManifestData) {
    this.id = data.id;
    this.version = data.version ?? MANIFEST_VERSION;
    this.node = data.node ?? '';
    this.data_type = data.data_type ?? DataType.Unknown;
    this.data_size = data.data_size ?? 0;
    this.data_hash = data.data_hash ?? '';
    this.metadata = data.metadata ?? {};
  }

  toJson(): string {
    return JSON.stringify(this, null, 2);
  }

  toBytes(): Uint8Array {
    return utf8Encode(this.toJson());
  }

  static fromJson(data: string): Manifest {
    return new Manifest(JSON.parse(data));
  }

  static fromBytes(data: Uint8Array): Manifest {
    return Manifest.fromJson(utf8Decode(data));
  }
}

/** Composite object combining a manifest with its binary payload. */
export class SynapseFile {
  manifest: Manifest;
  payload: Uint8Array;

  constructor(manifest: Manifest, payload: Uint8Array = new Uint8Array(0)) {
    this.manifest = manifest;
    this.payload = payload;
  }

  async toBytes(): Promise<Uint8Array> {
    this.manifest.data_size = this.payload.length;
    this.manifest.data_hash = await sha256Hex(this.payload);

    const manifestBytes = this.manifest.toBytes();
    if (manifestBytes.length > MAX_MANIFEST_SIZE) {
      throw new Error(`Manifest too large: ${manifestBytes.length} bytes`);
    }

    const header = new Uint8Array(HEADER_SIZE);
    header.set(MANIFEST_MAGIC, 0);
    const view = new DataView(header.buffer, header.byteOffset, header.byteLength);
    view.setUint16(4, MANIFEST_VERSION, false);
    view.setUint32(6, manifestBytes.length, false);

    return concatBytes([header, manifestBytes, this.payload]);
  }

  static fromBytes(data: Uint8Array): SynapseFile {
    if (data.length < HEADER_SIZE) {
      throw new Error('Data too small for SYNAPSE file');
    }

    const magic = data.subarray(0, 4);
    if (!equalBytes(magic, MANIFEST_MAGIC)) {
      throw new Error(`Invalid magic: ${utf8Decode(magic)}`);
    }

    const view = new DataView(data.buffer, data.byteOffset, data.byteLength);
    const manifestSize = view.getUint32(6, false);
    if (manifestSize > MAX_MANIFEST_SIZE) {
      throw new Error(`Manifest too large: ${manifestSize} bytes`);
    }

    const manifestEnd = HEADER_SIZE + manifestSize;
    const manifestBytes = data.subarray(HEADER_SIZE, manifestEnd);
    const manifest = Manifest.fromBytes(manifestBytes);
    const payload = data.subarray(manifestEnd);

    return new SynapseFile(manifest, payload);
  }

  async verify(): Promise<boolean> {
    const actualHash = await sha256Hex(this.payload);
    return actualHash === this.manifest.data_hash;
  }
}
