/**
 * synapse-wid: WID (Waldiez/SYNAPSE Identifier) generation and validation.
 * @packageDocumentation
 */

/** Core generator exports (re-exported for convenience). */
export {
  WidGen,
  type WidGenOptions,
  asyncNextWid,
  asyncWidStream,
  type AsyncWidStreamOptions,
  type WidStateSnapshot,
  type WidStateStore,
  MemoryWidStateStore,
  createBrowserWidStateStore,
  createNodeSqliteWidStateStore,
} from './wid';
/** Convenience exports for parsing and validation. */
export { validateWid, parseWid, type ParsedWid } from './wid';

/** Time utilities re-exported for external callers. */
export { type TimeUnit, parseTimeUnit } from './time';

/** HLC helpers and types that mirror the WID surface. */
export {
  HLCWidGen,
  validateHlcWid,
  parseHlcWid,
  asyncNextHlcWid,
  asyncHlcWidStream,
  type ParsedHlcWid,
  type HLCState,
  type HLCWidGenOptions,
} from './hlc';

/** Manifest helpers surfaced to consumers. */
export { Manifest, SynapseFile, DataType } from './manifest';
/** Manifest constants re-exported for the public API. */
export { MANIFEST_MAGIC, MANIFEST_VERSION } from './manifest';
