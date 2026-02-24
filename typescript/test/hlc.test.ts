import { describe, it, expect } from 'vitest';
import {
  HLCWidGen,
  asyncHlcWidStream,
  asyncNextHlcWid,
  parseHlcWid,
  validateHlcWid,
} from '../src/hlc';

describe('validateHlcWid', () => {
  it('accepts valid HLC-WID', () => {
    expect(validateHlcWid('20260212T091530.0000Z-node01', 4, 0)).toBe(true);
    expect(validateHlcWid('20260212T091530.0042Z-node01-a3f91c', 4, 6)).toBe(true);
    expect(validateHlcWid('20260212T091530123.0042Z-node01-a3f91c', 4, 6, 'ms')).toBe(true);
  });

  it('rejects invalid HLC-WID', () => {
    expect(validateHlcWid('20260212T091530.0000Z', 4, 0)).toBe(false);
    expect(validateHlcWid('20260212T091530.0000Z-node-01', 4, 0)).toBe(false);
    expect(validateHlcWid('20260212T091530.0000Z-node01-A3F91C', 4, 6)).toBe(false);
  });
});

describe('parseHlcWid', () => {
  it('parses HLC-WID with padding', () => {
    const parsed = parseHlcWid('20260212T091530.0042Z-node01-a3f91c', 4, 6);
    expect(parsed).not.toBeNull();
    expect(parsed!.logicalCounter).toBe(42);
    expect(parsed!.node).toBe('node01');
    expect(parsed!.padding).toBe('a3f91c');
  });

  it('parses ms HLC-WID', () => {
    const parsed = parseHlcWid('20260212T091530123.0042Z-node01-a3f91c', 4, 6, 'ms');
    expect(parsed).not.toBeNull();
    expect(parsed!.timestamp.getUTCMilliseconds()).toBe(123);
  });
});

describe('HLCWidGen', () => {
  it('generates valid, monotonic HLC-WIDs', () => {
    const gen = new HLCWidGen({ node: 'node01', W: 4, Z: 0 });
    const a = gen.next();
    const b = gen.next();
    expect(validateHlcWid(a, 4, 0)).toBe(true);
    expect(validateHlcWid(b, 4, 0)).toBe(true);
    expect(a <= b).toBe(true);
  });

  it('supports ms generation', () => {
    const gen = new HLCWidGen({ node: 'node01', W: 4, Z: 0, timeUnit: 'ms' });
    const id = gen.next();
    expect(validateHlcWid(id, 4, 0, 'ms')).toBe(true);
  });
});

describe('async HLC API', () => {
  it('asyncNextHlcWid returns valid HLC-WID', async () => {
    const id = await asyncNextHlcWid({ node: 'node01', W: 4, Z: 0, timeUnit: 'ms' });
    expect(validateHlcWid(id, 4, 0, 'ms')).toBe(true);
  });

  it('asyncHlcWidStream emits count values', async () => {
    const values: string[] = [];
    for await (const id of asyncHlcWidStream({ node: 'node01', W: 4, Z: 0, count: 2 })) {
      values.push(id);
    }
    expect(values.length).toBe(2);
    expect(values[0] <= values[1]).toBe(true);
  });
});
