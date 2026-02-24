import { describe, it, expect } from 'vitest';
import { Manifest, SynapseFile, MANIFEST_MAGIC, MANIFEST_VERSION, DataType } from '../src/manifest';

describe('Manifest', () => {
  it('creates with required fields', () => {
    const manifest = new Manifest({ id: 'test-id' });
    expect(manifest.id).toBe('test-id');
    expect(manifest.version).toBe(MANIFEST_VERSION);
    expect(manifest.data_type).toBe(DataType.Unknown);
  });

  it('serializes to JSON', () => {
    const manifest = new Manifest({
      id: 'test-id',
      node: 'test-node',
      data_type: DataType.Text,
    });
    const json = manifest.toJson();
    expect(json).toContain('"id": "test-id"');
    expect(json).toContain('"node": "test-node"');
  });

  it('deserializes from JSON', () => {
    const json = JSON.stringify({
      id: 'test-id',
      node: 'test-node',
      data_type: 'text/plain',
    });
    const manifest = Manifest.fromJson(json);
    expect(manifest.id).toBe('test-id');
    expect(manifest.node).toBe('test-node');
    expect(manifest.data_type).toBe('text/plain');
  });

  it('round-trips through bytes', () => {
    const original = new Manifest({
      id: 'test-id',
      node: 'test-node',
      metadata: { key: 'value' },
    });
    const bytes = original.toBytes();
    const restored = Manifest.fromBytes(bytes);
    expect(restored.id).toBe(original.id);
    expect(restored.node).toBe(original.node);
    expect(restored.metadata).toEqual(original.metadata);
  });
});

describe('SynapseFile', () => {
  it('creates with manifest and payload', () => {
    const manifest = new Manifest({ id: 'test-id' });
    const payload = new TextEncoder().encode('Hello, SYNAPSE!');
    const sf = new SynapseFile(manifest, payload);
    expect(sf.manifest.id).toBe('test-id');
    expect(new TextDecoder().decode(sf.payload)).toBe('Hello, SYNAPSE!');
  });

  it('serializes to bytes with magic header', async () => {
    const manifest = new Manifest({ id: 'test-id' });
    const payload = new TextEncoder().encode('test payload');
    const sf = new SynapseFile(manifest, payload);
    const bytes = await sf.toBytes();

    // Check magic
    expect(bytes.subarray(0, 4)).toEqual(MANIFEST_MAGIC);
    // Check version
    const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    expect(view.getUint16(4, false)).toBe(MANIFEST_VERSION);
  });

  it('updates data_size and data_hash on serialize', async () => {
    const manifest = new Manifest({ id: 'test-id' });
    const payload = new TextEncoder().encode('test payload');
    const sf = new SynapseFile(manifest, payload);
    await sf.toBytes();

    expect(sf.manifest.data_size).toBe(payload.length);
    expect(sf.manifest.data_hash).toHaveLength(64); // SHA256 hex
  });

  it('round-trips through bytes', async () => {
    const manifest = new Manifest({
      id: 'test-id',
      node: 'test-node',
    });
    const payload = new TextEncoder().encode('Hello, SYNAPSE!');
    const sf = new SynapseFile(manifest, payload);

    const bytes = await sf.toBytes();
    const restored = SynapseFile.fromBytes(bytes);

    expect(restored.manifest.id).toBe('test-id');
    expect(restored.manifest.node).toBe('test-node');
    expect(new TextDecoder().decode(restored.payload)).toBe('Hello, SYNAPSE!');
  });

  it('verifies payload hash', async () => {
    const manifest = new Manifest({ id: 'test-id' });
    const payload = new TextEncoder().encode('test payload');
    const sf = new SynapseFile(manifest, payload);
    await sf.toBytes(); // This updates the hash

    await expect(sf.verify()).resolves.toBe(true);
  });

  it('fails verification with corrupted payload', async () => {
    const manifest = new Manifest({ id: 'test-id' });
    const payload = new TextEncoder().encode('test payload');
    const sf = new SynapseFile(manifest, payload);
    await sf.toBytes();

    // Corrupt the payload
    sf.payload = new TextEncoder().encode('corrupted');
    await expect(sf.verify()).resolves.toBe(false);
  });

  it('throws on invalid magic', () => {
    const invalidData = new TextEncoder().encode('XXXX' + '\x00'.repeat(100));
    expect(() => SynapseFile.fromBytes(invalidData)).toThrow('Invalid magic');
  });

  it('throws on data too small', () => {
    const tooSmall = new TextEncoder().encode('SYN');
    expect(() => SynapseFile.fromBytes(tooSmall)).toThrow('too small');
  });

  it('throws on oversized serialized manifest in toBytes', async () => {
    const manifest = new Manifest({
      id: 'big',
      metadata: { huge: 'x'.repeat(70_000) },
    });
    const sf = new SynapseFile(manifest, new TextEncoder().encode('payload'));
    await expect(sf.toBytes()).rejects.toThrow('Manifest too large');
  });

  it('throws on oversized declared manifest in fromBytes header', () => {
    const header = new Uint8Array(10);
    header.set(MANIFEST_MAGIC, 0);
    const view = new DataView(header.buffer, header.byteOffset, header.byteLength);
    view.setUint16(4, MANIFEST_VERSION, false);
    view.setUint32(6, 70_000, false);
    expect(() => SynapseFile.fromBytes(header)).toThrow('Manifest too large');
  });
});
