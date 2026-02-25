/*
 * wid: WID + HLC-WID generation, parsing, and validation for C
 *
 * WID format:
 *   YYYYMMDDTHHMMSS[mmm].<seqW>Z[-<padZ>]
 *
 * HLC-WID format:
 *   YYYYMMDDTHHMMSS[mmm].<lcW>Z-<node>[-<padZ>]
 */

#ifndef WID_H
#define WID_H

/*
 * Single-header library.
 *
 * In ONE translation unit, define WID_IMPLEMENTATION before including:
 *   #define WID_IMPLEMENTATION
 *   #include "wid.h"
 *
 * All other translation units can include wid.h normally for declarations.
 * For single-TU projects (like this CLI), the static inline approach works
 * without defining WID_IMPLEMENTATION.
 */

#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

/*
 * Thread safety: wid_gen_t and hlc_wid_gen_t contain mutable state
 * (last_tick, last_seq, pt, lc) and are NOT thread-safe.
 * If used from multiple threads, callers must provide external
 * synchronization (e.g., a mutex) around calls to wid_gen_next(),
 * hlc_wid_gen_next(), and hlc_wid_observe().
 */

#define WID_MAX_LEN 256
#define WID_DEFAULT_W 4
#define WID_DEFAULT_Z 6
#define HLC_DEFAULT_NODE "c"
#define WID_MAX_W 18
#define WID_MAX_Z 64

typedef enum {
    WID_TIME_SEC = 0,
    WID_TIME_MS = 1
} wid_time_unit_t;

typedef struct {
    int W;
    int Z;
    wid_time_unit_t time_unit;
    int64_t last_tick;
    int64_t last_seq;
    int64_t max_seq;
} wid_gen_t;

typedef struct {
    int W;
    int Z;
    wid_time_unit_t time_unit;
    char node[64];
    int64_t pt;
    int64_t lc;
    int64_t max_lc;
} hlc_wid_gen_t;

typedef struct {
    const char *raw;
    int year;
    int month;
    int day;
    int hour;
    int minute;
    int second;
    int millisecond;
    int64_t sequence;
    bool has_padding;
    char padding[WID_MAX_Z + 1];
} parsed_wid_t;

typedef struct {
    const char *raw;
    int year;
    int month;
    int day;
    int hour;
    int minute;
    int second;
    int millisecond;
    int64_t logical_counter;
    char node[64];
    bool has_padding;
    char padding[WID_MAX_Z + 1];
} parsed_hlc_wid_t;

typedef struct {
    wid_gen_t gen;
    int remaining; /* -1 => infinite */
    int interval_ms;
    int64_t next_due_ns;
    bool initialized;
} wid_async_wid_stream_t;

typedef struct {
    hlc_wid_gen_t gen;
    int remaining; /* -1 => infinite */
    int interval_ms;
    int64_t next_due_ns;
    bool initialized;
} wid_async_hlc_stream_t;

static inline bool wid_is_digit(char c) {
    return c >= '0' && c <= '9';
}

static inline bool wid_is_alpha(char c) {
    return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z');
}

static inline bool wid_is_alnum(char c) {
    return wid_is_digit(c) || wid_is_alpha(c);
}

static inline bool wid_is_lower_hex(char c) {
    return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f');
}

static inline bool wid_is_leap_year(int year) {
    if (year % 400 == 0) return true;
    if (year % 100 == 0) return false;
    return (year % 4) == 0;
}

static inline bool wid_valid_ymdhms(
    int year,
    int month,
    int day,
    int hour,
    int minute,
    int second
) {
    static const int days_in_month[] = {31,28,31,30,31,30,31,31,30,31,30,31};

    (void)year;
    if (month < 1 || month > 12) return false;
    if (hour < 0 || hour > 23) return false;
    if (minute < 0 || minute > 59) return false;
    if (second < 0 || second > 59) return false;

    int dim = days_in_month[month - 1];
    if (month == 2 && wid_is_leap_year(year)) dim = 29;
    return day >= 1 && day <= dim;
}

static inline bool wid_is_node_char(char c) {
    return wid_is_alnum(c) || c == '_';
}

static inline bool wid_valid_node(const char *node) {
    if (!node || node[0] == '\0') return false;
    for (const char *p = node; *p; p++) {
        if (!wid_is_node_char(*p)) return false;
    }
    return true;
}

static inline bool wid_valid_suffix(const char *suffix, int Z) {
    if (!suffix || suffix[0] == '\0') return true;
    if (suffix[0] != '-') return false;
    if (Z <= 0) return false;

    const char *pad = suffix + 1;
    int n = (int)strlen(pad);
    if (n != Z) return false;
    for (int i = 0; i < n; i++) {
        if (!wid_is_lower_hex(pad[i])) return false;
    }
    return true;
}

static inline bool wid_time_unit_from_str(const char *s, wid_time_unit_t *out) {
    if (!s || !out) return false;
    if (strcmp(s, "sec") == 0) {
        *out = WID_TIME_SEC;
        return true;
    }
    if (strcmp(s, "ms") == 0) {
        *out = WID_TIME_MS;
        return true;
    }
    return false;
}

static inline const char *wid_time_unit_to_str(wid_time_unit_t u) {
    return u == WID_TIME_MS ? "ms" : "sec";
}

static inline int wid_timestamp_len(wid_time_unit_t unit) {
    return unit == WID_TIME_MS ? 18 : 15;
}

static inline int64_t wid_parse_digits_i64(const char *s, int n) {
    int64_t v = 0;
    for (int i = 0; i < n; i++) {
        if (!wid_is_digit(s[i])) return -1;
        v = (v * 10) + (int64_t)(s[i] - '0');
    }
    return v;
}

static inline bool wid_parse_timestamp(
    const char *s,
    wid_time_unit_t unit,
    int *year,
    int *month,
    int *day,
    int *hour,
    int *minute,
    int *second,
    int *millisecond
) {
    int ts_len = wid_timestamp_len(unit);
    if (!s) return false;

    if (s[8] != 'T') return false;
    for (int i = 0; i < 8; i++) if (!wid_is_digit(s[i])) return false;
    for (int i = 9; i < 15; i++) if (!wid_is_digit(s[i])) return false;

    int y = (int)wid_parse_digits_i64(s + 0, 4);
    int mo = (int)wid_parse_digits_i64(s + 4, 2);
    int d = (int)wid_parse_digits_i64(s + 6, 2);
    int h = (int)wid_parse_digits_i64(s + 9, 2);
    int mi = (int)wid_parse_digits_i64(s + 11, 2);
    int se = (int)wid_parse_digits_i64(s + 13, 2);
    if (!wid_valid_ymdhms(y, mo, d, h, mi, se)) return false;

    int ms = 0;
    if (unit == WID_TIME_MS) {
        for (int i = 15; i < 18; i++) if (!wid_is_digit(s[i])) return false;
        ms = (int)wid_parse_digits_i64(s + 15, 3);
        if (ms < 0 || ms > 999) return false;
    }

    if (s[ts_len] != '.') return false;

    if (year) *year = y;
    if (month) *month = mo;
    if (day) *day = d;
    if (hour) *hour = h;
    if (minute) *minute = mi;
    if (second) *second = se;
    if (millisecond) *millisecond = ms;
    return true;
}

static inline bool wid_validate_ex(const char *wid, int W, int Z, wid_time_unit_t unit) {
    if (!wid || W <= 0 || Z < 0) return false;
    if (W > WID_MAX_W || Z > WID_MAX_Z) return false;

    int ts_len = wid_timestamp_len(unit);
    int n = (int)strlen(wid);
    int base_len = ts_len + 1 + W + 1; /* ts + . + seq + Z */
    if (n < base_len) return false;

    if (!wid_parse_timestamp(wid, unit, NULL, NULL, NULL, NULL, NULL, NULL, NULL)) return false;
    if (wid[ts_len + 1 + W] != 'Z') return false;

    for (int i = ts_len + 1; i < ts_len + 1 + W; i++) {
        if (!wid_is_digit(wid[i])) return false;
    }

    const char *suffix = wid + base_len;
    return wid_valid_suffix(suffix, Z);
}

static inline bool hlc_wid_validate_ex(const char *wid, int W, int Z, wid_time_unit_t unit) {
    if (!wid || W <= 0 || Z < 0) return false;
    if (W > WID_MAX_W || Z > WID_MAX_Z) return false;

    int ts_len = wid_timestamp_len(unit);
    int n = (int)strlen(wid);
    int prefix_len = ts_len + 1 + W + 1; /* ts + . + lc + Z */
    if (n < prefix_len + 2) return false;

    if (!wid_parse_timestamp(wid, unit, NULL, NULL, NULL, NULL, NULL, NULL, NULL)) return false;
    if (wid[ts_len + 1 + W] != 'Z') return false;
    if (wid[ts_len + 1 + W + 1] != '-') return false;

    for (int i = ts_len + 1; i < ts_len + 1 + W; i++) {
        if (!wid_is_digit(wid[i])) return false;
    }

    const char *node_start = wid + (prefix_len + 1);
    const char *suffix_dash = NULL;
    for (const char *p = node_start; *p; p++) {
        if (*p == '-') {
            suffix_dash = p;
            break;
        }
        if (!wid_is_node_char(*p)) return false;
    }

    int node_len = suffix_dash ? (int)(suffix_dash - node_start) : (int)strlen(node_start);
    if (node_len <= 0) return false;

    if (!suffix_dash) return true;
    return wid_valid_suffix(suffix_dash, Z);
}

static inline bool wid_validate(const char *wid, int W, int Z) {
    return wid_validate_ex(wid, W, Z, WID_TIME_SEC);
}

static inline bool hlc_wid_validate(const char *wid, int W, int Z) {
    return hlc_wid_validate_ex(wid, W, Z, WID_TIME_SEC);
}

static inline bool wid_parse_ex(
    const char *wid,
    int W,
    int Z,
    wid_time_unit_t unit,
    parsed_wid_t *out
) {
    if (!out) return false;
    memset(out, 0, sizeof(*out));

    if (!wid_validate_ex(wid, W, Z, unit)) return false;

    int ts_len = wid_timestamp_len(unit);
    int base_len = ts_len + 1 + W + 1;

    if (!wid_parse_timestamp(
        wid,
        unit,
        &out->year,
        &out->month,
        &out->day,
        &out->hour,
        &out->minute,
        &out->second,
        &out->millisecond
    )) {
        return false;
    }

    out->sequence = wid_parse_digits_i64(wid + ts_len + 1, W);
    if (out->sequence < 0) return false;

    const char *suffix = wid + base_len;
    out->raw = wid;
    out->has_padding = false;
    out->padding[0] = '\0';

    if (suffix[0] != '\0') {
        size_t pad_len = strlen(suffix + 1);
        if (pad_len > WID_MAX_Z) return false;
        memcpy(out->padding, suffix + 1, pad_len);
        out->padding[pad_len] = '\0';
        out->has_padding = true;
    }

    return true;
}

static inline bool hlc_wid_parse_ex(
    const char *wid,
    int W,
    int Z,
    wid_time_unit_t unit,
    parsed_hlc_wid_t *out
) {
    if (!out) return false;
    memset(out, 0, sizeof(*out));

    if (!hlc_wid_validate_ex(wid, W, Z, unit)) return false;

    int ts_len = wid_timestamp_len(unit);
    int prefix_len = ts_len + 1 + W + 1;

    if (!wid_parse_timestamp(
        wid,
        unit,
        &out->year,
        &out->month,
        &out->day,
        &out->hour,
        &out->minute,
        &out->second,
        &out->millisecond
    )) {
        return false;
    }

    out->logical_counter = wid_parse_digits_i64(wid + ts_len + 1, W);
    if (out->logical_counter < 0) return false;

    const char *node_start = wid + (prefix_len + 1);
    const char *suffix_dash = strchr(node_start, '-');
    size_t node_len = suffix_dash ? (size_t)(suffix_dash - node_start) : strlen(node_start);

    if (node_len == 0 || node_len >= sizeof(out->node)) return false;
    memcpy(out->node, node_start, node_len);
    out->node[node_len] = '\0';

    out->raw = wid;
    out->has_padding = false;
    out->padding[0] = '\0';

    if (suffix_dash) {
        size_t pad_len = strlen(suffix_dash + 1);
        if (pad_len > WID_MAX_Z) return false;
        memcpy(out->padding, suffix_dash + 1, pad_len);
        out->padding[pad_len] = '\0';
        out->has_padding = true;
    }

    return true;
}

static inline bool wid_parse(const char *wid, int W, int Z, parsed_wid_t *out) {
    return wid_parse_ex(wid, W, Z, WID_TIME_SEC, out);
}

static inline bool hlc_wid_parse(const char *wid, int W, int Z, parsed_hlc_wid_t *out) {
    return hlc_wid_parse_ex(wid, W, Z, WID_TIME_SEC, out);
}

static inline void wid_random_hex(char *buf, int len) {
    static const char hex[] = "0123456789abcdef";
    unsigned char raw[(WID_MAX_Z / 2) + 1];
#if defined(__linux__) || defined(__APPLE__)
    FILE *f = fopen("/dev/urandom", "r");
    if (f) { fread(raw, 1, (size_t)len, f); fclose(f); }
    else
#endif
    { for (int i = 0; i < len; i++) raw[i] = (unsigned char)rand(); }
    for (int i = 0; i < len; i++) buf[i] = hex[raw[i] & 0x0f];
    buf[len] = '\0';
}

static inline int64_t wid_now_tick(wid_time_unit_t unit) {
    if (unit == WID_TIME_MS) {
#if defined(TIME_UTC)
        struct timespec ts;
        if (timespec_get(&ts, TIME_UTC) == TIME_UTC) {
            return (int64_t)ts.tv_sec * 1000 + (int64_t)(ts.tv_nsec / 1000000);
        }
#endif
        return (int64_t)time(NULL) * 1000;
    }
    return (int64_t)time(NULL);
}

static inline int64_t wid_now_monotonic_ns(void) {
#if defined(CLOCK_MONOTONIC)
    struct timespec ts_mono;
    if (clock_gettime(CLOCK_MONOTONIC, &ts_mono) == 0) {
        return (int64_t)ts_mono.tv_sec * 1000000000LL + ts_mono.tv_nsec;
    }
#endif
#if defined(TIME_UTC)
    struct timespec ts_utc;
    if (timespec_get(&ts_utc, TIME_UTC) == TIME_UTC) {
        return (int64_t)ts_utc.tv_sec * 1000000000LL + ts_utc.tv_nsec;
    }
#endif
    return (int64_t)clock() * (1000000000LL / CLOCKS_PER_SEC);
}

static inline void wid_fmt_tick(wid_time_unit_t unit, int64_t tick, char out[24]) {
    int64_t sec = tick;
    int ms = 0;

    if (unit == WID_TIME_MS) {
        sec = tick / 1000;
        ms = (int)(tick % 1000);
        if (ms < 0) ms += 1000;
    }

    time_t t = (time_t)sec;
    struct tm tm_buf;
    struct tm *tm_ptr;
#if (defined(_POSIX_C_SOURCE) && _POSIX_C_SOURCE >= 1) || defined(_GNU_SOURCE)
    tm_ptr = gmtime_r(&t, &tm_buf);
#else
    tm_ptr = gmtime(&t);
    if (tm_ptr) { tm_buf = *tm_ptr; tm_ptr = &tm_buf; }
#endif
    if (!tm_ptr) {
        out[0] = '\0';
        return;
    }

    char base[20];
    strftime(base, sizeof(base), "%Y%m%dT%H%M%S", tm_ptr);
    if (unit == WID_TIME_MS) {
        snprintf(out, 24, "%s%03d", base, ms);
    } else {
        snprintf(out, 24, "%s", base);
    }
}

static inline int64_t wid_pow10_i64(int n) {
    int64_t v = 1;
    for (int i = 0; i < n; i++) {
        if (v > INT64_MAX / 10) return INT64_MAX;
        v *= 10;
    }
    return v;
}

static inline void wid_gen_init_ex(wid_gen_t *gen, int W, int Z, wid_time_unit_t unit) {
    gen->W = W > 0 ? W : WID_DEFAULT_W;
    gen->Z = Z >= 0 ? Z : WID_DEFAULT_Z;
    gen->time_unit = unit;

    if (gen->W > WID_MAX_W) gen->W = WID_MAX_W;
    if (gen->Z > WID_MAX_Z) gen->Z = WID_MAX_Z;

    gen->last_tick = 0;
    gen->last_seq = -1;
    gen->max_seq = wid_pow10_i64(gen->W) - 1;
}

static inline void wid_gen_init(wid_gen_t *gen, int W, int Z) {
    wid_gen_init_ex(gen, W, Z, WID_TIME_SEC);
}

static inline void wid_gen_next(wid_gen_t *gen, char *out, size_t out_len) {
    int64_t now_tick = wid_now_tick(gen->time_unit);
    int64_t tick = now_tick > gen->last_tick ? now_tick : gen->last_tick;

    int64_t seq = (tick == gen->last_tick) ? (gen->last_seq + 1) : 0;
    if (seq > gen->max_seq) {
        tick += 1;
        seq = 0;
    }

    gen->last_tick = tick;
    gen->last_seq = seq;

    char ts[24];
    wid_fmt_tick(gen->time_unit, tick, ts);

    char seq_str[64];
    snprintf(seq_str, sizeof(seq_str), "%0*lld", gen->W, (long long)seq);

    if (gen->Z > 0) {
        char pad[WID_MAX_Z + 1];
        wid_random_hex(pad, gen->Z);
        snprintf(out, out_len, "%s.%sZ-%s", ts, seq_str, pad);
    } else {
        snprintf(out, out_len, "%s.%sZ", ts, seq_str);
    }
}

static inline bool hlc_wid_gen_init_ex(
    hlc_wid_gen_t *gen,
    const char *node,
    int W,
    int Z,
    wid_time_unit_t unit
) {
    if (!wid_valid_node(node)) return false;

    gen->W = W > 0 ? W : WID_DEFAULT_W;
    gen->Z = Z >= 0 ? Z : 0;
    gen->time_unit = unit;

    if (gen->W > WID_MAX_W) gen->W = WID_MAX_W;
    if (gen->Z > WID_MAX_Z) gen->Z = WID_MAX_Z;

    strncpy(gen->node, node, sizeof(gen->node) - 1);
    gen->node[sizeof(gen->node) - 1] = '\0';

    gen->pt = 0;
    gen->lc = 0;
    gen->max_lc = wid_pow10_i64(gen->W) - 1;
    return true;
}

static inline bool hlc_wid_gen_init(hlc_wid_gen_t *gen, const char *node, int W, int Z) {
    return hlc_wid_gen_init_ex(gen, node, W, Z, WID_TIME_SEC);
}

static inline void hlc_wid_rollover_if_needed(hlc_wid_gen_t *gen) {
    if (gen->lc > gen->max_lc) {
        gen->pt += 1;
        gen->lc = 0;
    }
}

static inline bool hlc_wid_observe(hlc_wid_gen_t *gen, int64_t remote_pt, int64_t remote_lc) {
    if (remote_pt < 0 || remote_lc < 0) return false;

    int64_t now = wid_now_tick(gen->time_unit);
    int64_t new_pt = now;
    if (gen->pt > new_pt) new_pt = gen->pt;
    if (remote_pt > new_pt) new_pt = remote_pt;

    if (new_pt == gen->pt && new_pt == remote_pt) {
        gen->lc = (gen->lc > remote_lc ? gen->lc : remote_lc) + 1;
    } else if (new_pt == gen->pt) {
        gen->lc += 1;
    } else if (new_pt == remote_pt) {
        gen->lc = remote_lc + 1;
    } else {
        gen->lc = 0;
    }

    gen->pt = new_pt;
    hlc_wid_rollover_if_needed(gen);
    return true;
}

static inline void hlc_wid_gen_next(hlc_wid_gen_t *gen, char *out, size_t out_len) {
    int64_t now = wid_now_tick(gen->time_unit);

    if (now > gen->pt) {
        gen->pt = now;
        gen->lc = 0;
    } else {
        gen->lc += 1;
    }

    hlc_wid_rollover_if_needed(gen);

    char ts[24];
    wid_fmt_tick(gen->time_unit, gen->pt, ts);

    char lc_str[64];
    snprintf(lc_str, sizeof(lc_str), "%0*lld", gen->W, (long long)gen->lc);

    if (gen->Z > 0) {
        char pad[WID_MAX_Z + 1];
        wid_random_hex(pad, gen->Z);
        snprintf(out, out_len, "%s.%sZ-%s-%s", ts, lc_str, gen->node, pad);
    } else {
        snprintf(out, out_len, "%s.%sZ-%s", ts, lc_str, gen->node);
    }
}

/* ---- Sync bulk helpers ---- */

static inline bool wid_gen_next_n(wid_gen_t *gen, int n, char out[][WID_MAX_LEN]) {
    if (!gen || !out || n < 0) return false;
    for (int i = 0; i < n; i++) {
        wid_gen_next(gen, out[i], WID_MAX_LEN);
    }
    return true;
}

static inline bool hlc_wid_gen_next_n(hlc_wid_gen_t *gen, int n, char out[][WID_MAX_LEN]) {
    if (!gen || !out || n < 0) return false;
    for (int i = 0; i < n; i++) {
        hlc_wid_gen_next(gen, out[i], WID_MAX_LEN);
    }
    return true;
}

/* ---- Async poll-based stream helpers ---- */

static inline bool wid_async_wid_stream_init(
    wid_async_wid_stream_t *s,
    int W,
    int Z,
    wid_time_unit_t unit,
    int count,
    int interval_ms
) {
    if (!s || count < 0 || interval_ms < 0) return false;
    memset(s, 0, sizeof(*s));
    wid_gen_init_ex(&s->gen, W, Z, unit);
    s->remaining = count == 0 ? -1 : count;
    s->interval_ms = interval_ms;
    s->next_due_ns = 0;
    s->initialized = true;
    return true;
}

static inline bool wid_async_wid_stream_done(const wid_async_wid_stream_t *s) {
    return !s || !s->initialized || s->remaining == 0;
}

static inline bool wid_async_wid_stream_poll(
    wid_async_wid_stream_t *s,
    char *out,
    size_t out_len
) {
    if (!s || !s->initialized || !out) return false;
    if (s->remaining == 0) return false;

    int64_t now_ns = wid_now_monotonic_ns();
    if (s->next_due_ns > 0 && now_ns < s->next_due_ns) {
        return false; /* not due yet */
    }

    wid_gen_next(&s->gen, out, out_len);
    if (s->remaining > 0) s->remaining--;
    s->next_due_ns = now_ns + (int64_t)s->interval_ms * 1000000LL;
    return true;
}

static inline bool wid_async_hlc_stream_init(
    wid_async_hlc_stream_t *s,
    const char *node,
    int W,
    int Z,
    wid_time_unit_t unit,
    int count,
    int interval_ms
) {
    if (!s || count < 0 || interval_ms < 0) return false;
    memset(s, 0, sizeof(*s));
    if (!hlc_wid_gen_init_ex(&s->gen, node, W, Z, unit)) return false;
    s->remaining = count == 0 ? -1 : count;
    s->interval_ms = interval_ms;
    s->next_due_ns = 0;
    s->initialized = true;
    return true;
}

static inline bool wid_async_hlc_stream_done(const wid_async_hlc_stream_t *s) {
    return !s || !s->initialized || s->remaining == 0;
}

static inline bool wid_async_hlc_stream_poll(
    wid_async_hlc_stream_t *s,
    char *out,
    size_t out_len
) {
    if (!s || !s->initialized || !out) return false;
    if (s->remaining == 0) return false;

    int64_t now_ns = wid_now_monotonic_ns();
    if (s->next_due_ns > 0 && now_ns < s->next_due_ns) {
        return false; /* not due yet */
    }

    hlc_wid_gen_next(&s->gen, out, out_len);
    if (s->remaining > 0) s->remaining--;
    s->next_due_ns = now_ns + (int64_t)s->interval_ms * 1000000LL;
    return true;
}

#endif /* WID_H */
