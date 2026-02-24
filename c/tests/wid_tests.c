#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "wid.h"

static int g_failures = 0;

#define CHECK(cond, msg)            \
    do {                            \
        if (!(cond)) {              \
            fprintf(stderr, "FAIL: %s\\n", (msg)); \
            g_failures++;           \
        }                           \
    } while (0)

static void test_validate_wid(void) {
    CHECK(wid_validate("20260212T091530.0000Z", 4, 0), "minimal wid should validate");
    CHECK(wid_validate("20260212T091530.0042Z-a3f91c", 4, 6), "wid with lowercase padding should validate");
    CHECK(wid_validate_ex("20260212T091530123.0042Z-a3f91c", 4, 6, WID_TIME_MS), "wid ms should validate");

    CHECK(!wid_validate("waldiez", 4, 6), "non-wid should fail");
    CHECK(!wid_validate("20260212T091530.0000", 4, 0), "missing Z should fail");
    CHECK(!wid_validate("20260212T091530.0000z", 4, 0), "lowercase z should fail");
    CHECK(!wid_validate("2026-02-12T09:15:30.0000Z", 4, 0), "extended iso should fail");
    CHECK(!wid_validate("20261312T091530.0000Z", 4, 0), "invalid month should fail");
    CHECK(!wid_validate("20260230T091530.0000Z", 4, 0), "invalid day should fail");
    CHECK(!wid_validate("20260212T251530.0000Z", 4, 0), "invalid hour should fail");
    CHECK(!wid_validate("20260212T091530.0000Z-ABCDEF", 4, 6), "uppercase padding should fail");
    CHECK(!wid_validate("20260212T091530.0000Z-node01", 4, 0), "hlc id should not validate as wid");

    CHECK(!wid_validate_ex("20260212T09153012.0000Z", 4, 0, WID_TIME_MS), "ms timestamp too short should fail");
    CHECK(!wid_validate_ex("20260212T0915301234.0000Z", 4, 0, WID_TIME_MS), "ms timestamp too long should fail");

    CHECK(wid_validate("20240229T091530.0000Z", 4, 0), "leap day should validate");
    CHECK(!wid_validate("20230229T091530.0000Z", 4, 0), "non-leap feb29 should fail");
}

static void test_validate_hlc(void) {
    CHECK(hlc_wid_validate("20260212T091530.0000Z-node01", 4, 0), "hlc without pad should validate");
    CHECK(hlc_wid_validate("20260212T091530.0042Z-node01-a3f91c", 4, 6), "hlc with pad should validate");
    CHECK(hlc_wid_validate("20260212T091530.0042Z-my_node", 4, 0), "underscore in node should validate");
    CHECK(hlc_wid_validate_ex("20260212T091530123.0042Z-node01-a3f91c", 4, 6, WID_TIME_MS), "hlc ms should validate");

    CHECK(!hlc_wid_validate("20260212T091530.0000Z", 4, 0), "plain wid should not validate as hlc");
    CHECK(!hlc_wid_validate("20260212T091530.0000Z-node-01", 4, 0), "hyphen in node should fail");
    CHECK(!hlc_wid_validate("20260212T091530.0000Z-node01-ABCDEF", 4, 6), "uppercase hlc pad should fail");
    CHECK(!hlc_wid_validate("20260212T091530.0000Z-node$", 4, 0), "symbol in node should fail");
}

static void test_parse_wid(void) {
    parsed_wid_t p;
    CHECK(wid_parse("20260212T091530.0042Z-a3f91c", 4, 6, &p), "wid parse should succeed");
    CHECK(p.sequence == 42, "wid parse sequence should be 42");
    CHECK(p.has_padding, "wid parse should report padding");
    CHECK(strcmp(p.padding, "a3f91c") == 0, "wid parse padding should match");

    CHECK(wid_parse_ex("20260212T091530123.0042Z", 4, 0, WID_TIME_MS, &p), "wid parse ms should succeed");
    CHECK(p.millisecond == 123, "wid parse ms should carry millisecond");

    CHECK(!wid_parse("waldiez", 4, 0, &p), "wid parse invalid should fail");
}

static void test_parse_hlc(void) {
    parsed_hlc_wid_t p;
    CHECK(hlc_wid_parse("20260212T091530.0042Z-node01-a3f91c", 4, 6, &p), "hlc parse should succeed");
    CHECK(p.logical_counter == 42, "hlc parse lc should be 42");
    CHECK(strcmp(p.node, "node01") == 0, "hlc parse node should match");
    CHECK(p.has_padding, "hlc parse should report padding");
    CHECK(strcmp(p.padding, "a3f91c") == 0, "hlc parse padding should match");

    CHECK(hlc_wid_parse_ex("20260212T091530123.0042Z-node01", 4, 0, WID_TIME_MS, &p), "hlc parse ms should succeed");
    CHECK(p.millisecond == 123, "hlc parse ms should carry millisecond");

    CHECK(!hlc_wid_parse("20260212T091530.0000Z-node-01", 4, 0, &p), "hlc parse invalid should fail");
}

static void test_wid_gen(void) {
    wid_gen_t gen;
    char a[WID_MAX_LEN];
    char b[WID_MAX_LEN];
    char p[WID_MAX_LEN];

    wid_gen_init(&gen, 4, 0);
    wid_gen_next(&gen, a, sizeof(a));
    wid_gen_next(&gen, b, sizeof(b));

    CHECK(wid_validate(a, 4, 0), "generated wid a should validate");
    CHECK(wid_validate(b, 4, 0), "generated wid b should validate");
    CHECK(strcmp(a, b) < 0, "generated wid sequence should be monotonic when Z=0");

    wid_gen_init(&gen, 4, 6);
    wid_gen_next(&gen, p, sizeof(p));
    CHECK(wid_validate(p, 4, 6), "generated wid with padding should validate");

    wid_gen_init_ex(&gen, 4, 0, WID_TIME_MS);
    wid_gen_next(&gen, p, sizeof(p));
    CHECK(wid_validate_ex(p, 4, 0, WID_TIME_MS), "generated wid in ms mode should validate");
}

static void test_hlc_gen(void) {
    hlc_wid_gen_t gen;
    char id1[WID_MAX_LEN];
    char id2[WID_MAX_LEN];

    CHECK(!hlc_wid_gen_init(&gen, "bad-node", 4, 0), "invalid node should fail init");
    CHECK(hlc_wid_gen_init(&gen, "node01", 4, 0), "valid node should init");

    hlc_wid_gen_next(&gen, id1, sizeof(id1));
    hlc_wid_gen_next(&gen, id2, sizeof(id2));

    CHECK(hlc_wid_validate(id1, 4, 0), "generated hlc id1 should validate");
    CHECK(hlc_wid_validate(id2, 4, 0), "generated hlc id2 should validate");
    CHECK(strcmp(id1, id2) <= 0, "hlc ids should be non-decreasing");

    CHECK(!hlc_wid_observe(&gen, -1, 0), "observe with negative pt should fail");
    CHECK(!hlc_wid_observe(&gen, 1, -1), "observe with negative lc should fail");

    {
        int64_t remote_pt = wid_now_tick(gen.time_unit) + 5;
        CHECK(hlc_wid_observe(&gen, remote_pt, 9), "observe remote event should succeed");
        hlc_wid_gen_next(&gen, id1, sizeof(id1));
        CHECK(hlc_wid_validate(id1, 4, 0), "hlc id after observe should validate");
    }

    CHECK(hlc_wid_gen_init_ex(&gen, "node01", 4, 0, WID_TIME_MS), "hlc ms init should work");
    hlc_wid_gen_next(&gen, id1, sizeof(id1));
    CHECK(hlc_wid_validate_ex(id1, 4, 0, WID_TIME_MS), "generated hlc in ms mode should validate");
}

static void test_bulk_sync_api(void) {
    wid_gen_t wg;
    char out_w[3][WID_MAX_LEN];
    wid_gen_init_ex(&wg, 4, 0, WID_TIME_MS);
    CHECK(wid_gen_next_n(&wg, 3, out_w), "wid_gen_next_n should succeed");
    CHECK(wid_validate_ex(out_w[0], 4, 0, WID_TIME_MS), "bulk wid[0] should validate");
    CHECK(wid_validate_ex(out_w[1], 4, 0, WID_TIME_MS), "bulk wid[1] should validate");
    CHECK(wid_validate_ex(out_w[2], 4, 0, WID_TIME_MS), "bulk wid[2] should validate");

    hlc_wid_gen_t hg;
    char out_h[2][WID_MAX_LEN];
    CHECK(hlc_wid_gen_init_ex(&hg, "node01", 4, 0, WID_TIME_MS), "hlc bulk init should work");
    CHECK(hlc_wid_gen_next_n(&hg, 2, out_h), "hlc_wid_gen_next_n should succeed");
    CHECK(hlc_wid_validate_ex(out_h[0], 4, 0, WID_TIME_MS), "bulk hlc[0] should validate");
    CHECK(hlc_wid_validate_ex(out_h[1], 4, 0, WID_TIME_MS), "bulk hlc[1] should validate");
}

static void test_async_poll_api(void) {
    wid_async_wid_stream_t ws;
    char id[WID_MAX_LEN];
    CHECK(wid_async_wid_stream_init(&ws, 4, 0, WID_TIME_SEC, 2, 0), "wid async init should work");
    CHECK(!wid_async_wid_stream_done(&ws), "wid async should not be done initially");
    CHECK(wid_async_wid_stream_poll(&ws, id, sizeof(id)), "wid async first poll should emit");
    CHECK(wid_validate(id, 4, 0), "wid async emitted id should validate");
    CHECK(wid_async_wid_stream_poll(&ws, id, sizeof(id)), "wid async second poll should emit");
    CHECK(wid_validate(id, 4, 0), "wid async emitted id should validate");
    CHECK(wid_async_wid_stream_done(&ws), "wid async should be done after count");
    CHECK(!wid_async_wid_stream_poll(&ws, id, sizeof(id)), "wid async poll after done should fail");

    wid_async_hlc_stream_t hs;
    CHECK(wid_async_hlc_stream_init(&hs, "node01", 4, 0, WID_TIME_SEC, 2, 0), "hlc async init should work");
    CHECK(!wid_async_hlc_stream_done(&hs), "hlc async should not be done initially");
    CHECK(wid_async_hlc_stream_poll(&hs, id, sizeof(id)), "hlc async first poll should emit");
    CHECK(hlc_wid_validate(id, 4, 0), "hlc async emitted id should validate");
    CHECK(wid_async_hlc_stream_poll(&hs, id, sizeof(id)), "hlc async second poll should emit");
    CHECK(hlc_wid_validate(id, 4, 0), "hlc async emitted id should validate");
    CHECK(wid_async_hlc_stream_done(&hs), "hlc async should be done after count");
    CHECK(!wid_async_hlc_stream_poll(&hs, id, sizeof(id)), "hlc async poll after done should fail");
}

static void test_low_level_helpers(void) {
    CHECK(wid_valid_node("node01"), "node01 valid");
    CHECK(wid_valid_node("my_node"), "my_node valid");
    CHECK(!wid_valid_node(""), "empty node invalid");
    CHECK(!wid_valid_node("bad node"), "space in node invalid");
    CHECK(!wid_valid_node("bad-node"), "hyphen in node invalid");
    CHECK(!wid_valid_node("node$"), "symbol in node invalid");

    CHECK(wid_valid_suffix("", 6), "empty suffix accepted");
    CHECK(wid_valid_suffix("-a3f91c", 6), "valid lowercase suffix accepted");
    CHECK(!wid_valid_suffix("-ABCDEF", 6), "uppercase suffix invalid");
    CHECK(!wid_valid_suffix("-abc", 6), "short suffix invalid");
    CHECK(!wid_valid_suffix("a3f91c", 6), "missing dash suffix invalid");
    CHECK(!wid_valid_suffix("-a3f91c", 0), "suffix not allowed when Z=0");
}

int main(void) {
    srand(1);

    test_validate_wid();
    test_validate_hlc();
    test_parse_wid();
    test_parse_hlc();
    test_wid_gen();
    test_hlc_gen();
    test_bulk_sync_api();
    test_async_poll_api();
    test_low_level_helpers();

    if (g_failures != 0) {
        fprintf(stderr, "\\n%d test(s) failed.\\n", g_failures);
        return 1;
    }

    puts("all C tests passed");
    return 0;
}
