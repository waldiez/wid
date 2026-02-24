CC ?= cc
CFLAGS = -Wall -Wextra -std=c11 -O2
BUILD_DIR = .build

.PHONY: setup test lint fmt check clean next stream healthcheck bench coverage

setup: $(BUILD_DIR)/wid $(BUILD_DIR)/wid_tests

$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

$(BUILD_DIR)/wid: src/main.c include/wid.h | $(BUILD_DIR)
	$(CC) $(CFLAGS) -I include -o $@ src/main.c

$(BUILD_DIR)/wid_tests: tests/wid_tests.c include/wid.h | $(BUILD_DIR)
	$(CC) $(CFLAGS) -I include -o $@ tests/wid_tests.c

test: $(BUILD_DIR)/wid $(BUILD_DIR)/wid_tests
	$(BUILD_DIR)/wid_tests
	$(BUILD_DIR)/wid selftest

lint:
	$(CC) $(CFLAGS) -Werror -I include -fsyntax-only src/main.c

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
