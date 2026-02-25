/*
 * wid C CLI
 */

#define _POSIX_C_SOURCE 200809L

#include <ctype.h>
#include <errno.h>
#include <limits.h>
#include <signal.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <time.h>
#include <unistd.h>

#include "wid.h"

#ifndef PATH_MAX
#define PATH_MAX 4096
#endif

typedef struct {
    const char *kind;
    const char *node;
    int W;
    int Z;
    wid_time_unit_t time_unit;
    int count;
    bool json;
} cli_opts_t;

static int cmd_next(const cli_opts_t *o);
static int cmd_stream(const cli_opts_t *o);
static int cmd_healthcheck(const cli_opts_t *o);
static int cmd_parse(const char *id, const cli_opts_t *o);
static int cmd_bench(const cli_opts_t *o);

static void print_help(void) {
    fprintf(stderr,
            "wid - WID/HLC-WID generator CLI\n\n"
            "Usage:\n"
            "  wid next [--kind wid|hlc] [--node <name>] [--W <n>] [--Z <n>] [--time-unit sec|ms]\n"
            "  wid stream [--kind wid|hlc] [--node <name>] [--W <n>] [--Z <n>] [--time-unit sec|ms] [--count <n>]\n"
            "  wid validate <id> [--kind wid|hlc] [--W <n>] [--Z <n>] [--time-unit sec|ms]\n"
            "  wid parse <id> [--kind wid|hlc] [--W <n>] [--Z <n>] [--time-unit sec|ms] [--json]\n"
            "  wid healthcheck [--kind wid|hlc] [--node <name>] [--W <n>] [--Z <n>] [--time-unit sec|ms] [--json]\n"
            "  wid bench [--kind wid|hlc] [--node <name>] [--W <n>] [--Z <n>] [--time-unit sec|ms] [--count <n>]\n"
            "  wid help-actions\n"
            "\n"
            "Canonical mode:\n"
            "  wid W=# A=# L=# D=# I=# E=# Z=# T=sec|ms R=auto|mqtt|ws|redis|null|stdout N=#\n"
            "  For A=stream: N=0 means infinite stream\n"
            "  E supports: state | stateless | sql\n");
}

static void print_actions(void) {
    puts("wid action matrix\n\n"
         "Core ID:\n"
         "  A=next | A=stream | A=healthcheck | A=sign | A=verify | A=w-otp\n\n"
         "Service lifecycle (native):\n"
         "  A=discover | A=scaffold | A=run | A=start | A=stop | A=status | A=logs | A=self.check-update\n\n"
         "Service modules (native):\n"
         "  A=saf      (alias: raf)\n"
         "  A=saf-wid  (aliases: waf, wraf)\n"
         "  A=wir      (alias: witr)\n"
         "  A=wism     (alias: wim)\n"
         "  A=wihp     (alias: wih)\n"
         "  A=wipr     (alias: wip)\n"
         "  A=duplex\n\n"
         "Help:\n"
         "  A=help-actions\n\n"
         "State mode:\n"
         "  E=state | E=stateless | E=sql");
}

static bool parse_int(const char *s, int *out) {
    if (!s || !*s) return false;
    char *end = NULL;
    long v = strtol(s, &end, 10);
    if (!end || *end != '\0') return false;
    if (v < -2147483647L || v > 2147483647L) return false;
    *out = (int)v;
    return true;
}

static bool is_kv_arg(const char *s) {
    return s && strchr(s, '=') != NULL;
}

typedef struct {
    char A[32];
    int W;
    int Z;
    int L;
    int N;
    char T[8];
    char D[256];
    char I[32];
    char E[64];
    char R[32];
    char M[16];
    char WID[512];
    char KEY[PATH_MAX];
    char SIG[1024];
    char DATA[PATH_MAX];
    char OUT[PATH_MAX];
    char MODE[16];
    char CODE[64];
    int DIGITS;
    int MAX_AGE_SEC;
    int MAX_FUTURE_SEC;
} canon_opts_t;

static int run_canonical_sql_next(const canon_opts_t *c, wid_time_unit_t unit);
static int run_canonical_sql_stream(const canon_opts_t *c, wid_time_unit_t unit);
static int run_sign(const canon_opts_t *c);
static int run_verify(const canon_opts_t *c);
static int run_wotp(const canon_opts_t *c, wid_time_unit_t unit);

static bool is_core_action(const char *a) {
    return strcmp(a, "next") == 0 || strcmp(a, "stream") == 0 || strcmp(a, "healthcheck") == 0 ||
           strcmp(a, "help-actions") == 0 || strcmp(a, "sign") == 0 || strcmp(a, "verify") == 0 ||
           strcmp(a, "w-otp") == 0;
}

static bool is_transport(const char *s) {
    return strcmp(s, "mqtt") == 0 || strcmp(s, "ws") == 0 || strcmp(s, "redis") == 0 || strcmp(s, "null") == 0 ||
           strcmp(s, "stdout") == 0 || strcmp(s, "auto") == 0;
}

static bool is_local_service_transport(const char *s) {
    return strcmp(s, "mqtt") == 0 || strcmp(s, "ws") == 0 || strcmp(s, "redis") == 0 || strcmp(s, "null") == 0 ||
           strcmp(s, "stdout") == 0;
}

static bool has_unsafe_shell_char(const char *s) {
    if (!s) return false;
    for (const char *p = s; *p; p++) {
        if (*p == '\'' || *p == '"' || *p == ';' || *p == '&' || *p == '|' || *p == '`' || *p == '\n' ||
            *p == '\r') {
            return true;
        }
    }
    return false;
}

static bool parse_canonical(int argc, char **argv, canon_opts_t *o) {
    strcpy(o->A, "next");
    o->W = 4;
    o->Z = 6;
    o->L = 3600;
    o->N = 0;
    strcpy(o->T, "sec");
    strcpy(o->D, "");
    strcpy(o->I, "auto");
    strcpy(o->E, "state");
    strcpy(o->R, "auto");
    strcpy(o->M, "false");
    o->WID[0] = '\0';
    o->KEY[0] = '\0';
    o->SIG[0] = '\0';
    o->DATA[0] = '\0';
    o->OUT[0] = '\0';
    o->MODE[0] = '\0';
    o->CODE[0] = '\0';
    o->DIGITS = 6;
    o->MAX_AGE_SEC = 0;
    o->MAX_FUTURE_SEC = 5;

    for (int i = 1; i < argc; i++) {
        char *eq = strchr(argv[i], '=');
        if (!eq) return false;
        size_t klen = (size_t)(eq - argv[i]);
        const char *v = eq + 1;

        if (klen == 1 && argv[i][0] == 'A') {
            if (strcmp(v, "#") == 0) v = "next";
            snprintf(o->A, sizeof(o->A), "%s", v);
        } else if (klen == 1 && argv[i][0] == 'W') {
            if (strcmp(v, "#") == 0) v = "4";
            if (!parse_int(v, &o->W)) return false;
        } else if (klen == 1 && argv[i][0] == 'Z') {
            if (strcmp(v, "#") == 0) v = "6";
            if (!parse_int(v, &o->Z)) return false;
        } else if (klen == 1 && argv[i][0] == 'L') {
            if (strcmp(v, "#") == 0) v = "3600";
            if (!parse_int(v, &o->L)) return false;
        } else if (klen == 1 && argv[i][0] == 'N') {
            if (strcmp(v, "#") == 0) v = "0";
            if (!parse_int(v, &o->N)) return false;
        } else if (klen == 1 && argv[i][0] == 'T') {
            if (strcmp(v, "#") == 0) v = "sec";
            snprintf(o->T, sizeof(o->T), "%s", v);
        } else if (klen == 1 && argv[i][0] == 'D') {
            if (strcmp(v, "#") == 0) v = "";
            snprintf(o->D, sizeof(o->D), "%s", v);
        } else if (klen == 1 && argv[i][0] == 'I') {
            if (strcmp(v, "#") == 0) v = "auto";
            snprintf(o->I, sizeof(o->I), "%s", v);
        } else if (klen == 1 && argv[i][0] == 'E') {
            if (strcmp(v, "#") == 0) v = "state";
            snprintf(o->E, sizeof(o->E), "%s", v);
        } else if (klen == 1 && argv[i][0] == 'R') {
            if (strcmp(v, "#") == 0) v = "auto";
            snprintf(o->R, sizeof(o->R), "%s", v);
        } else if (klen == 1 && argv[i][0] == 'M') {
            if (strcmp(v, "#") == 0) v = "false";
            snprintf(o->M, sizeof(o->M), "%s", v);
        } else if (klen == 3 && strncmp(argv[i], "WID", 3) == 0) {
            snprintf(o->WID, sizeof(o->WID), "%s", v);
        } else if (klen == 3 && strncmp(argv[i], "KEY", 3) == 0) {
            snprintf(o->KEY, sizeof(o->KEY), "%s", v);
        } else if (klen == 3 && strncmp(argv[i], "SIG", 3) == 0) {
            snprintf(o->SIG, sizeof(o->SIG), "%s", v);
        } else if (klen == 4 && strncmp(argv[i], "DATA", 4) == 0) {
            snprintf(o->DATA, sizeof(o->DATA), "%s", v);
        } else if (klen == 3 && strncmp(argv[i], "OUT", 3) == 0) {
            snprintf(o->OUT, sizeof(o->OUT), "%s", v);
        } else if (klen == 4 && strncmp(argv[i], "MODE", 4) == 0) {
            snprintf(o->MODE, sizeof(o->MODE), "%s", v);
        } else if (klen == 4 && strncmp(argv[i], "CODE", 4) == 0) {
            snprintf(o->CODE, sizeof(o->CODE), "%s", v);
        } else if (klen == 6 && strncmp(argv[i], "DIGITS", 6) == 0) {
            if (strcmp(v, "#") == 0) v = "6";
            if (!parse_int(v, &o->DIGITS)) return false;
        } else if (klen == 11 && strncmp(argv[i], "MAX_AGE_SEC", 11) == 0) {
            if (strcmp(v, "#") == 0) v = "0";
            if (!parse_int(v, &o->MAX_AGE_SEC)) return false;
        } else if (klen == 14 && strncmp(argv[i], "MAX_FUTURE_SEC", 14) == 0) {
            if (strcmp(v, "#") == 0) v = "5";
            if (!parse_int(v, &o->MAX_FUTURE_SEC)) return false;
        } else {
            return false;
        }
    }

    for (size_t i = 0; o->A[i] != '\0'; i++) o->A[i] = (char)tolower((unsigned char)o->A[i]);

    if (strcmp(o->A, "id") == 0 || strcmp(o->A, "default") == 0) {
        strcpy(o->A, "next");
    } else if (strcmp(o->A, "hc") == 0) {
        strcpy(o->A, "healthcheck");
    } else if (strcmp(o->A, "raf") == 0) {
        strcpy(o->A, "saf");
    } else if (strcmp(o->A, "waf") == 0 || strcmp(o->A, "wraf") == 0) {
        strcpy(o->A, "saf-wid");
    } else if (strcmp(o->A, "witr") == 0) {
        strcpy(o->A, "wir");
    } else if (strcmp(o->A, "wim") == 0) {
        strcpy(o->A, "wism");
    } else if (strcmp(o->A, "wih") == 0) {
        strcpy(o->A, "wihp");
    } else if (strcmp(o->A, "wip") == 0) {
        strcpy(o->A, "wipr");
    }

    if (is_core_action(o->A) && strcmp(o->T, "sec") != 0 && strcmp(o->T, "ms") != 0) {
        fprintf(stderr, "error: T=%s not supported in C implementation (use sec|ms)\n", o->T);
        return false;
    }

    if (has_unsafe_shell_char(o->D) || has_unsafe_shell_char(o->I) || has_unsafe_shell_char(o->E) ||
        has_unsafe_shell_char(o->R) || has_unsafe_shell_char(o->M) || has_unsafe_shell_char(o->A) ||
        has_unsafe_shell_char(o->T) || has_unsafe_shell_char(o->KEY) || has_unsafe_shell_char(o->DATA) ||
        has_unsafe_shell_char(o->OUT) || has_unsafe_shell_char(o->SIG)) {
        fprintf(stderr, "error: unsafe characters in canonical values\n");
        return false;
    }

    if (o->W <= 0 || o->Z < 0 || o->N < 0 || o->L < 0) return false;
    if (o->MAX_AGE_SEC < 0 || o->MAX_FUTURE_SEC < 0) return false;
    if (!is_transport(o->R)) return false;
    return true;
}

static int mkdir_p(const char *path) {
    if (!path || !*path) return -1;
    char tmp[PATH_MAX];
    size_t len = strlen(path);
    if (len >= sizeof(tmp)) return -1;
    strcpy(tmp, path);

    for (char *p = tmp + 1; *p; p++) {
        if (*p == '/') {
            *p = '\0';
            if (mkdir(tmp, 0777) != 0 && errno != EEXIST) return -1;
            *p = '/';
        }
    }
    if (mkdir(tmp, 0777) != 0 && errno != EEXIST) return -1;
    return 0;
}

static void get_data_dir(const canon_opts_t *c, char out[PATH_MAX]) {
    if (c->D[0]) {
        snprintf(out, PATH_MAX, "%s", c->D);
    } else {
        snprintf(out, PATH_MAX, ".local/services");
    }
}

static int join_path(char *out, size_t out_len, const char *left, const char *right) {
    size_t l = strnlen(left, out_len);
    size_t r = strlen(right);
    if (l >= out_len) return -1;
    if (l + r + 1 > out_len) return -1;
    memcpy(out, left, l);
    memcpy(out + l, right, r + 1);
    return 0;
}

static void parse_state_transport(const canon_opts_t *c, char state_mode[64], char effective_transport[32]) {
    snprintf(state_mode, 64, "%s", c->E);
    snprintf(effective_transport, 32, "%s", c->R);

    const char *plus = strchr(c->E, '+');
    const char *comma = strchr(c->E, ',');
    const char *sep = plus ? plus : comma;

    if (sep) {
        size_t left_len = (size_t)(sep - c->E);
        if (left_len >= 64) left_len = 63;
        memcpy(state_mode, c->E, left_len);
        state_mode[left_len] = '\0';

        if (strcmp(effective_transport, "auto") == 0) {
            snprintf(effective_transport, 32, "%s", sep + 1);
        }
    }
}

static int sql_state_path(const canon_opts_t *c, char out[PATH_MAX]) {
    char dd[PATH_MAX];
    get_data_dir(c, dd);
    return join_path(out, PATH_MAX, dd, "/wid_state.sqlite");
}

static int systemf(const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    va_list ap2;
    va_copy(ap2, ap);
    int n = vsnprintf(NULL, 0, fmt, ap);
    va_end(ap);
    if (n < 0) {
        va_end(ap2);
        return -1;
    }
    size_t needed = (size_t)n + 1;
    char *cmd = (char *)malloc(needed);
    if (!cmd) {
        va_end(ap2);
        return -1;
    }
    (void)vsnprintf(cmd, needed, fmt, ap2);
    va_end(ap2);
    int rc = system(cmd);
    free(cmd);
    return rc;
}

static int sqlite_exec_capture(const char *db_path, const char *sql, char *out, size_t out_len) {
    char cmd[8192];
    snprintf(cmd, sizeof(cmd), "sqlite3 -cmd \".timeout 5000\" '%s' \"%s\"", db_path, sql);
    FILE *fp = popen(cmd, "r");
    if (!fp) return -1;
    if (out && out_len > 0) {
        out[0] = '\0';
        if (fgets(out, (int)out_len, fp)) {
            size_t n = strlen(out);
            while (n > 0 && (out[n - 1] == '\n' || out[n - 1] == '\r')) {
                out[n - 1] = '\0';
                n--;
            }
        }
    }
    int rc = pclose(fp);
    return rc == 0 ? 0 : -1;
}

static int sql_load_state(const char *db_path, const char *key, int64_t *tick_out, int64_t *seq_out) {
    char sql[1024];
    char out[256];
    snprintf(sql, sizeof(sql), "SELECT last_tick || '|' || last_seq FROM wid_state WHERE k='%s';", key);
    if (sqlite_exec_capture(db_path, sql, out, sizeof(out)) != 0) return -1;
    long long tick = 0;
    long long seq = -1;
    if (sscanf(out, "%lld|%lld", &tick, &seq) != 2) return -1;
    *tick_out = (int64_t)tick;
    *seq_out = (int64_t)seq;
    return 0;
}

static int sql_ensure_state(const char *db_path, const char *key) {
    char sql[1024];
    snprintf(sql,
             sizeof(sql),
             "CREATE TABLE IF NOT EXISTS wid_state (k TEXT PRIMARY KEY, last_tick INTEGER NOT NULL, last_seq "
             "INTEGER NOT NULL);"
             "INSERT OR IGNORE INTO wid_state(k,last_tick,last_seq) VALUES('%s',0,-1);",
             key);
    return sqlite_exec_capture(db_path, sql, NULL, 0);
}

static int sql_compare_and_swap_state(
    const char *db_path,
    const char *key,
    int64_t old_tick,
    int64_t old_seq,
    int64_t tick,
    int64_t seq
) {
    char sql[2048];
    char out[256];
    snprintf(sql,
             sizeof(sql),
             "UPDATE wid_state SET last_tick=%lld,last_seq=%lld "
             "WHERE k='%s' AND last_tick=%lld AND last_seq=%lld;"
             "SELECT changes();",
             (long long)tick,
             (long long)seq,
             key,
             (long long)old_tick,
             (long long)old_seq);
    if (sqlite_exec_capture(db_path, sql, out, sizeof(out)) != 0) return -1;
    return strcmp(out, "1") == 0 ? 1 : 0;
}

static int sql_allocate_next_wid(
    const canon_opts_t *c,
    wid_time_unit_t unit,
    char out[WID_MAX_LEN]
) {
    char db_path[PATH_MAX];
    if (sql_state_path(c, db_path) != 0) return -1;
    char key[128];
    snprintf(key, sizeof(key), "wid:c:%d:%d:%s", c->W, c->Z, c->T);
    if (sql_ensure_state(db_path, key) != 0) return -1;

    for (int attempt = 0; attempt < 64; attempt++) {
        int64_t last_tick = 0;
        int64_t last_seq = -1;
        if (sql_load_state(db_path, key, &last_tick, &last_seq) != 0) return -1;

        wid_gen_t g;
        wid_gen_init_ex(&g, c->W, c->Z, unit);
        g.last_tick = last_tick;
        g.last_seq = last_seq;
        wid_gen_next(&g, out, WID_MAX_LEN);

        int cas = sql_compare_and_swap_state(db_path, key, last_tick, last_seq, g.last_tick, g.last_seq);
        if (cas < 0) return -1;
        if (cas == 1) return 0;
    }
    return -1;
}

static void runtime_paths(char runtime_dir[PATH_MAX], char pid_file[PATH_MAX], char log_file[PATH_MAX]) {
    snprintf(runtime_dir, PATH_MAX, ".local/wid/c");
    snprintf(pid_file, PATH_MAX, "%s/service.pid", runtime_dir);
    snprintf(log_file, PATH_MAX, "%s/service.log", runtime_dir);
}

static int read_pid_file(const char *pid_file, pid_t *pid_out) {
    FILE *fp = fopen(pid_file, "r");
    if (!fp) return 0;
    long pid = 0;
    int ok = fscanf(fp, "%ld", &pid) == 1;
    fclose(fp);
    if (!ok || pid <= 0) return 0;
    *pid_out = (pid_t)pid;
    return 1;
}

static int pid_alive(pid_t pid) {
    if (pid <= 0) return 0;
    return kill(pid, 0) == 0;
}

static int run_discover(void) {
    puts("{\"impl\":\"c\",\"orchestration\":\"native\","
         "\"actions\":[\"discover\",\"scaffold\",\"run\",\"start\",\"stop\",\"status\",\"logs\",\"saf\",\"saf-wid\",\"wir\",\"wism\",\"wihp\",\"wipr\",\"duplex\",\"self.check-update\"],"
         "\"transports\":[\"auto\",\"mqtt\",\"ws\",\"redis\",\"null\",\"stdout\"]}");
    return 0;
}

static int run_scaffold(const canon_opts_t *c) {
    if (!c->D[0]) {
        fprintf(stderr, "error: D=<name> required for A=scaffold\n");
        return 1;
    }

    char state_dir[PATH_MAX];
    char logs_dir[PATH_MAX];
    snprintf(state_dir, PATH_MAX, "%s/state", c->D);
    snprintf(logs_dir, PATH_MAX, "%s/logs", c->D);

    if (mkdir_p(state_dir) != 0 || mkdir_p(logs_dir) != 0) {
        fprintf(stderr, "error: failed to scaffold '%s'\n", c->D);
        return 1;
    }
    printf("scaffolded %s\n", c->D);
    return 0;
}

static int run_service_loop(const canon_opts_t *c, const char *action) {
    char state_mode[64];
    char transport[32];
    parse_state_transport(c, state_mode, transport);
    if (strcmp(transport, "auto") == 0) {
        snprintf(transport, sizeof(transport), "mqtt");
    }

    if ((strcmp(action, "saf-wid") == 0 || strcmp(action, "wir") == 0 || strcmp(action, "wism") == 0 ||
         strcmp(action, "wihp") == 0 || strcmp(action, "wipr") == 0 || strcmp(action, "duplex") == 0) &&
        !is_local_service_transport(transport)) {
        fprintf(stderr, "error: invalid transport for A=%s: %s\n", action, transport);
        return 1;
    }

    char data_dir[PATH_MAX];
    get_data_dir(c, data_dir);
    if (mkdir_p(data_dir) != 0) {
        fprintf(stderr, "error: failed to create data dir: %s\n", data_dir);
        return 1;
    }

    const char *log_level = getenv("LOG_LEVEL");
    if (!log_level || !*log_level) log_level = "INFO";
    int64_t iter = 0;
    int64_t max_iter = (c->N == 0) ? INT64_MAX : c->N;

    wid_gen_t wg;
    wid_gen_init_ex(&wg, c->W, c->Z, strcmp(c->T, "ms") == 0 ? WID_TIME_MS : WID_TIME_SEC);

    while (iter < max_iter) {
        iter++;
        char wid[WID_MAX_LEN];
        wid_gen_next(&wg, wid, sizeof(wid));

        if (strcmp(transport, "null") != 0) {
            if (strcmp(action, "saf-wid") == 0 || strcmp(action, "wism") == 0 || strcmp(action, "wihp") == 0 ||
                strcmp(action, "wipr") == 0) {
                printf("{\"impl\":\"c\",\"action\":\"%s\",\"tick\":%lld,\"transport\":\"%s\",\"W\":%d,\"Z\":%d,\"time_unit\":\"%s\",\"wid\":\"%s\",\"interval\":%d,\"log_level\":\"%s\",\"data_dir\":\"%s\"}\n",
                       action,
                       (long long)iter,
                       transport,
                       c->W,
                       c->Z,
                       c->T,
                       wid,
                       c->L,
                       log_level,
                       data_dir);
            } else if (strcmp(action, "duplex") == 0) {
                const char *b_transport = "ws";
                if (is_local_service_transport(c->I) && strcmp(c->I, "auto") != 0) b_transport = c->I;
                printf("{\"impl\":\"c\",\"action\":\"duplex\",\"tick\":%lld,\"a_transport\":\"%s\",\"b_transport\":\"%s\",\"interval\":%d,\"data_dir\":\"%s\"}\n",
                       (long long)iter,
                       transport,
                       b_transport,
                       c->L,
                       data_dir);
            } else {
                printf("{\"impl\":\"c\",\"action\":\"%s\",\"tick\":%lld,\"transport\":\"%s\",\"interval\":%d,\"log_level\":\"%s\",\"data_dir\":\"%s\"}\n",
                       action,
                       (long long)iter,
                       transport,
                       c->L,
                       log_level,
                       data_dir);
            }
            fflush(stdout);
        }

        if (iter < max_iter && c->L > 0) sleep((unsigned int)c->L);
    }
    (void)state_mode;
    return 0;
}

static int run_status(void) {
    char runtime_dir[PATH_MAX], pid_file[PATH_MAX], log_file[PATH_MAX];
    runtime_paths(runtime_dir, pid_file, log_file);
    pid_t pid;
    if (read_pid_file(pid_file, &pid) && pid_alive(pid)) {
        printf("wid-c status=running pid=%ld log=%s\n", (long)pid, log_file);
        return 0;
    }
    unlink(pid_file);
    puts("wid-c status=stopped");
    return 0;
}

static int run_logs(void) {
    char runtime_dir[PATH_MAX], pid_file[PATH_MAX], log_file[PATH_MAX];
    runtime_paths(runtime_dir, pid_file, log_file);
    (void)pid_file;
    FILE *fp = fopen(log_file, "r");
    if (!fp) {
        puts("wid-c logs: empty");
        return 0;
    }
    char buf[4096];
    while (fgets(buf, sizeof(buf), fp)) {
        fputs(buf, stdout);
    }
    fclose(fp);
    return 0;
}

static int run_stop(void) {
    char runtime_dir[PATH_MAX], pid_file[PATH_MAX], log_file[PATH_MAX];
    runtime_paths(runtime_dir, pid_file, log_file);
    (void)runtime_dir;
    (void)log_file;
    pid_t pid;
    if (!read_pid_file(pid_file, &pid)) {
        puts("wid-c stop: not running");
        return 0;
    }
    if (!pid_alive(pid)) {
        unlink(pid_file);
        puts("wid-c stop: not running");
        return 0;
    }
    if (kill(pid, SIGTERM) != 0) {
        fprintf(stderr, "error: failed to stop pid=%ld\n", (long)pid);
        return 1;
    }
    unlink(pid_file);
    printf("wid-c stop: stopped pid=%ld\n", (long)pid);
    return 0;
}

static int run_start(const canon_opts_t *c) {
    char runtime_dir[PATH_MAX], pid_file[PATH_MAX], log_file[PATH_MAX];
    runtime_paths(runtime_dir, pid_file, log_file);
    if (mkdir_p(runtime_dir) != 0) {
        fprintf(stderr, "error: failed to create runtime dir\n");
        return 1;
    }

    pid_t existing;
    if (read_pid_file(pid_file, &existing) && pid_alive(existing)) {
        printf("wid-c start: already-running pid=%ld log=%s\n", (long)existing, log_file);
        return 0;
    }

    pid_t pid = fork();
    if (pid < 0) {
        fprintf(stderr, "error: fork failed\n");
        return 1;
    }
    if (pid == 0) {
        setsid();
        FILE *log = fopen(log_file, "a");
        if (!log) _exit(1);
        dup2(fileno(log), STDOUT_FILENO);
        dup2(fileno(log), STDERR_FILENO);
        fclose(log);
        int rc = run_service_loop(c, "run");
        _exit(rc == 0 ? 0 : 1);
    }

    FILE *fp = fopen(pid_file, "w");
    if (!fp) {
        fprintf(stderr, "error: failed to write pid file\n");
        return 1;
    }
    fprintf(fp, "%ld\n", (long)pid);
    fclose(fp);
    printf("wid-c start: started pid=%ld log=%s\n", (long)pid, log_file);
    return 0;
}

static int run_check_update(void) {
    const char *current = "1.0.0";
    char latest[64] = "1.0.0";
    bool update_exists = false;

    FILE *fp = popen("curl -fsSL --max-time 3 https://api.github.com/repos/waldiez/wid/releases/latest 2>/dev/null | grep '\"tag_name\":' | sed -E 's/.*\"([^\"]+)\".*/\\1/' | sed 's/^v//'", "r");
    if (fp) {
        if (fgets(latest, sizeof(latest), fp)) {
            size_t n = strlen(latest);
            while (n > 0 && (latest[n-1] == '\n' || latest[n-1] == '\r')) {
                latest[n-1] = '\0';
                n--;
            }
            if (n > 0 && strcmp(latest, current) != 0) {
                update_exists = true;
            }
        }
        pclose(fp);
    }

    printf("{\"current\":\"%s\",\"latest\":\"%s\",\"update_exists\":%s}\n", 
           current, latest[0] ? latest : current, update_exists ? "true" : "false");
    return 0;
}

static int run_native_orchestration(const canon_opts_t *c) {
    if (strcmp(c->A, "discover") == 0) return run_discover();
    if (strcmp(c->A, "scaffold") == 0) return run_scaffold(c);
    if (strcmp(c->A, "run") == 0) return run_service_loop(c, "run");
    if (strcmp(c->A, "start") == 0) return run_start(c);
    if (strcmp(c->A, "stop") == 0) return run_stop();
    if (strcmp(c->A, "status") == 0) return run_status();
    if (strcmp(c->A, "logs") == 0) return run_logs();
    if (strcmp(c->A, "self.check-update") == 0) return run_check_update();
    if (strcmp(c->A, "saf") == 0) return run_service_loop(c, "saf");
    if (strcmp(c->A, "saf-wid") == 0) return run_service_loop(c, "saf-wid");
    if (strcmp(c->A, "wir") == 0) return run_service_loop(c, "wir");
    if (strcmp(c->A, "wism") == 0) return run_service_loop(c, "wism");
    if (strcmp(c->A, "wihp") == 0) return run_service_loop(c, "wihp");
    if (strcmp(c->A, "wipr") == 0) return run_service_loop(c, "wipr");
    if (strcmp(c->A, "duplex") == 0) return run_service_loop(c, "duplex");
    fprintf(stderr, "error: unknown A=%s\n", c->A);
    return 1;
}

static int build_message_file(const canon_opts_t *c, const char *msg_path) {
    if (!c->WID[0]) {
        fprintf(stderr, "error: WID=<wid_string> required\n");
        return 1;
    }
    FILE *f = fopen(msg_path, "wb");
    if (!f) return 1;
    fwrite(c->WID, 1, strlen(c->WID), f);
    fclose(f);
    if (c->DATA[0]) {
        FILE *in = fopen(c->DATA, "rb");
        if (!in) {
            fprintf(stderr, "error: data file not found: %s\n", c->DATA);
            return 1;
        }
        f = fopen(msg_path, "ab");
        if (!f) {
            fclose(in);
            return 1;
        }
        char buf[4096];
        size_t n;
        while ((n = fread(buf, 1, sizeof(buf), in)) > 0) fwrite(buf, 1, n, f);
        fclose(in);
        fclose(f);
    }
    return 0;
}

static int run_sign(const canon_opts_t *c) {
    if (!c->KEY[0]) {
        fprintf(stderr, "error: KEY=<private_key_path> required for A=sign\n");
        return 1;
    }
    if (access(c->KEY, R_OK) != 0) {
        fprintf(stderr, "error: private key file not found: %s\n", c->KEY);
        return 1;
    }
    mkdir_p(".local/wid/c");
    char msg[PATH_MAX], sig[PATH_MAX], txt[PATH_MAX];
    snprintf(msg, sizeof(msg), ".local/wid/c/sign_msg_%d.bin", (int)getpid());
    snprintf(sig, sizeof(sig), ".local/wid/c/sign_sig_%d.bin", (int)getpid());
    snprintf(txt, sizeof(txt), ".local/wid/c/sign_txt_%d.txt", (int)getpid());
    if (build_message_file(c, msg) != 0) return 1;
    if (systemf("openssl pkeyutl -sign -inkey '%s' -rawin -in '%s' -out '%s' >/dev/null 2>&1", c->KEY, msg, sig) !=
        0) {
        fprintf(stderr, "error: sign failed (ensure Ed25519 private key PEM)\n");
        unlink(msg);
        unlink(sig);
        return 1;
    }
    if (systemf("openssl base64 -A < '%s' | tr '+/' '-_' | tr -d '=' > '%s'", sig, txt) != 0) {
        unlink(msg);
        unlink(sig);
        unlink(txt);
        return 1;
    }
    FILE *f = fopen(txt, "rb");
    if (!f) return 1;
    char out[2048];
    size_t nr = fread(out, 1, sizeof(out) - 1, f);
    fclose(f);
    out[nr] = '\0';
    if (c->OUT[0]) {
        FILE *of = fopen(c->OUT, "wb");
        if (!of) return 1;
        fwrite(out, 1, strlen(out), of);
        fclose(of);
    } else {
        printf("%s\n", out);
    }
    unlink(msg);
    unlink(sig);
    unlink(txt);
    return 0;
}

static int run_verify(const canon_opts_t *c) {
    if (!c->KEY[0]) {
        fprintf(stderr, "error: KEY=<public_key_path> required for A=verify\n");
        return 1;
    }
    if (!c->SIG[0]) {
        fprintf(stderr, "error: SIG=<signature_string> required for A=verify\n");
        return 1;
    }
    if (access(c->KEY, R_OK) != 0) {
        fprintf(stderr, "error: public key file not found: %s\n", c->KEY);
        return 1;
    }
    mkdir_p(".local/wid/c");
    char msg[PATH_MAX], sig64[PATH_MAX], sig[PATH_MAX];
    snprintf(msg, sizeof(msg), ".local/wid/c/verify_msg_%d.bin", (int)getpid());
    snprintf(sig64, sizeof(sig64), ".local/wid/c/verify_sig64_%d.txt", (int)getpid());
    snprintf(sig, sizeof(sig), ".local/wid/c/verify_sig_%d.bin", (int)getpid());
    if (build_message_file(c, msg) != 0) return 1;
    FILE *f = fopen(sig64, "wb");
    if (!f) return 1;
    char std[2048];
    snprintf(std, sizeof(std), "%s", c->SIG);
    for (size_t i = 0; std[i]; i++) {
        if (std[i] == '-') std[i] = '+';
        else if (std[i] == '_') std[i] = '/';
    }
    size_t l = strlen(std);
    if (l % 4 == 2) strcat(std, "==");
    else if (l % 4 == 3) strcat(std, "=");
    else if (l % 4 == 1) {
        fprintf(stderr, "error: invalid base64url signature length\n");
        fclose(f);
        return 1;
    }
    fwrite(std, 1, strlen(std), f);
    fclose(f);
    if (systemf("openssl base64 -A -d -in '%s' -out '%s' >/dev/null 2>&1", sig64, sig) != 0) {
        fprintf(stderr, "error: invalid signature encoding\n");
        unlink(msg);
        unlink(sig64);
        unlink(sig);
        return 1;
    }
    int rc = systemf(
        "openssl pkeyutl -verify -pubin -inkey '%s' -sigfile '%s' -rawin -in '%s' >/dev/null 2>&1",
        c->KEY,
        sig,
        msg
    );
    unlink(msg);
    unlink(sig64);
    unlink(sig);
    if (rc == 0) {
        puts("Signature valid.");
        return 0;
    }
    fprintf(stderr, "Signature invalid.\n");
    return 1;
}

static int resolve_wotp_secret(const char *raw, char *out, size_t out_sz) {
    if (!raw || !*raw) return 1;
    FILE *f = fopen(raw, "rb");
    if (!f) {
        snprintf(out, out_sz, "%s", raw);
        return 0;
    }
    size_t n = fread(out, 1, out_sz - 1, f);
    fclose(f);
    out[n] = '\0';
    while (n > 0 && (out[n - 1] == '\n' || out[n - 1] == '\r' || out[n - 1] == ' ' || out[n - 1] == '\t')) {
        out[--n] = '\0';
    }
    return n == 0 ? 1 : 0;
}

static int compute_wotp(const char *secret, const char *wid, int digits, char *otp_out, size_t otp_sz) {
    if (has_unsafe_shell_char(secret) || has_unsafe_shell_char(wid)) return 1;
    enum {
        WOTP_MAX_SECRET = 512,
        WOTP_MAX_WID = 256
    };
    size_t wid_len = strnlen(wid, WOTP_MAX_WID + 1);
    size_t secret_len = strnlen(secret, WOTP_MAX_SECRET + 1);
    if (wid_len == 0 || wid_len > WOTP_MAX_WID) return 1;
    if (secret_len == 0 || secret_len > WOTP_MAX_SECRET) return 1;
    char wid_safe[WOTP_MAX_WID + 1];
    char secret_safe[WOTP_MAX_SECRET + 1];
    memcpy(wid_safe, wid, wid_len);
    wid_safe[wid_len] = '\0';
    memcpy(secret_safe, secret, secret_len);
    secret_safe[secret_len] = '\0';

    char cmd[PATH_MAX];
    int n = snprintf(cmd,
                     sizeof(cmd),
                     "printf '%%s' '%s' | openssl dgst -sha256 -mac HMAC -macopt 'key:%s' 2>/dev/null",
                     wid_safe,
                     secret_safe);
    if (n < 0 || (size_t)n >= sizeof(cmd)) return 1;
    FILE *p = popen(cmd, "r");
    if (!p) return 1;
    char line[256];
    if (!fgets(line, sizeof(line), p)) {
        pclose(p);
        return 1;
    }
    pclose(p);
    char *eq = strrchr(line, '=');
    char *hex = eq ? eq + 1 : line;
    while (*hex == ' ') hex++;
    char first8[9] = {0};
    for (int i = 0; i < 8; i++) {
        if (!isxdigit((unsigned char)hex[i])) return 1;
        first8[i] = hex[i];
    }
    unsigned long v = strtoul(first8, NULL, 16);
    unsigned long mod = 1;
    for (int i = 0; i < digits; i++) mod *= 10;
    snprintf(otp_out, otp_sz, "%0*lu", digits, v % mod);
    return 0;
}

static int wotp_wid_tick_ms(const char *wid, int64_t *out_ms) {
    int year = 0, month = 0, day = 0, hour = 0, minute = 0, second = 0, millis = 0;
    if (sscanf(wid, "%4d%2d%2dT%2d%2d%2d%3d.", &year, &month, &day, &hour, &minute, &second, &millis) < 6) {
        return -1;
    }
    struct tm tmv;
    memset(&tmv, 0, sizeof(tmv));
    tmv.tm_year = year - 1900;
    tmv.tm_mon = month - 1;
    tmv.tm_mday = day;
    tmv.tm_hour = hour;
    tmv.tm_min = minute;
    tmv.tm_sec = second;
    time_t sec_epoch;
    char *old_tz = getenv("TZ");
    setenv("TZ", "UTC", 1);
    tzset();
    sec_epoch = mktime(&tmv);
    if (old_tz) setenv("TZ", old_tz, 1); else unsetenv("TZ");
    tzset();
    if (sec_epoch < 0) return -1;
    *out_ms = ((int64_t)sec_epoch * 1000) + millis;
    return 0;
}

static int run_wotp(const canon_opts_t *c, wid_time_unit_t unit) {
    char mode[16];
    snprintf(mode, sizeof(mode), "%s", c->MODE[0] ? c->MODE : "gen");
    for (size_t i = 0; mode[i]; i++) mode[i] = (char)tolower((unsigned char)mode[i]);
    if (strcmp(mode, "gen") != 0 && strcmp(mode, "verify") != 0) {
        fprintf(stderr, "error: MODE must be gen or verify for A=w-otp\n");
        return 1;
    }
    if (!c->KEY[0]) {
        fprintf(stderr, "error: KEY=<secret_or_path> required for A=w-otp\n");
        return 1;
    }
    if (c->DIGITS < 4 || c->DIGITS > 10) {
        fprintf(stderr, "error: DIGITS must be between 4 and 10\n");
        return 1;
    }
    if (c->MAX_AGE_SEC < 0) {
        fprintf(stderr, "error: MAX_AGE_SEC must be a non-negative integer\n");
        return 1;
    }
    if (c->MAX_FUTURE_SEC < 0) {
        fprintf(stderr, "error: MAX_FUTURE_SEC must be a non-negative integer\n");
        return 1;
    }
    char secret[PATH_MAX];
    if (resolve_wotp_secret(c->KEY, secret, sizeof(secret)) != 0) {
        fprintf(stderr, "error: w-otp secret cannot be empty\n");
        return 1;
    }
    char widv[WID_MAX_LEN];
    if (c->WID[0]) {
        snprintf(widv, sizeof(widv), "%s", c->WID);
    } else if (strcmp(mode, "gen") == 0) {
        wid_gen_t g;
        wid_gen_init_ex(&g, c->W, c->Z, unit);
        wid_gen_next(&g, widv, sizeof(widv));
    } else {
        fprintf(stderr, "error: WID=<wid_string> required for A=w-otp MODE=verify\n");
        return 1;
    }
    char otp[32];
    if (compute_wotp(secret, widv, c->DIGITS, otp, sizeof(otp)) != 0) {
        fprintf(stderr, "error: failed to compute w-otp digest\n");
        return 1;
    }
    if (strcmp(mode, "gen") == 0) {
        printf("{\"wid\":\"%s\",\"otp\":\"%s\",\"digits\":%d}\n", widv, otp, c->DIGITS);
        return 0;
    }
    if (!c->CODE[0]) {
        fprintf(stderr, "error: CODE=<otp_code> required for A=w-otp MODE=verify\n");
        return 1;
    }
    if (c->MAX_AGE_SEC > 0 || c->MAX_FUTURE_SEC > 0) {
        int64_t wid_ms = 0;
        if (wotp_wid_tick_ms(widv, &wid_ms) != 0) {
            fprintf(stderr, "error: WID timestamp is invalid for time-window verification\n");
            return 1;
        }
        int64_t now_ms = (int64_t)time(NULL) * 1000;
        int64_t delta_ms = now_ms - wid_ms;
        if (delta_ms < 0 && -delta_ms > ((int64_t)c->MAX_FUTURE_SEC * 1000)) {
            fprintf(stderr, "error: OTP invalid: WID timestamp is too far in the future\n");
            return 1;
        }
        if (delta_ms >= 0 && c->MAX_AGE_SEC > 0 && delta_ms > ((int64_t)c->MAX_AGE_SEC * 1000)) {
            fprintf(stderr, "error: OTP invalid: WID timestamp is too old\n");
            return 1;
        }
    }
    if (strcmp(c->CODE, otp) == 0) {
        puts("OTP valid.");
        return 0;
    }
    fprintf(stderr, "OTP invalid.\n");
    return 1;
}

static int run_canonical(const canon_opts_t *c) {
    wid_time_unit_t unit;
    if (!wid_time_unit_from_str(c->T, &unit)) {
        fprintf(stderr, "error: invalid T=%s (expected sec|ms)\n", c->T);
        return 2;
    }

    cli_opts_t o;
    o.kind = "wid";
    o.node = HLC_DEFAULT_NODE;
    o.W = c->W;
    o.Z = c->Z;
    o.time_unit = unit;
    o.count = c->N;
    o.json = true;

    if (strcmp(c->A, "help-actions") == 0) {
        print_actions();
        return 0;
    }
    if (strcmp(c->A, "sign") == 0) return run_sign(c);
    if (strcmp(c->A, "verify") == 0) return run_verify(c);
    if (strcmp(c->A, "w-otp") == 0) return run_wotp(c, unit);

    char state_mode[64];
    char transport[32];
    parse_state_transport(c, state_mode, transport);
    (void)transport;
    if (strcmp(state_mode, "sql") == 0) {
        if (strcmp(c->A, "next") == 0) return run_canonical_sql_next(c, unit);
        if (strcmp(c->A, "stream") == 0) return run_canonical_sql_stream(c, unit);
    }

    if (strcmp(c->A, "next") == 0) return cmd_next(&o);
    if (strcmp(c->A, "stream") == 0) return cmd_stream(&o);
    if (strcmp(c->A, "healthcheck") == 0) return cmd_healthcheck(&o);

    return run_native_orchestration(c);
}

static int run_canonical_sql_next(const canon_opts_t *c, wid_time_unit_t unit) {
    char dd[PATH_MAX];
    get_data_dir(c, dd);
    if (mkdir_p(dd) != 0) {
        fprintf(stderr, "error: failed to create data dir: %s\n", dd);
        return 1;
    }
    char out[WID_MAX_LEN];
    if (sql_allocate_next_wid(c, unit, out) != 0) {
        fprintf(stderr, "error: failed to allocate SQL WID\n");
        return 1;
    }
    puts(out);
    return 0;
}

static int run_canonical_sql_stream(const canon_opts_t *c, wid_time_unit_t unit) {
    char dd[PATH_MAX];
    get_data_dir(c, dd);
    if (mkdir_p(dd) != 0) {
        fprintf(stderr, "error: failed to create data dir: %s\n", dd);
        return 1;
    }
    for (int i = 0; c->N == 0 || i < c->N; i++) {
        char out[WID_MAX_LEN];
        if (sql_allocate_next_wid(c, unit, out) != 0) {
            fprintf(stderr, "error: failed to allocate SQL WID\n");
            return 1;
        }
        puts(out);
    }
    return 0;
}

static bool parse_opts(int argc, char **argv, int start, bool allow_count, cli_opts_t *o) {
    o->kind = "wid";
    o->node = HLC_DEFAULT_NODE;
    o->W = WID_DEFAULT_W;
    o->Z = WID_DEFAULT_Z;
    o->time_unit = WID_TIME_SEC;
    o->count = 0;
    o->json = false;

    for (int i = start; i < argc; i++) {
        if (strcmp(argv[i], "--kind") == 0) {
            if (i + 1 >= argc) return false;
            o->kind = argv[++i];
        } else if (strcmp(argv[i], "--node") == 0) {
            if (i + 1 >= argc) return false;
            o->node = argv[++i];
        } else if (strcmp(argv[i], "--W") == 0) {
            if (i + 1 >= argc || !parse_int(argv[++i], &o->W)) return false;
        } else if (strcmp(argv[i], "--Z") == 0) {
            if (i + 1 >= argc || !parse_int(argv[++i], &o->Z)) return false;
        } else if (strcmp(argv[i], "--time-unit") == 0 || strcmp(argv[i], "--T") == 0) {
            if (i + 1 >= argc) return false;
            if (!wid_time_unit_from_str(argv[++i], &o->time_unit)) return false;
        } else if (allow_count && strcmp(argv[i], "--count") == 0) {
            if (i + 1 >= argc || !parse_int(argv[++i], &o->count)) return false;
        } else if (strcmp(argv[i], "--json") == 0) {
            o->json = true;
        } else {
            return false;
        }
    }

    if (strcmp(o->kind, "wid") != 0 && strcmp(o->kind, "hlc") != 0) return false;
    if (o->W <= 0 || o->Z < 0) return false;
    if (o->W > WID_MAX_W || o->Z > WID_MAX_Z) return false;
    if (o->count < 0) return false;
    if (strcmp(o->kind, "hlc") == 0 && !wid_valid_node(o->node)) return false;
    return true;
}

static int cmd_next(const cli_opts_t *o) {
    char out[WID_MAX_LEN];
    if (strcmp(o->kind, "wid") == 0) {
        wid_gen_t g;
        wid_gen_init_ex(&g, o->W, o->Z, o->time_unit);
        wid_gen_next(&g, out, sizeof(out));
    } else {
        hlc_wid_gen_t g;
        if (!hlc_wid_gen_init_ex(&g, o->node, o->W, o->Z, o->time_unit)) return 1;
        hlc_wid_gen_next(&g, out, sizeof(out));
    }
    puts(out);
    return 0;
}

static int cmd_stream(const cli_opts_t *o) {
    if (strcmp(o->kind, "wid") == 0) {
        wid_gen_t g;
        wid_gen_init_ex(&g, o->W, o->Z, o->time_unit);
        for (int i = 0; o->count == 0 || i < o->count; i++) {
            char out[WID_MAX_LEN];
            wid_gen_next(&g, out, sizeof(out));
            puts(out);
        }
    } else {
        hlc_wid_gen_t g;
        if (!hlc_wid_gen_init_ex(&g, o->node, o->W, o->Z, o->time_unit)) return 1;
        for (int i = 0; o->count == 0 || i < o->count; i++) {
            char out[WID_MAX_LEN];
            hlc_wid_gen_next(&g, out, sizeof(out));
            puts(out);
        }
    }
    return 0;
}

static int cmd_validate(const char *id, const cli_opts_t *o) {
    bool ok = strcmp(o->kind, "wid") == 0
                  ? wid_validate_ex(id, o->W, o->Z, o->time_unit)
                  : hlc_wid_validate_ex(id, o->W, o->Z, o->time_unit);
    puts(ok ? "true" : "false");
    return ok ? 0 : 1;
}

static int cmd_parse(const char *id, const cli_opts_t *o) {
    char ts[32];
    if (strcmp(o->kind, "wid") == 0) {
        parsed_wid_t p;
        if (!wid_parse_ex(id, o->W, o->Z, o->time_unit, &p)) {
            puts("null");
            return 1;
        }
        snprintf(ts, sizeof(ts), "%04d-%02d-%02dT%02d:%02d:%02d+00:00",
                 p.year, p.month, p.day, p.hour, p.minute, p.second);
        if (o->json) {
            printf("{\"raw\":\"%s\",\"timestamp\":\"%s\",\"sequence\":%lld,\"padding\":",
                   p.raw, ts, (long long)p.sequence);
            if (p.has_padding) { printf("\"%s\"", p.padding); } else { printf("null"); }
            printf("}\n");
        } else {
            printf("raw=%s\ntimestamp=%s\nsequence=%lld\npadding=%s\n",
                   p.raw, ts, (long long)p.sequence, p.has_padding ? p.padding : "");
        }
    } else {
        parsed_hlc_wid_t p;
        if (!hlc_wid_parse_ex(id, o->W, o->Z, o->time_unit, &p)) {
            puts("null");
            return 1;
        }
        snprintf(ts, sizeof(ts), "%04d-%02d-%02dT%02d:%02d:%02d+00:00",
                 p.year, p.month, p.day, p.hour, p.minute, p.second);
        if (o->json) {
            printf("{\"raw\":\"%s\",\"timestamp\":\"%s\",\"logical_counter\":%lld,\"node\":\"%s\",\"padding\":",
                   p.raw, ts, (long long)p.logical_counter, p.node);
            if (p.has_padding) { printf("\"%s\"", p.padding); } else { printf("null"); }
            printf("}\n");
        } else {
            printf("raw=%s\ntimestamp=%s\nlogical_counter=%lld\nnode=%s\npadding=%s\n",
                   p.raw, ts, (long long)p.logical_counter, p.node,
                   p.has_padding ? p.padding : "");
        }
    }
    return 0;
}

static int64_t mono_ns(void) {
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

static int cmd_bench(const cli_opts_t *o) {
    const int n = o->count > 0 ? o->count : 100000;
    char out[WID_MAX_LEN];

    int64_t start = mono_ns();
    if (strcmp(o->kind, "wid") == 0) {
        wid_gen_t g;
        wid_gen_init_ex(&g, o->W, o->Z, o->time_unit);
        for (int i = 0; i < n; i++) wid_gen_next(&g, out, sizeof(out));
    } else {
        hlc_wid_gen_t g;
        if (!hlc_wid_gen_init_ex(&g, o->node, o->W, o->Z, o->time_unit)) return 1;
        for (int i = 0; i < n; i++) hlc_wid_gen_next(&g, out, sizeof(out));
    }
    int64_t end = mono_ns();

    double seconds = (double)(end - start) / 1000000000.0;
    if (seconds <= 0.0) seconds = 1e-9;
    double ids_per_sec = (double)n / seconds;

    printf("{\"impl\":\"c\",\"kind\":\"%s\",\"W\":%d,\"Z\":%d,\"time_unit\":\"%s\",\"n\":%d,\"seconds\":%.6f,\"ids_per_sec\":%.2f}\n",
           o->kind,
           o->W,
           o->Z,
           wid_time_unit_to_str(o->time_unit),
           n,
           seconds,
           ids_per_sec);
    return 0;
}

static int cmd_healthcheck(const cli_opts_t *o) {
    char id[WID_MAX_LEN];
    bool ok = false;

    if (strcmp(o->kind, "wid") == 0) {
        wid_gen_t g;
        wid_gen_init_ex(&g, o->W, o->Z, o->time_unit);
        wid_gen_next(&g, id, sizeof(id));
        ok = wid_validate_ex(id, o->W, o->Z, o->time_unit);
    } else {
        hlc_wid_gen_t g;
        if (!hlc_wid_gen_init_ex(&g, o->node, o->W, o->Z, o->time_unit)) return 1;
        hlc_wid_gen_next(&g, id, sizeof(id));
        ok = hlc_wid_validate_ex(id, o->W, o->Z, o->time_unit);
    }

    if (o->json) {
        printf("{\"ok\":%s,\"kind\":\"%s\",\"W\":%d,\"Z\":%d,\"time_unit\":\"%s\",\"sample_id\":\"%s\"}\n",
               ok ? "true" : "false",
               o->kind,
               o->W,
               o->Z,
               wid_time_unit_to_str(o->time_unit),
               id);
    } else {
        printf("ok=%s kind=%s sample=%s\n", ok ? "true" : "false", o->kind, id);
    }
    return ok ? 0 : 1;
}

static int run_selftest(void) {
    wid_gen_t wg;
    wid_gen_init(&wg, 4, 0);

    char a[WID_MAX_LEN], b[WID_MAX_LEN];
    wid_gen_next(&wg, a, sizeof(a));
    wid_gen_next(&wg, b, sizeof(b));
    if (!(strcmp(a, b) < 0)) return 1;
    if (!wid_validate(a, 4, 0)) return 1;

    hlc_wid_gen_t hg;
    if (!hlc_wid_gen_init(&hg, "node01", 4, 0)) return 1;
    char h[WID_MAX_LEN];
    hlc_wid_gen_next(&hg, h, sizeof(h));
    if (!hlc_wid_validate(h, 4, 0)) return 1;

    if (wid_validate("20260212T091530.0000Z-node01", 4, 0)) return 1;
    if (hlc_wid_validate("20260212T091530.0000Z", 4, 0)) return 1;
    if (!wid_validate_ex("20260212T091530123.0000Z", 4, 0, WID_TIME_MS)) return 1;
    if (!hlc_wid_validate_ex("20260212T091530123.0000Z-node01", 4, 0, WID_TIME_MS)) return 1;

    return 0;
}

static void print_completion(const char *shell) {
    if (strcmp(shell, "bash") == 0) {
        printf(
            "_wid_complete() {\n"
            "  local cur=\"${COMP_WORDS[COMP_CWORD]}\"\n"
            "  local cmds=\"next stream healthcheck validate parse help-actions bench selftest completion\"\n"
            "  if [[ \"$cur\" == *=* ]]; then\n"
            "    local key=\"${cur%%%%=*}\" val=\"${cur#*=}\" vals=\"\"\n"
            "    case \"$key\" in\n"
            "      A) vals=\"next stream healthcheck sign verify w-otp discover scaffold run start stop status logs saf saf-wid wir wism wihp wipr duplex help-actions\" ;;\n"
            "      T) vals=\"sec ms\" ;;\n"
            "      I) vals=\"auto sh bash\" ;;\n"
            "      E) vals=\"state stateless sql\" ;;\n"
            "      R) vals=\"auto mqtt ws redis null stdout\" ;;\n"
            "      M) vals=\"true false\" ;;\n"
            "    esac\n"
            "    local IFS=$'\\n'\n"
            "    COMPREPLY=($(for v in $vals; do [[ \"$v\" == \"$val\"* ]] && printf '%%s\\n' \"${key}=${v}\"; done))\n"
            "  else\n"
            "    local kv=\"A= W= Z= T= N= L= D= I= E= R= M=\"\n"
            "    COMPREPLY=($(compgen -W \"$cmds $kv\" -- \"$cur\"))\n"
            "  fi\n"
            "}\n"
            "complete -o nospace -F _wid_complete wid\n"
        );
    } else if (strcmp(shell, "zsh") == 0) {
        printf(
            "#compdef wid\n"
            "_wid_complete() {\n"
            "  local cur=\"${words[-1]}\"\n"
            "  local -a cmds=(next stream healthcheck validate parse help-actions bench selftest completion)\n"
            "  if [[ \"$cur\" == *=* ]]; then\n"
            "    local key=\"${cur%%%%=*}\"\n"
            "    local -a vals=()\n"
            "    case \"$key\" in\n"
            "      A) vals=(next stream healthcheck sign verify w-otp discover scaffold run start stop status logs saf saf-wid wir wism wihp wipr duplex help-actions) ;;\n"
            "      T) vals=(sec ms) ;;\n"
            "      I) vals=(auto sh bash) ;;\n"
            "      E) vals=(state stateless sql) ;;\n"
            "      R) vals=(auto mqtt ws redis null stdout) ;;\n"
            "      M) vals=(true false) ;;\n"
            "    esac\n"
            "    compadd -P \"${key}=\" -- \"${vals[@]}\"\n"
            "  else\n"
            "    compadd -- \"${cmds[@]}\" A= W= Z= T= N= L= D= I= E= R= M=\n"
            "  fi\n"
            "}\n"
            "_wid_complete \"$@\"\n"
        );
    } else if (strcmp(shell, "fish") == 0) {
        printf(
            "complete -c wid -e\n"
            "complete -c wid -f -n 'not __fish_seen_subcommand_from next stream healthcheck validate parse help-actions bench selftest completion' -a next -d 'Emit one WID'\n"
            "complete -c wid -f -n 'not __fish_seen_subcommand_from next stream healthcheck validate parse help-actions bench selftest completion' -a stream -d 'Stream WIDs continuously'\n"
            "complete -c wid -f -n 'not __fish_seen_subcommand_from next stream healthcheck validate parse help-actions bench selftest completion' -a healthcheck -d 'Generate and validate a sample WID'\n"
            "complete -c wid -f -n 'not __fish_seen_subcommand_from next stream healthcheck validate parse help-actions bench selftest completion' -a validate -d 'Validate a WID string'\n"
            "complete -c wid -f -n 'not __fish_seen_subcommand_from next stream healthcheck validate parse help-actions bench selftest completion' -a parse -d 'Parse a WID string'\n"
            "complete -c wid -f -n 'not __fish_seen_subcommand_from next stream healthcheck validate parse help-actions bench selftest completion' -a help-actions -d 'Show canonical action matrix'\n"
            "complete -c wid -f -n 'not __fish_seen_subcommand_from next stream healthcheck validate parse help-actions bench selftest completion' -a completion -d 'Print shell completion script'\n"
            "complete -c wid -f -a 'A=next A=stream A=healthcheck A=sign A=verify A=w-otp A=start A=stop A=status A=logs A=help-actions' -d 'Action'\n"
            "complete -c wid -f -a 'T=sec T=ms' -d 'Time unit'\n"
            "complete -c wid -f -a 'I=auto I=sh I=bash' -d 'Input source'\n"
            "complete -c wid -f -a 'E=state E=stateless E=sql' -d 'State mode'\n"
            "complete -c wid -f -a 'R=auto R=mqtt R=ws R=redis R=null R=stdout' -d 'Transport'\n"
            "complete -c wid -f -a 'M=true M=false' -d 'Milliseconds mode'\n"
            "complete -c wid -f -a 'W=' -d 'Sequence width'\n"
            "complete -c wid -f -a 'Z=' -d 'Padding length'\n"
            "complete -c wid -f -a 'N=' -d 'Count'\n"
            "complete -c wid -f -a 'L=' -d 'Interval seconds'\n"
        );
    } else {
        fprintf(stderr, "error: unknown shell '%s'. Use: wid completion bash|zsh|fish\n", shell);
        exit(1);
    }
}

int main(int argc, char **argv) {
    srand((unsigned int)time(NULL));

    if (argc > 1 && is_kv_arg(argv[1])) {
        canon_opts_t c;
        if (!parse_canonical(argc, argv, &c)) return 2;
        return run_canonical(&c);
    }

    if (argc == 1 || strcmp(argv[1], "help") == 0 || strcmp(argv[1], "-h") == 0 ||
        strcmp(argv[1], "--help") == 0) {
        print_help();
        return argc == 1 ? 2 : 0;
    }

    if (strcmp(argv[1], "help-actions") == 0) {
        print_actions();
        return 0;
    }

    if (strcmp(argv[1], "selftest") == 0) return run_selftest();

    if (strcmp(argv[1], "completion") == 0) {
        if (argc < 3) {
            fprintf(stderr, "usage: wid completion bash|zsh|fish\n");
            return 1;
        }
        print_completion(argv[2]);
        return 0;
    }

    cli_opts_t opts;

    if (strcmp(argv[1], "next") == 0) {
        if (!parse_opts(argc, argv, 2, false, &opts)) {
            fprintf(stderr, "error: invalid arguments\n");
            return 1;
        }
        return cmd_next(&opts);
    }

    if (strcmp(argv[1], "stream") == 0) {
        if (!parse_opts(argc, argv, 2, true, &opts)) {
            fprintf(stderr, "error: invalid arguments\n");
            return 1;
        }
        return cmd_stream(&opts);
    }

    if (strcmp(argv[1], "validate") == 0) {
        if (argc < 3) {
            fprintf(stderr, "error: validate requires an id\n");
            return 1;
        }
        if (!parse_opts(argc, argv, 3, false, &opts)) {
            fprintf(stderr, "error: invalid arguments\n");
            return 1;
        }
        return cmd_validate(argv[2], &opts);
    }

    if (strcmp(argv[1], "parse") == 0) {
        if (argc < 3) {
            fprintf(stderr, "error: parse requires an id\n");
            return 1;
        }
        if (!parse_opts(argc, argv, 3, false, &opts)) {
            fprintf(stderr, "error: invalid arguments\n");
            return 1;
        }
        return cmd_parse(argv[2], &opts);
    }

    if (strcmp(argv[1], "healthcheck") == 0) {
        if (!parse_opts(argc, argv, 2, false, &opts)) {
            fprintf(stderr, "error: invalid arguments\n");
            return 1;
        }
        return cmd_healthcheck(&opts);
    }

    if (strcmp(argv[1], "bench") == 0) {
        if (!parse_opts(argc, argv, 2, true, &opts)) {
            fprintf(stderr, "error: invalid arguments\n");
            return 1;
        }
        return cmd_bench(&opts);
    }

    fprintf(stderr, "error: unknown command: %s\n", argv[1]);
    return 2;
}
