#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "wid.h"

static int g_failures = 0;

#define CHECK(cond, msg)            \
    do {                            \
        if (!(cond)) {              \
            fprintf(stderr, "FAIL: %s\n", (msg)); \
            g_failures++;           \
        }                           \
    } while (0)

/* ── Original tests (preserved) ──────────────────────────────────────── */

static void test_validate_wid(void) {
    CHECK(wid_validate("20260212T091530.0000Z", 4, 0), "minimal wid");
    CHECK(wid_validate("20260212T091530.0042Z-a3f91c", 4, 6), "wid with pad");
    CHECK(wid_validate_ex("20260212T091530123.0042Z-a3f91c", 4, 6, WID_TIME_MS), "wid ms");

    CHECK(!wid_validate("waldiez", 4, 6), "non-wid");
    CHECK(!wid_validate("20260212T091530.0000", 4, 0), "missing Z");
    CHECK(!wid_validate("20260212T091530.0000z", 4, 0), "lowercase z");
    CHECK(!wid_validate("2026-02-12T09:15:30.0000Z", 4, 0), "extended iso");
    CHECK(!wid_validate("20261312T091530.0000Z", 4, 0), "invalid month");
    CHECK(!wid_validate("20260230T091530.0000Z", 4, 0), "invalid day");
    CHECK(!wid_validate("20260212T251530.0000Z", 4, 0), "invalid hour");
    CHECK(!wid_validate("20260212T091530.0000Z-ABCDEF", 4, 6), "uppercase pad");
    CHECK(!wid_validate("20260212T091530.0000Z-node01", 4, 0), "hlc as wid");

    CHECK(!wid_validate_ex("20260212T09153012.0000Z", 4, 0, WID_TIME_MS), "ms too short");
    CHECK(!wid_validate_ex("20260212T0915301234.0000Z", 4, 0, WID_TIME_MS), "ms too long");

    CHECK(wid_validate("20240229T091530.0000Z", 4, 0), "leap day");
    CHECK(!wid_validate("20230229T091530.0000Z", 4, 0), "non-leap feb29");
}

static void test_validate_hlc(void) {
    CHECK(hlc_wid_validate("20260212T091530.0000Z-node01", 4, 0), "hlc no pad");
    CHECK(hlc_wid_validate("20260212T091530.0042Z-node01-a3f91c", 4, 6), "hlc with pad");
    CHECK(hlc_wid_validate("20260212T091530.0042Z-my_node", 4, 0), "underscore node");
    CHECK(hlc_wid_validate_ex("20260212T091530123.0042Z-node01-a3f91c", 4, 6, WID_TIME_MS), "hlc ms");

    CHECK(!hlc_wid_validate("20260212T091530.0000Z", 4, 0), "plain wid as hlc");
    CHECK(!hlc_wid_validate("20260212T091530.0000Z-node-01", 4, 0), "hyphen node");
    CHECK(!hlc_wid_validate("20260212T091530.0000Z-node01-ABCDEF", 4, 6), "uppercase hlc pad");
    CHECK(!hlc_wid_validate("20260212T091530.0000Z-node$", 4, 0), "symbol node");
}

static void test_parse_wid(void) {
    parsed_wid_t p;
    CHECK(wid_parse("20260212T091530.0042Z-a3f91c", 4, 6, &p), "parse ok");
    CHECK(p.sequence == 42, "seq 42");
    CHECK(p.has_padding, "has pad");
    CHECK(strcmp(p.padding, "a3f91c") == 0, "pad match");

    CHECK(wid_parse_ex("20260212T091530123.0042Z", 4, 0, WID_TIME_MS, &p), "parse ms");
    CHECK(p.millisecond == 123, "ms 123");

    CHECK(!wid_parse("waldiez", 4, 0, &p), "parse invalid");
}

static void test_parse_hlc(void) {
    parsed_hlc_wid_t p;
    CHECK(hlc_wid_parse("20260212T091530.0042Z-node01-a3f91c", 4, 6, &p), "hlc parse ok");
    CHECK(p.logical_counter == 42, "lc 42");
    CHECK(strcmp(p.node, "node01") == 0, "node match");
    CHECK(p.has_padding, "has pad");
    CHECK(strcmp(p.padding, "a3f91c") == 0, "pad match");

    CHECK(hlc_wid_parse_ex("20260212T091530123.0042Z-node01", 4, 0, WID_TIME_MS, &p), "hlc parse ms");
    CHECK(p.millisecond == 123, "hlc ms 123");

    CHECK(!hlc_wid_parse("20260212T091530.0000Z-node-01", 4, 0, &p), "hlc invalid");

    /* validate and parse must agree on node length */
    {
        char long_node[WID_MAX_LEN + 1];
        char long_id[WID_MAX_LEN + 64];
        memset(long_node, 'n', 70);
        long_node[70] = '\0';
        snprintf(long_id, sizeof(long_id), "20260212T091530.0000Z-%s", long_node);
        CHECK(hlc_wid_validate(long_id, 4, 0), "70-char node validate");
        CHECK(hlc_wid_parse(long_id, 4, 0, &p), "70-char node parse");
        CHECK(strcmp(p.node, long_node) == 0, "70-char node roundtrip");

        memset(long_node, 'n', WID_MAX_LEN);
        long_node[WID_MAX_LEN] = '\0';
        snprintf(long_id, sizeof(long_id), "20260212T091530.0000Z-%s", long_node);
        CHECK(!hlc_wid_validate(long_id, 4, 0), "256-char node reject validate");
        CHECK(!hlc_wid_parse(long_id, 4, 0, &p), "256-char node reject parse");
    }
}

static void test_wid_gen(void) {
    wid_gen_t gen;
    char a[WID_MAX_LEN], b[WID_MAX_LEN], p[WID_MAX_LEN];

    wid_gen_init(&gen, 4, 0);
    wid_gen_next(&gen, a, sizeof(a));
    wid_gen_next(&gen, b, sizeof(b));
    CHECK(wid_validate(a, 4, 0), "gen a");
    CHECK(wid_validate(b, 4, 0), "gen b");
    CHECK(strcmp(a, b) < 0, "monotonic Z=0");

    wid_gen_init(&gen, 4, 6);
    wid_gen_next(&gen, p, sizeof(p));
    CHECK(wid_validate(p, 4, 6), "gen with pad");

    wid_gen_init_ex(&gen, 4, 0, WID_TIME_MS);
    wid_gen_next(&gen, p, sizeof(p));
    CHECK(wid_validate_ex(p, 4, 0, WID_TIME_MS), "gen ms");
}

static void test_hlc_gen(void) {
    hlc_wid_gen_t gen;
    char id1[WID_MAX_LEN], id2[WID_MAX_LEN];

    CHECK(!hlc_wid_gen_init(&gen, "bad-node", 4, 0), "bad node init");
    CHECK(hlc_wid_gen_init(&gen, "node01", 4, 0), "valid node init");

    {
        char long_node[WID_MAX_NODE_LEN + 2];
        memset(long_node, 'n', WID_MAX_NODE_LEN + 1);
        long_node[WID_MAX_NODE_LEN + 1] = '\0';
        CHECK(!hlc_wid_gen_init(&gen, long_node, 4, 0), "over-long node");
        long_node[WID_MAX_NODE_LEN] = '\0';
        CHECK(hlc_wid_gen_init(&gen, long_node, 4, 0), "max-length node");
        CHECK(hlc_wid_gen_init(&gen, "node01", 4, 0), "re-init");
    }

    hlc_wid_gen_next(&gen, id1, sizeof(id1));
    hlc_wid_gen_next(&gen, id2, sizeof(id2));
    CHECK(hlc_wid_validate(id1, 4, 0), "gen hlc a");
    CHECK(hlc_wid_validate(id2, 4, 0), "gen hlc b");
    CHECK(strcmp(id1, id2) <= 0, "hlc non-decreasing");

    CHECK(!hlc_wid_observe(&gen, -1, 0), "neg pt observe");
    CHECK(!hlc_wid_observe(&gen, 1, -1), "neg lc observe");

    {
        int64_t remote_pt = wid_now_tick(gen.time_unit) + 5;
        CHECK(hlc_wid_observe(&gen, remote_pt, 9), "observe ok");
        hlc_wid_gen_next(&gen, id1, sizeof(id1));
        CHECK(hlc_wid_validate(id1, 4, 0), "post-observe validate");
    }

    CHECK(hlc_wid_gen_init_ex(&gen, "node01", 4, 0, WID_TIME_MS), "hlc ms init");
    hlc_wid_gen_next(&gen, id1, sizeof(id1));
    CHECK(hlc_wid_validate_ex(id1, 4, 0, WID_TIME_MS), "gen hlc ms");
}

static void test_bulk_sync_api(void) {
    wid_gen_t wg;
    char out_w[3][WID_MAX_LEN];
    wid_gen_init_ex(&wg, 4, 0, WID_TIME_MS);
    CHECK(wid_gen_next_n(&wg, 3, out_w), "bulk wid ok");
    CHECK(wid_validate_ex(out_w[0], 4, 0, WID_TIME_MS), "bulk w[0]");
    CHECK(wid_validate_ex(out_w[1], 4, 0, WID_TIME_MS), "bulk w[1]");
    CHECK(wid_validate_ex(out_w[2], 4, 0, WID_TIME_MS), "bulk w[2]");

    hlc_wid_gen_t hg;
    char out_h[2][WID_MAX_LEN];
    CHECK(hlc_wid_gen_init_ex(&hg, "node01", 4, 0, WID_TIME_MS), "bulk hlc init");
    CHECK(hlc_wid_gen_next_n(&hg, 2, out_h), "bulk hlc ok");
    CHECK(hlc_wid_validate_ex(out_h[0], 4, 0, WID_TIME_MS), "bulk h[0]");
    CHECK(hlc_wid_validate_ex(out_h[1], 4, 0, WID_TIME_MS), "bulk h[1]");
}

static void test_async_poll_api(void) {
    wid_async_wid_stream_t ws;
    char id[WID_MAX_LEN];
    CHECK(wid_async_wid_stream_init(&ws, 4, 0, WID_TIME_SEC, 2, 0), "async wid init");
    CHECK(!wid_async_wid_stream_done(&ws), "async not done");
    CHECK(wid_async_wid_stream_poll(&ws, id, sizeof(id)), "async poll 1");
    CHECK(wid_validate(id, 4, 0), "async poll 1 valid");
    CHECK(wid_async_wid_stream_poll(&ws, id, sizeof(id)), "async poll 2");
    CHECK(wid_validate(id, 4, 0), "async poll 2 valid");
    CHECK(wid_async_wid_stream_done(&ws), "async done");
    CHECK(!wid_async_wid_stream_poll(&ws, id, sizeof(id)), "async poll after done");

    wid_async_hlc_stream_t hs;
    CHECK(wid_async_hlc_stream_init(&hs, "node01", 4, 0, WID_TIME_SEC, 2, 0), "async hlc init");
    CHECK(!wid_async_hlc_stream_done(&hs), "async hlc not done");
    CHECK(wid_async_hlc_stream_poll(&hs, id, sizeof(id)), "async hlc poll 1");
    CHECK(hlc_wid_validate(id, 4, 0), "async hlc poll 1 valid");
    CHECK(wid_async_hlc_stream_poll(&hs, id, sizeof(id)), "async hlc poll 2");
    CHECK(hlc_wid_validate(id, 4, 0), "async hlc poll 2 valid");
    CHECK(wid_async_hlc_stream_done(&hs), "async hlc done");
    CHECK(!wid_async_hlc_stream_poll(&hs, id, sizeof(id)), "async hlc poll after done");
}

static void test_low_level_helpers(void) {
    CHECK(wid_valid_node("node01"), "node01 valid");
    CHECK(wid_valid_node("my_node"), "my_node valid");
    CHECK(!wid_valid_node(""), "empty node");
    CHECK(!wid_valid_node("bad node"), "space node");
    CHECK(!wid_valid_node("bad-node"), "hyphen node");
    CHECK(!wid_valid_node("node$"), "symbol node");

    CHECK(wid_valid_suffix("", 6), "empty suffix ok");
    CHECK(wid_valid_suffix("-a3f91c", 6), "valid suffix");
    CHECK(!wid_valid_suffix("-ABCDEF", 6), "uppercase suffix");
    CHECK(!wid_valid_suffix("-abc", 6), "short suffix");
    CHECK(!wid_valid_suffix("a3f91c", 6), "missing dash");
    CHECK(!wid_valid_suffix("-a3f91c", 0), "Z=0 rejects suffix");
}

static void test_extreme_tick_saturates(void) {
    char out[24];
    wid_fmt_tick(WID_TIME_SEC, INT64_MAX, out);
    CHECK(strcmp(out, "99991231T235959") == 0, "high saturate sec");
    wid_fmt_tick(WID_TIME_MS, INT64_MIN, out);
    CHECK(strcmp(out, "19700101T000000000") == 0, "low saturate ms");
}

/* ── New tests ───────────────────────────────────────────────────────── */

static void test_timestamp_edge_cases(void) {
    CHECK(!wid_validate("00000101T000000.0000Z", 4, 0), "year 0000");
    CHECK(!hlc_wid_validate("00000101T000000.0000Z-node01", 4, 0), "hlc year 0000");
    CHECK(wid_validate("00010101T000000.0000Z", 4, 0), "year 0001");
    CHECK(hlc_wid_validate("00010101T000000.0000Z-node01", 4, 0), "hlc year 0001");
    CHECK(wid_validate("99991231T235959.0000Z", 4, 0), "year 9999");

    CHECK(wid_validate("20260101T000000.0000Z", 4, 0), "Jan 1");
    CHECK(wid_validate("20261231T000000.0000Z", 4, 0), "Dec 31");
    CHECK(!wid_validate("20260000T000000.0000Z", 4, 0), "month 00");
    CHECK(!wid_validate("20261300T000000.0000Z", 4, 0), "month 13");

    CHECK(!wid_validate("20260431T000000.0000Z", 4, 0), "Apr 31");
    CHECK(wid_validate("20260131T000000.0000Z", 4, 0), "Jan 31");
    CHECK(!wid_validate("20260230T000000.0000Z", 4, 0), "Feb 30 non-leap");
    CHECK(wid_validate("20200229T000000.0000Z", 4, 0), "Feb 29 leap 2020");
    CHECK(!wid_validate("20210229T000000.0000Z", 4, 0), "Feb 29 non-leap 2021");
    CHECK(wid_validate("20000229T000000.0000Z", 4, 0), "Feb 29 century 2000");
    CHECK(!wid_validate("19000229T000000.0000Z", 4, 0), "Feb 29 non-leap 1900");

    CHECK(!wid_validate("20260101T240000.0000Z", 4, 0), "hour 24");
    CHECK(!wid_validate("20260101T006000.0000Z", 4, 0), "minute 60");
    CHECK(!wid_validate("20260101T000060.0000Z", 4, 0), "second 60");
    CHECK(wid_validate("20260101T235959.0000Z", 4, 0), "23:59:59");

    CHECK(wid_validate_ex("20260101T000000000.0000Z", 4, 0, WID_TIME_MS), "ms 000");
    CHECK(wid_validate_ex("20260101T235959999.0000Z", 4, 0, WID_TIME_MS), "ms 999");
}

static void test_non_default_w_z(void) {
    CHECK(wid_validate("20260101T000000.0Z", 1, 0), "W=1");
    CHECK(hlc_wid_validate("20260101T000000.0Z-node01", 1, 0), "hlc W=1");
    CHECK(wid_validate("20260101T000000.000000000000000000Z", 18, 0), "W=18");
    CHECK(hlc_wid_validate("20260101T000000.000000000000000000Z-node01", 18, 0), "hlc W=18");

    CHECK(wid_validate("20260101T000000.0000Z", 4, 0), "Z=0");
    CHECK(wid_validate("20260101T000000.0000Z-a", 4, 1), "Z=1");
    {
        char buf[512], pad[65];
        memset(pad, 'a', 64);
        pad[64] = '\0';
        snprintf(buf, sizeof(buf), "20260101T000000.0000Z-%s", pad);
        CHECK(wid_validate(buf, 4, 64), "Z=64");
    }

    CHECK(wid_validate("20260101T000000.00Z-ab", 2, 2), "W=2 Z=2");
    CHECK(hlc_wid_validate("20260101T000000.000000Z-node01-abcdef", 6, 6), "hlc W=6 Z=6");

    CHECK(!wid_validate("20260101T000000.0000Z", 3, 0), "W=3 rejects W=4");
    CHECK(!wid_validate("20260101T000000.0000Z", 5, 0), "W=5 rejects W=4");
    CHECK(!wid_validate("20260101T000000.0000Z-ab", 4, 3), "Z=3 rejects Z=2 pad");
    CHECK(!wid_validate("20260101T000000.0000Z-ab", 4, 1), "Z=1 rejects Z=2 pad");
}

static void test_w_z_out_of_range(void) {
    CHECK(!wid_validate_ex("20260101T000000.0000Z", 0, 0, WID_TIME_SEC), "W=0");
    CHECK(!hlc_wid_validate_ex("20260101T000000.0000Z-node01", 0, 0, WID_TIME_SEC), "hlc W=0");
    CHECK(!wid_validate_ex("20260101T000000.0000Z", 19, 0, WID_TIME_SEC), "W=19");
    CHECK(!hlc_wid_validate_ex("20260101T000000.0000Z-node01", 19, 0, WID_TIME_SEC), "hlc W=19");
    CHECK(!wid_validate_ex("20260101T000000.0000Z", 4, 65, WID_TIME_SEC), "Z=65");
    CHECK(!wid_validate_ex("20260101T000000.0000Z", 4, -1, WID_TIME_SEC), "Z=-1");
}

static void test_parse_extraction(void) {
    parsed_wid_t p;
    CHECK(wid_parse("20260212T091530.0042Z-a3f91c", 4, 6, &p), "parse extract ok");
    CHECK(p.year == 2026, "year 2026");
    CHECK(p.month == 2, "month 2");
    CHECK(p.day == 12, "day 12");
    CHECK(p.hour == 9, "hour 9");
    CHECK(p.minute == 15, "minute 15");
    CHECK(p.second == 30, "second 30");
    CHECK(p.sequence == 42, "seq 42");
    CHECK(p.millisecond == 0, "ms 0 sec mode");

    CHECK(wid_parse("20260212T091530.0042Z", 4, 0, &p), "parse no pad");
    CHECK(!p.has_padding, "no pad flag");
    CHECK(p.padding[0] == '\0', "pad empty");

    parsed_hlc_wid_t hp;
    CHECK(hlc_wid_parse("20260212T091530.0042Z-node01-a3f91c", 4, 6, &hp), "hlc parse extract");
    CHECK(hp.year == 2026, "hlc year");
    CHECK(hp.logical_counter == 42, "hlc lc");
    CHECK(strcmp(hp.node, "node01") == 0, "hlc node");
    CHECK(hp.has_padding, "hlc pad flag");
    CHECK(strcmp(hp.padding, "a3f91c") == 0, "hlc pad value");

    CHECK(hlc_wid_parse("20260212T091530.0042Z-node01", 4, 0, &hp), "hlc no pad");
    CHECK(!hp.has_padding, "hlc no pad flag");

    const char *id = "20260212T091530.0042Z-node01";
    CHECK(hlc_wid_parse(id, 4, 0, &hp), "hlc raw check");
    CHECK(hp.raw == id, "raw pointer");
}

static void test_hlc_observe_branches(void) {
    hlc_wid_gen_t gen;
    CHECK(hlc_wid_gen_init(&gen, "node01", 4, 0), "hlc init");
    int64_t base = wid_now_tick(WID_TIME_SEC);

    /* Branch: new_pt == pt == remote_pt */
    {
        hlc_wid_gen_t g;
        CHECK(hlc_wid_gen_init(&g, "n1", 4, 0), "init n1");
        g.pt = base + 1000;
        g.lc = 5;
        CHECK(hlc_wid_observe(&g, base + 1000, 3), "observe pt==remote");
        CHECK(g.pt == base + 1000, "pt unchanged");
        CHECK(g.lc == 6, "lc max(5,3)+1=6");
    }

    /* Branch: new_pt == pt > remote_pt */
    {
        hlc_wid_gen_t g;
        CHECK(hlc_wid_gen_init(&g, "n2", 4, 0), "init n2");
        g.pt = base + 2000;
        g.lc = 3;
        CHECK(hlc_wid_observe(&g, base + 1000, 7), "observe pt ahead");
        CHECK(g.pt == base + 2000, "pt unchanged ahead");
        CHECK(g.lc == 4, "lc incremented");
    }

    /* Branch: new_pt == remote_pt > pt */
    {
        hlc_wid_gen_t g;
        CHECK(hlc_wid_gen_init(&g, "n3", 4, 0), "init n3");
        g.pt = base + 1000;
        g.lc = 2;
        CHECK(hlc_wid_observe(&g, base + 3000, 9), "observe remote ahead");
        CHECK(g.pt == base + 3000, "pt advanced to remote");
        CHECK(g.lc == 10, "lc remote_lc+1=10");
    }

    /* Branch: wall clock wins -> lc = 0 */
    {
        hlc_wid_gen_t g;
        CHECK(hlc_wid_gen_init(&g, "n4", 4, 0), "init n4");
        g.pt = 1;
        g.lc = 99;
        CHECK(hlc_wid_observe(&g, 2, 5), "observe wall clock wins");
        CHECK(g.pt >= base, "pt wall clock");
        CHECK(g.lc == 0, "lc reset 0");
    }

    /* Rollover: lc > max_lc */
    {
        hlc_wid_gen_t g;
        CHECK(hlc_wid_gen_init(&g, "n5", 1, 0), "init n5 W=1");
        g.pt = base + 5000;
        g.lc = 9;
        CHECK(hlc_wid_observe(&g, base + 5000, 9), "observe rollover");
        CHECK(g.pt == base + 5001, "pt rolled");
        CHECK(g.lc == 0, "lc reset after roll");
    }
}

static void test_gen_init_clamping(void) {
    wid_gen_t gen;
    wid_gen_init_ex(&gen, 0, -5, WID_TIME_SEC);
    CHECK(gen.W == WID_DEFAULT_W, "W=0 clamped to 4");
    CHECK(gen.Z == WID_DEFAULT_Z, "Z=-5 clamped to 6");

    wid_gen_init_ex(&gen, 19, 65, WID_TIME_MS);
    CHECK(gen.W == WID_MAX_W, "W=19 clamped to 18");
    CHECK(gen.Z == WID_MAX_Z, "Z=65 clamped to 64");

    hlc_wid_gen_t hg;
    CHECK(hlc_wid_gen_init_ex(&hg, "n", 19, 65, WID_TIME_SEC), "hlc clamp init ok");
    CHECK(hg.W == WID_MAX_W, "hlc W=19 clamped");
    CHECK(hg.Z == WID_MAX_Z, "hlc Z=65 clamped");

    CHECK(!hlc_wid_gen_init_ex(&hg, "", 4, 0, WID_TIME_SEC), "empty node fail");
    CHECK(!hlc_wid_gen_init_ex(&hg, NULL, 4, 0, WID_TIME_SEC), "NULL node fail");
}

static void test_null_safety(void) {
    CHECK(!wid_validate(NULL, 4, 0), "NULL wid validate");
    CHECK(!hlc_wid_validate(NULL, 4, 0), "NULL hlc validate");
    CHECK(!wid_validate_ex(NULL, 4, 0, WID_TIME_MS), "NULL wid ms");

    CHECK(!wid_parse("20260212T091530.0000Z", 4, 0, NULL), "NULL out wid parse");
    CHECK(!hlc_wid_parse("20260212T091530.0000Z-node01", 4, 0, NULL), "NULL out hlc parse");

    CHECK(!wid_gen_next_n(NULL, 1, NULL), "NULL gen next_n");
    CHECK(!hlc_wid_gen_next_n(NULL, 1, NULL), "NULL gen hlc next_n");

    wid_gen_t gen;
    wid_gen_init(&gen, 4, 0);
    char out[1][WID_MAX_LEN];
    CHECK(!wid_gen_next_n(&gen, -1, out), "neg n next_n");

    CHECK(!wid_async_wid_stream_init(NULL, 4, 0, WID_TIME_SEC, 1, 0), "NULL async init");
    CHECK(!wid_async_hlc_stream_init(NULL, "n", 4, 0, WID_TIME_SEC, 1, 0), "NULL hlc async");

    CHECK(wid_async_wid_stream_done(NULL), "NULL async done true");
    CHECK(!wid_async_wid_stream_poll(NULL, (char *)"x", WID_MAX_LEN), "NULL async poll");

    wid_async_wid_stream_t ws;
    CHECK(!wid_async_wid_stream_init(&ws, 4, 0, WID_TIME_SEC, -1, 0), "neg count async");
    CHECK(!wid_async_wid_stream_init(&ws, 4, 0, WID_TIME_SEC, 0, -1), "neg interval async");
}

static void test_more_low_level_helpers(void) {
    CHECK(wid_is_leap_year(2000), "2000 leap");
    CHECK(wid_is_leap_year(2020), "2020 leap");
    CHECK(wid_is_leap_year(2024), "2024 leap");
    CHECK(!wid_is_leap_year(1900), "1900 non-leap");
    CHECK(!wid_is_leap_year(2021), "2021 non-leap");
    CHECK(!wid_is_leap_year(2023), "2023 non-leap");

    wid_time_unit_t u;
    CHECK(wid_time_unit_from_str("sec", &u), "sec parse");
    CHECK(u == WID_TIME_SEC, "sec value");
    CHECK(wid_time_unit_from_str("ms", &u), "ms parse");
    CHECK(u == WID_TIME_MS, "ms value");
    CHECK(!wid_time_unit_from_str("bad", &u), "bad unit");
    CHECK(!wid_time_unit_from_str(NULL, &u), "NULL unit");
    CHECK(!wid_time_unit_from_str("sec", NULL), "NULL out");

    CHECK(strcmp(wid_time_unit_to_str(WID_TIME_SEC), "sec") == 0, "to_str sec");
    CHECK(strcmp(wid_time_unit_to_str(WID_TIME_MS), "ms") == 0, "to_str ms");

    CHECK(wid_timestamp_len(WID_TIME_SEC) == 15, "ts len sec");
    CHECK(wid_timestamp_len(WID_TIME_MS) == 18, "ts len ms");

    CHECK(wid_parse_digits_i64("0042", 4) == 42, "digits 0042");
    CHECK(wid_parse_digits_i64("0000", 4) == 0, "digits 0000");
    CHECK(wid_parse_digits_i64("9999", 4) == 9999, "digits 9999");
    CHECK(wid_parse_digits_i64("x", 1) == -1, "digits non-digit");

    CHECK(wid_valid_ymdhms(2026, 1, 1, 0, 0, 0), "ymdhms valid");
    CHECK(!wid_valid_ymdhms(0, 1, 1, 0, 0, 0), "ymdhms year 0");
    CHECK(!wid_valid_ymdhms(2026, 0, 1, 0, 0, 0), "ymdhms month 0");
    CHECK(!wid_valid_ymdhms(2026, 13, 1, 0, 0, 0), "ymdhms month 13");
    CHECK(wid_valid_ymdhms(2026, 1, 31, 0, 0, 0), "ymdhms Jan 31");
    CHECK(!wid_valid_ymdhms(2026, 4, 31, 0, 0, 0), "ymdhms Apr 31");

    CHECK(wid_clamp_tick(WID_TIME_SEC, -1) == 0, "clamp -1 sec");
    CHECK(wid_clamp_tick(WID_TIME_MS, -100) == 0, "clamp -100 ms");
    int64_t max_sec = 253402300799LL;
    CHECK(wid_clamp_tick(WID_TIME_SEC, max_sec + 1) == max_sec, "clamp above max");
    CHECK(wid_clamp_tick(WID_TIME_SEC, 1000000) == 1000000, "clamp passthrough");

    CHECK(wid_pow10_i64(0) == 1, "pow10 0");
    CHECK(wid_pow10_i64(3) == 1000, "pow10 3");
    CHECK(wid_pow10_i64(18) > 0, "pow10 18 non-zero");
}

static void test_fmt_tick_more(void) {
    char out[24];

    wid_fmt_tick(WID_TIME_SEC, 0, out);
    CHECK(strcmp(out, "19700101T000000") == 0, "epoch sec");

    wid_fmt_tick(WID_TIME_MS, 0, out);
    CHECK(strcmp(out, "19700101T000000000") == 0, "epoch ms");

    wid_fmt_tick(WID_TIME_MS, -1, out);
    CHECK(strcmp(out, "19700101T000000000") == 0, "neg ms clamped");
}

static void test_async_stream_interval(void) {
    wid_async_wid_stream_t ws;
    CHECK(wid_async_wid_stream_init(&ws, 4, 0, WID_TIME_SEC, 0, 0), "unbounded init");
    CHECK(!wid_async_wid_stream_done(&ws), "unbounded not done");
    char id[WID_MAX_LEN];
    CHECK(wid_async_wid_stream_poll(&ws, id, sizeof(id)), "unbounded poll 1");
    CHECK(wid_async_wid_stream_poll(&ws, id, sizeof(id)), "unbounded poll 2");
    CHECK(!wid_async_wid_stream_done(&ws), "unbounded still not done");

    wid_async_hlc_stream_t hs;
    CHECK(wid_async_hlc_stream_init(&hs, "n1", 4, 0, WID_TIME_SEC, 0, 0), "unbounded hlc");
    CHECK(!wid_async_hlc_stream_done(&hs), "unbounded hlc not done");
    CHECK(wid_async_hlc_stream_poll(&hs, id, sizeof(id)), "unbounded hlc poll");
    CHECK(hlc_wid_validate(id, 4, 0), "unbounded hlc valid");

    /* With interval: first poll immediate, second not yet due */
    CHECK(wid_async_wid_stream_init(&ws, 4, 0, WID_TIME_SEC, 2, 1000), "interval init");
    CHECK(wid_async_wid_stream_poll(&ws, id, sizeof(id)), "interval poll 1");
    CHECK(!wid_async_wid_stream_poll(&ws, id, sizeof(id)), "interval poll 2 blocked");
    CHECK(!wid_async_wid_stream_done(&ws), "interval not done");

    CHECK(wid_async_hlc_stream_init(&hs, "n1", 4, 0, WID_TIME_SEC, 2, 500), "hlc interval init");
    CHECK(wid_async_hlc_stream_poll(&hs, id, sizeof(id)), "hlc interval poll 1");
    CHECK(!wid_async_hlc_stream_poll(&hs, id, sizeof(id)), "hlc interval poll 2 blocked");
}

static void test_generator_sequence_overflow(void) {
    int64_t base = wid_now_tick(WID_TIME_SEC);
    wid_gen_t gen;
    wid_gen_init_ex(&gen, 1, 0, WID_TIME_SEC);
    gen.last_tick = base + 10000;
    char out[WID_MAX_LEN];

    for (int i = 0; i < 10; i++)
        wid_gen_next(&gen, out, sizeof(out));
    wid_gen_next(&gen, out, sizeof(out));
    CHECK(gen.last_tick == base + 10001, "tick rolled after overflow");
    CHECK(gen.last_seq == 0, "seq reset to 0");
}

/* ── Main ────────────────────────────────────────────────────────────── */

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
    test_extreme_tick_saturates();

    test_timestamp_edge_cases();
    test_non_default_w_z();
    test_w_z_out_of_range();
    test_parse_extraction();
    test_hlc_observe_branches();
    test_gen_init_clamping();
    test_null_safety();
    test_more_low_level_helpers();
    test_fmt_tick_more();
    test_async_stream_interval();
    test_generator_sequence_overflow();

    if (g_failures != 0) {
        fprintf(stderr, "\n%d test(s) failed.\n", g_failures);
        return 1;
    }

    puts("all C tests passed");
    return 0;
}
