/* libFuzzer harness for the wid.h string parsers — the surface that consumes
 * untrusted input. Build: make fuzz (clang only; links -fsanitize=fuzzer).
 *
 * The whole input is treated as the candidate WID string, so seed corpora
 * are plain human-readable WIDs. Each input is driven through validate and
 * parse for both kinds (plain / HLC) across a fixed matrix of parameter
 * shapes covering the W/Z/unit extremes, plus one shape derived from the
 * input bytes so the fuzzer can reach every W/Z combination.
 */
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#include "wid.h"

static void drive(const char *s, int W, int Z, wid_time_unit_t unit) {
    parsed_wid_t p;
    parsed_hlc_wid_t hp;
    (void)wid_validate_ex(s, W, Z, unit);
    (void)hlc_wid_validate_ex(s, W, Z, unit);
    (void)wid_parse_ex(s, W, Z, unit, &p);
    (void)hlc_wid_parse_ex(s, W, Z, unit, &hp);
}

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size);

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
    /* Longest legal WID: 17 ts + 1 dot + 18 seq + 1 Z + 64 node + 1 dash
     * + 64 pad + slack. Anything longer must be rejected, so cap generously
     * above WID_MAX_LEN to also exercise the over-length path. */
    char buf[2 * WID_MAX_LEN];
    if (size >= sizeof(buf)) size = sizeof(buf) - 1;
    memcpy(buf, data, size);
    buf[size] = '\0';

    static const struct {
        int W;
        int Z;
        wid_time_unit_t unit;
    } shapes[] = {
        {WID_DEFAULT_W, WID_DEFAULT_Z, WID_TIME_SEC},
        {WID_DEFAULT_W, 0, WID_TIME_SEC},
        {1, 0, WID_TIME_SEC},
        {WID_MAX_W, WID_MAX_Z, WID_TIME_MS},
        {WID_DEFAULT_W, WID_DEFAULT_Z, WID_TIME_MS},
    };
    for (size_t i = 0; i < sizeof(shapes) / sizeof(shapes[0]); i++) {
        drive(buf, shapes[i].W, shapes[i].Z, shapes[i].unit);
    }

    /* Input-derived shape: lets the fuzzer explore the full parameter space
     * (including out-of-range W/Z, which must fail cleanly, never crash). */
    uint32_t h = 2166136261u;
    for (size_t i = 0; i < size; i++) h = (h ^ data[i]) * 16777619u;
    int W = (int)(h % (WID_MAX_W + 2));            /* 0..19: includes invalid */
    int Z = (int)((h >> 8) % (WID_MAX_Z + 2));     /* 0..65: includes invalid */
    wid_time_unit_t unit = (h & 0x10000) ? WID_TIME_MS : WID_TIME_SEC;
    drive(buf, W, Z, unit);

    /* Auxiliary string consumers. */
    wid_time_unit_t u;
    (void)wid_time_unit_from_str(buf, &u);
    (void)wid_valid_node(buf);

    return 0;
}
