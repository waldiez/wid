CC ?= cc
CFLAGS = -Wall -Wextra -std=c11 -O2
BUILD_DIR = .build

# OpenSSL libcrypto is used for Ed25519 sign/verify and HMAC-SHA256 (A=sign,
# A=verify, A=w-otp). Resolved via pkg-config when available, else -lcrypto.
CRYPTO_CFLAGS ?= $(shell pkg-config --cflags libcrypto 2>/dev/null)
CRYPTO_LIBS ?= $(shell pkg-config --libs libcrypto 2>/dev/null || echo -lcrypto)

# SQLite (libsqlite3) is used for E=sql generator-state persistence. Resolved
# via pkg-config when available, else -lsqlite3.
SQLITE_CFLAGS ?= $(shell pkg-config --cflags sqlite3 2>/dev/null)
SQLITE_LIBS ?= $(shell pkg-config --libs sqlite3 2>/dev/null || echo -lsqlite3)

.PHONY: setup test lint fmt check clean next stream healthcheck bench coverage sanitize fuzz

setup: $(BUILD_DIR)/wid $(BUILD_DIR)/wid_tests

$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

$(BUILD_DIR)/wid: src/main.c include/wid.h | $(BUILD_DIR)
	$(CC) $(CFLAGS) $(CRYPTO_CFLAGS) $(SQLITE_CFLAGS) -I include -o $@ src/main.c $(CRYPTO_LIBS) $(SQLITE_LIBS)

$(BUILD_DIR)/wid_tests: tests/wid_tests.c include/wid.h | $(BUILD_DIR)
	$(CC) $(CFLAGS) -I include -o $@ tests/wid_tests.c

test: $(BUILD_DIR)/wid $(BUILD_DIR)/wid_tests
	$(BUILD_DIR)/wid_tests
	$(BUILD_DIR)/wid selftest

# Full -Werror compile (not just -fsyntax-only) so warnings that only surface
# during code generation/optimization (e.g. -Wunused-result, -Wmaybe-uninitialized)
# are caught, for both the CLI and the test translation units.
lint: | $(BUILD_DIR)
	$(CC) $(CFLAGS) $(CRYPTO_CFLAGS) $(SQLITE_CFLAGS) -Werror -I include -c src/main.c -o $(BUILD_DIR)/main.lint.o
	$(CC) $(CFLAGS) -Werror -I include -c tests/wid_tests.c -o $(BUILD_DIR)/tests.lint.o

fmt:
	@command -v clang-format >/dev/null 2>&1 && \
		clang-format -i src/main.c include/wid.h tests/wid_tests.c || \
		echo "clang-format not found, skipping"

check: lint test

clean:
	rm -rf $(BUILD_DIR)

next: $(BUILD_DIR)/wid
	$(BUILD_DIR)/wid next

stream: $(BUILD_DIR)/wid
	$(BUILD_DIR)/wid stream --count 11

healthcheck: $(BUILD_DIR)/wid
	$(BUILD_DIR)/wid healthcheck --json

bench: $(BUILD_DIR)/wid
	$(BUILD_DIR)/wid bench --count $(or $(BENCH_N),50000)

coverage: | $(BUILD_DIR)
	$(CC) $(CFLAGS) -I include --coverage -o $(BUILD_DIR)/wid_tests_cov tests/wid_tests.c
	$(BUILD_DIR)/wid_tests_cov
	gcov tests/wid_tests.c

# Memory-safety gates (clang). `sanitize` reruns the unit tests and the CLI
# selftest under ASan+UBSan with recovery disabled, so any UB aborts the run.
# `fuzz` drives the header's untrusted-input parsers (validate/parse, plain
# and HLC) with libFuzzer; FUZZ_SECONDS bounds the run for CI smoke use.
CLANG ?= clang
SAN_FLAGS = -g -O1 -fsanitize=address,undefined -fno-sanitize-recover=all
FUZZ_SECONDS ?= 30

sanitize: | $(BUILD_DIR)
	$(CLANG) $(CFLAGS) $(SAN_FLAGS) -I include -o $(BUILD_DIR)/wid_tests_san tests/wid_tests.c
	$(BUILD_DIR)/wid_tests_san
	$(CLANG) $(CFLAGS) $(SAN_FLAGS) $(CRYPTO_CFLAGS) $(SQLITE_CFLAGS) -I include -o $(BUILD_DIR)/wid_san src/main.c $(CRYPTO_LIBS) $(SQLITE_LIBS)
	$(BUILD_DIR)/wid_san selftest

fuzz: | $(BUILD_DIR)
	$(CLANG) $(CFLAGS) $(SAN_FLAGS) -fsanitize=fuzzer,address,undefined -I include -o $(BUILD_DIR)/fuzz_parse fuzz/fuzz_parse.c
	mkdir -p $(BUILD_DIR)/fuzz-corpus
	printf '20260212T091530.0042Z-a3f91c' > $(BUILD_DIR)/fuzz-corpus/wid_padded
	printf '20260212T091530.0042Z' > $(BUILD_DIR)/fuzz-corpus/wid_plain
	printf '20260212T091530123.0042Z-node01-a3f91c' > $(BUILD_DIR)/fuzz-corpus/hlc_ms_padded
	printf '20260212T091530.999999999999999999Z' > $(BUILD_DIR)/fuzz-corpus/wid_w18
	$(BUILD_DIR)/fuzz_parse -max_total_time=$(FUZZ_SECONDS) -max_len=512 -print_final_stats=1 $(BUILD_DIR)/fuzz-corpus
