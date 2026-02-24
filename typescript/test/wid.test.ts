import { describe, it, expect } from 'vitest';
import { rmSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import {
  WidGen,
  validateWid,
  parseWid,
  asyncNextWid,
  asyncWidStream,
  MemoryWidStateStore,
  createNodeSqliteWidStateStore,
} from '../src/wid';

describe('validateWid', () => {
  it('accepts minimal WID (W=4, Z=0)', () => {
    expect(validateWid('20260212T091530.0000Z', 4, 0)).toBe(true);
    expect(validateWid('20260212T091530.0042Z', 4, 0)).toBe(true);
  });

  it('accepts WID with padding (W=4, Z=6)', () => {
    expect(validateWid('20260212T091530.0042Z-a3f91c', 4, 6)).toBe(true);
  });

  it('accepts ms WID when timeUnit=ms', () => {
    expect(validateWid('20260212T091530123.0042Z-a3f91c', 4, 6, 'ms')).toBe(true);
  });

  it('accepts WID with scope and padding', () => {
    expect(validateWid('20260212T091530.0042Z-acme-a3f91c', 4, 6)).toBe(true);
    expect(validateWid('20260212T091530.0042Z-acme-node01-7b2e4f', 4, 6)).toBe(true);
  });

  it('accepts WID with scope and no padding when Z>0', () => {
    expect(validateWid('20260212T091530.0042Z-acme', 4, 6)).toBe(true);
  });

  it('accepts scoped suffix when Z=0', () => {
    expect(validateWid('20260212T091530.0042Z-acme', 4, 0)).toBe(true);
  });

  it('rejects non-WID strings', () => {
    expect(validateWid('waldiez', 4, 6)).toBe(false);
  });

  it('rejects missing Z suffix', () => {
    expect(validateWid('20260212T091530.0000', 4, 0)).toBe(false);
  });

  it('rejects lowercase z', () => {
    expect(validateWid('20260212T091530.0000z', 4, 0)).toBe(false);
  });

  it('rejects extended ISO format', () => {
    expect(validateWid('2026-02-12T09:15:30.0000Z', 4, 0)).toBe(false);
  });

  it('rejects invalid month', () => {
    expect(validateWid('20261312T091530.0000Z', 4, 0)).toBe(false);
  });

  it('rejects invalid day', () => {
    expect(validateWid('20260232T091530.0000Z', 4, 0)).toBe(false);
  });

  it('rejects invalid hour', () => {
    expect(validateWid('20260212T251530.0000Z', 4, 0)).toBe(false);
  });

  it('rejects uppercase hex padding', () => {
    expect(validateWid('20260212T091530.0000Z-A3F91C', 4, 6)).toBe(false);
    expect(validateWid('20260212T091530.0000Z-acme-A3F91C', 4, 6)).toBe(false);
  });

  it('rejects UUID format', () => {
    expect(validateWid('550e8400-e29b-41d4-a716-446655440000', 4, 6)).toBe(false);
  });
});

describe('parseWid', () => {
  it('parses minimal WID', () => {
    const parsed = parseWid('20260212T091530.0042Z', 4, 0);
    expect(parsed).not.toBeNull();
    expect(parsed!.sequence).toBe(42);
    expect(parsed!.scope).toBeNull();
    expect(parsed!.padding).toBeNull();
    expect(parsed!.timestamp.getUTCFullYear()).toBe(2026);
    expect(parsed!.timestamp.getUTCMonth()).toBe(1); // February = 1
    expect(parsed!.timestamp.getUTCDate()).toBe(12);
  });

  it('parses WID with scope and padding', () => {
    const parsed = parseWid('20260212T091530.0042Z-acme-a3f91c', 4, 6);
    expect(parsed).not.toBeNull();
    expect(parsed!.sequence).toBe(42);
    expect(parsed!.scope).toBe('acme');
    expect(parsed!.padding).toBe('a3f91c');
  });

  it('parses WID with hierarchical scope', () => {
    const parsed = parseWid('20260212T091530.0042Z-acme-node01-7b2e4f', 4, 6);
    expect(parsed).not.toBeNull();
    expect(parsed!.scope).toBe('acme-node01');
    expect(parsed!.padding).toBe('7b2e4f');
  });

  it('parses ms WID', () => {
    const parsed = parseWid('20260212T091530123.0042Z-a3f91c', 4, 6, 'ms');
    expect(parsed).not.toBeNull();
    expect(parsed!.timestamp.getUTCMilliseconds()).toBe(123);
  });

  it('returns null for invalid WID', () => {
    expect(parseWid('waldiez', 4, 6)).toBeNull();
    expect(parseWid('20260212T091530.0000', 4, 0)).toBeNull();
    expect(parseWid('20260212T091530.0000Z-invalid@scope', 4, 6)).toBeNull();
    expect(parseWid('20260212T091530.0000Z-acme-A3F91C', 4, 6)).toBeNull();
    expect(parseWid('20260212T091530.0000Z', 0, 6)).toBeNull();
    expect(parseWid('20260212T091530.0000Z', 4, -1)).toBeNull();
  });
});

describe('WidGen', () => {
  it('generates valid WIDs', () => {
    const gen = new WidGen({ W: 4, Z: 6 });
    const wid = gen.next();
    expect(validateWid(wid, 4, 6)).toBe(true);
  });

  it('generates monotonically increasing WIDs', () => {
    const gen = new WidGen({ W: 4, Z: 0 });
    const wid1 = gen.next();
    const wid2 = gen.next();
    const wid3 = gen.next();
    expect(wid1 < wid2).toBe(true);
    expect(wid2 < wid3).toBe(true);
  });

  it('includes scope when provided', () => {
    const gen = new WidGen({ W: 4, Z: 6, scope: 'acme-node01' });
    const wid = gen.next();
    expect(wid).toContain('-acme-node01-');
  });

  it('generates unique padding', () => {
    const gen = new WidGen({ W: 4, Z: 6 });
    const wids = gen.nextN(10);
    const paddings = wids.map(w => {
      const parsed = parseWid(w, 4, 6);
      return parsed?.padding;
    });
    const uniquePaddings = new Set(paddings);
    expect(uniquePaddings.size).toBe(10);
  });

  it('throws on invalid W', () => {
    expect(() => new WidGen({ W: 0 })).toThrow();
    expect(() => new WidGen({ W: -1 })).toThrow();
  });

  it('throws on invalid Z', () => {
    expect(() => new WidGen({ Z: -1 })).toThrow();
  });

  it('throws on invalid scope', () => {
    expect(() => new WidGen({ scope: 'invalid scope' })).toThrow();
    expect(() => new WidGen({ scope: 'invalid@scope' })).toThrow();
  });

  it('allows restoring state', () => {
    const gen1 = new WidGen({ W: 4, Z: 0 });
    gen1.next();
    gen1.next();
    const state = gen1.state;

    const gen2 = new WidGen({ W: 4, Z: 0 });
    gen2.restoreState(state.lastSec, state.lastSeq);

    // Next WID from gen2 should continue from gen1's state
    const wid = gen2.next();
    const parsed = parseWid(wid, 4, 0);
    expect(parsed!.sequence).toBe(state.lastSeq + 1);
  });

  it('rolls over sequence when max reached', () => {
    const gen = new WidGen({ W: 1, Z: 0 }); // max sequence = 9
    gen.restoreState(100, 9);
    const wid = gen.next();
    const parsed = parseWid(wid, 1, 0);
    expect(parsed).not.toBeNull();
    expect(parsed!.sequence).toBe(0);
  });

  it('persists and restores state using memory store', () => {
    const store = new MemoryWidStateStore();
    const gen1 = new WidGen({
      W: 4,
      Z: 0,
      stateStore: store,
      stateKey: 'test-state',
      autoPersist: true,
    });
    gen1.next();
    const snapshot = gen1.state;

    const gen2 = new WidGen({
      W: 4,
      Z: 0,
      stateStore: store,
      stateKey: 'test-state',
      autoPersist: true,
    });
    const state2 = gen2.state;
    expect(state2.lastSec).toBe(snapshot.lastSec);
    expect(state2.lastSeq).toBe(snapshot.lastSeq);
  });

  it('persists and restores state using sqlite store', () => {
    const dbPath = join(tmpdir(), `wid-state-${Date.now()}-${Math.random().toString(16).slice(2)}.sqlite`);
    let store: ReturnType<typeof createNodeSqliteWidStateStore> | null = null;
    try {
      store = createNodeSqliteWidStateStore(dbPath, 'wid-test');
    } catch {
      return;
    }

    const gen1 = new WidGen({
      W: 4,
      Z: 0,
      stateStore: store,
      stateKey: 'test-state',
      autoPersist: true,
    });
    gen1.next();
    const snapshot = gen1.state;

    const gen2 = new WidGen({
      W: 4,
      Z: 0,
      stateStore: store,
      stateKey: 'test-state',
      autoPersist: true,
    });
    const state2 = gen2.state;
    expect(state2.lastSec).toBe(snapshot.lastSec);
    expect(state2.lastSeq).toBe(snapshot.lastSeq);
    rmSync(dbPath, { force: true });
  });
});

describe('async API', () => {
  it('asyncNextWid returns a valid wid', async () => {
    const wid = await asyncNextWid({ W: 4, Z: 6 });
    expect(validateWid(wid, 4, 6)).toBe(true);
  });

  it('asyncNextWid supports ms', async () => {
    const wid = await asyncNextWid({ W: 4, Z: 0, timeUnit: 'ms' });
    expect(validateWid(wid, 4, 0, 'ms')).toBe(true);
  });

  it('asyncWidStream emits count values in order', async () => {
    const values: string[] = [];
    for await (const wid of asyncWidStream({ W: 4, Z: 0, count: 3 })) {
      values.push(wid);
    }
    expect(values.length).toBe(3);
    expect(values[0] < values[1]).toBe(true);
    expect(values[1] < values[2]).toBe(true);
  });

  it('asyncWidStream validates options', async () => {
    await expect(async () => {
      for await (const _wid of asyncWidStream({ count: -1 })) {
        // no-op
      }
    }).rejects.toThrow();
    await expect(async () => {
      for await (const _wid of asyncWidStream({ count: 1, intervalMs: -1 })) {
        // no-op
      }
    }).rejects.toThrow();
  });
});
