/** Supported time-precision units for WID/HLC generators. */
type TimeUnit = "sec" | "ms";
declare function parseTimeUnit(input: string): TimeUnit;

/**
 * WID (Waldiez/SYNAPSE Identifier) generation and validation.
 * Format: YYYYMMDDTHHMMSS[mmm].<seqW>Z[-<scope>][-<padZ>]
 */

/** Parsed WID components after a successful parse. */
interface ParsedWid {
    /** Raw identifier string that was parsed. */
    raw: string;
    /** UTC timestamp extracted from the WID envelope. */
    timestamp: Date;
    /** Sequential component embedded in the identifier. */
    sequence: number;
    /** Optional scope suffix if one was provided. */
    scope: string | null;
    /** Optional padding hex string when Z > 0. */
    padding: string | null;
}
/** In-memory snapshot of the last seen second/sequence for a generator. */
interface WidStateSnapshot {
    lastSec: number;
    lastSeq: number;
}
/** Storage contract consumed by `WidGen` when persistence is enabled. */
interface WidStateStore {
    load(key: string): WidStateSnapshot | null;
    save(key: string, state: WidStateSnapshot): void;
}
/** Basic in-memory store that keeps Wid state during runtime. */
declare class MemoryWidStateStore implements WidStateStore {
    private readonly memory;
    load(key: string): WidStateSnapshot | null;
    save(key: string, state: WidStateSnapshot): void;
}
/**
 * Creates a browser localStorage-backed state store.
 * In non-browser runtimes this behaves as a no-op store.
 */
/** Factory that wires the browser storage-backed Wid store for web runtimes. */
declare function createBrowserWidStateStore(prefix?: string): WidStateStore;
/** Node factory that requires the `node:sqlite` module for persistence. */
declare function createNodeSqliteWidStateStore(databasePath: string, prefix?: string): WidStateStore;
/** Configuration options accepted by `WidGen`. */
interface WidGenOptions {
    /** Width of the sequence segment (default 4). */
    W?: number;
    /** Padding length (default 6). */
    Z?: number;
    /** Optional scope suffix appended to generated IDs. */
    scope?: string;
    /** Time unit precision, either `sec` or `ms`. */
    timeUnit?: TimeUnit;
    /** Optional persistence layer for generator state. */
    stateStore?: WidStateStore;
    /** Key used when storing state. */
    stateKey?: string;
    /** Persist state after each generation when true. */
    autoPersist?: boolean;
}
/** Extended configuration for streaming helpers around `WidGen`. */
interface AsyncWidStreamOptions extends WidGenOptions {
    /** Number of IDs to emit (0 for infinite). */
    count?: number;
    /** Delay between emits in milliseconds. */
    intervalMs?: number;
}
declare function validateWid(wid: string, W?: number, Z?: number, timeUnit?: TimeUnit): boolean;
declare function parseWid(wid: string, W?: number, Z?: number, timeUnit?: TimeUnit): ParsedWid | null;
declare function asyncNextWid(options?: WidGenOptions): Promise<string>;
declare function asyncWidStream(options?: AsyncWidStreamOptions): AsyncGenerator<string>;
/** Stateful generator for WID IDs that keeps monotonicity guarantees. */
declare class WidGen {
    private readonly W;
    private readonly Z;
    private readonly scope;
    private readonly timeUnit;
    private readonly maxSeq;
    private readonly stateStore;
    private readonly stateKey;
    private readonly autoPersist;
    private lastSec;
    private lastSeq;
    private cachedSec;
    private cachedTs;
    /** Create a generator with optional persistence and precision control. */
    constructor(options?: WidGenOptions);
    private persistState;
    private tsForTick;
    private nowTick;
    next(): string;
    nextN(n: number): string[];
    get state(): WidStateSnapshot;
    restoreState(lastSec: number, lastSeq: number): void;
}

/**
 * HLC-WID (Hybrid Logical Clock WID) generation, validation, and parsing.
 * Format: YYYYMMDDTHHMMSS[mmm].<lcW>Z-<node>[-<padZ>]
 */

/** Parsed components of an HLC-WID after a successful parse. */
interface ParsedHlcWid {
    /** Raw HLC-WID string. */
    raw: string;
    /** UTC timestamp portion of the HLC-WID. */
    timestamp: Date;
    /** Logical clock counter embedded in the HLC-WID. */
    logicalCounter: number;
    /** Node identifier appended to the HLC-WID. */
    node: string;
    /** Optional padding when Z > 0. */
    padding: string | null;
}
/** Minimal Hybrid Logical Clock state snapshot. */
interface HLCState {
    /** Physical timestamp used by the generator. */
    pt: number;
    /** Logical counter component. */
    lc: number;
}
/** Configuration options for `HLCWidGen`. */
interface HLCWidGenOptions {
    /** Unique node identifier suffix. */
    node: string;
    /** Width of the logical counter (default 4). */
    W?: number;
    /** Optional padding length (default 0). */
    Z?: number;
    /** Time precision (defaults to `sec`). */
    timeUnit?: TimeUnit;
}
declare function validateHlcWid(wid: string, W?: number, Z?: number, timeUnit?: TimeUnit): boolean;
declare function parseHlcWid(wid: string, W?: number, Z?: number, timeUnit?: TimeUnit): ParsedHlcWid | null;
/** Generator for HLC-WIDs that keeps the logical counter monotonic. */
declare class HLCWidGen {
    private readonly W;
    private readonly Z;
    private readonly node;
    private readonly timeUnit;
    private readonly maxLC;
    private pt;
    private lc;
    private cachedTick;
    private cachedTs;
    constructor(options: HLCWidGenOptions);
    private nowTick;
    private tsForTick;
    private rollover;
    observe(remotePT: number, remoteLC: number): void;
    next(): string;
    nextN(n: number): string[];
    get state(): HLCState;
    restoreState(pt: number, lc: number): void;
}
declare function asyncNextHlcWid(options: HLCWidGenOptions): Promise<string>;
declare function asyncHlcWidStream(options: HLCWidGenOptions & {
    count?: number;
    intervalMs?: number;
}): AsyncGenerator<string>;

/**
 * SYNAPSE Manifest-Based Binary Files.
 */
/** Fixed header bytes used by SYNAPSE files. */
declare const MANIFEST_MAGIC: Uint8Array<ArrayBuffer>;
/** Current manifest version published in all files. */
declare const MANIFEST_VERSION = 1;
/** Supported data media types stored inside a manifest. */
declare enum DataType {
    Unknown = "unknown",
    Text = "text/plain",
    Json = "application/json",
    Binary = "application/octet-stream"
}
/** Shape of a manifest when decoding/encoding JSON representations. */
interface ManifestData {
    id: string;
    version?: number;
    node?: string;
    data_type?: string;
    data_size?: number;
    data_hash?: string;
    metadata?: Record<string, unknown>;
}
/** Lightweight wrapper around manifest metadata with serialization helpers. */
declare class Manifest {
    id: string;
    version: number;
    node: string;
    data_type: string;
    data_size: number;
    data_hash: string;
    metadata: Record<string, unknown>;
    constructor(data: ManifestData);
    toJson(): string;
    toBytes(): Uint8Array;
    static fromJson(data: string): Manifest;
    static fromBytes(data: Uint8Array): Manifest;
}
/** Composite object combining a manifest with its binary payload. */
declare class SynapseFile {
    manifest: Manifest;
    payload: Uint8Array;
    constructor(manifest: Manifest, payload?: Uint8Array);
    toBytes(): Promise<Uint8Array>;
    static fromBytes(data: Uint8Array): SynapseFile;
    verify(): Promise<boolean>;
}

export { type AsyncWidStreamOptions, DataType, type HLCState, HLCWidGen, type HLCWidGenOptions, MANIFEST_MAGIC, MANIFEST_VERSION, Manifest, MemoryWidStateStore, type ParsedHlcWid, type ParsedWid, SynapseFile, type TimeUnit, WidGen, type WidGenOptions, type WidStateSnapshot, type WidStateStore, asyncHlcWidStream, asyncNextHlcWid, asyncNextWid, asyncWidStream, createBrowserWidStateStore, createNodeSqliteWidStateStore, parseHlcWid, parseTimeUnit, parseWid, validateHlcWid, validateWid };
