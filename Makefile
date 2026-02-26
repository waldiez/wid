.PHONY: all setup test check clean lint fmt \
       rust-setup rust-test rust-check rust-clean rust-lint rust-bench rust-next \
       python-setup python-test python-check python-clean python-lint python-fmt python-typecheck python-next python-uninstall \
       c-setup c-test c-check c-clean c-lint c-bench c-next \
       ts-setup ts-test ts-check ts-clean ts-lint ts-build ts-bench ts-next \
       go-setup go-test go-check go-clean go-lint go-bench go-next \
       sh-test sh-next \
       next id stream do healthcheck start stop status sign verify otp otp-gen otp-verify crypto-demo \
       mobile-arcade-fix-links mobile-arcade-zip \
       conformance bench-matrix docker capabilities-check stream-conformance crypto-smoke signed-envelope-check security-matrix-check key-rotation-drill-check soak-check envelope-compat-check release-check \
       wotp-parity-check \
       hardening-check

.DEFAULT_GOAL := help

LANGS = rust python c ts go sh

# ─── Aggregate targets ───────────────────────────────────────────────

help:
	@echo "WID Make Targets"
	@echo ""
	@echo "Default:"
	@echo "  make                     # shows this help"
	@echo "  make all                 # runs: setup + check"
	@echo ""
	@echo "Main:"
	@echo "  make install             # install/build dependencies (alias: setup)"
	@echo "  make setup               # build/install prerequisites for all implementations"
	@echo "  make test                # run all test suites"
	@echo "  make check               # run all check suites (lint/type/test by language)"
	@echo "  make quick-check         # small cross-language gate + CLI smoke"
	@echo "  make doctor              # verify required toolchain on PATH"
	@echo "  make clean               # clean build artifacts"
	@echo ""
	@echo "Quick CLI:"
	@echo "  make next                # one ID via sh/wid canonical mode"
	@echo "  make id                  # alias for make next"
	@echo "  make stream              # stream IDs (set N=<count>, N=0 infinite)"
	@echo "  make do                  # infinite stream alias (N=0)"
	@echo "  make healthcheck         # canonical healthcheck JSON"
	@echo "  make start               # start canonical service daemon (A=start)"
	@echo "  make status              # service daemon status (A=status)"
	@echo "  make stop                # stop canonical service daemon (A=stop)"
	@echo "  make sign                # sign WID (KEY=<priv.pem> [WID=<id>] [DATA=<path>])"
	@echo "  make verify              # verify signature (KEY=<pub.pem> SIG=<sig> WID=<id>)"
	@echo "  make otp                 # alias for make otp-gen"
	@echo "  make otp-gen             # generate WID-bound OTP"
	@echo "  make otp-verify          # verify WID-bound OTP"
	@echo "  make crypto-demo         # end-to-end sign/verify + OTP demo"
	@echo "  make mobile-arcade-fix-links # patch web demo links in flutter web bundle"
	@echo "  make mobile-arcade-zip   # patch links + package build/pages/mobile-arcade"
	@echo ""
	@echo "QA:"
	@echo "  make release-check       # capabilities + stream-conformance + check"
	@echo "  make hardening-check     # release-check + strict crypto + path/package/SQL spot checks"
	@echo "  make capabilities-check"
	@echo "  make stream-conformance"
	@echo "  make signed-envelope-check"
	@echo "  make security-matrix-check"
	@echo "  make key-rotation-drill-check"
	@echo "  make envelope-compat-check"
	@echo "  make soak-check"
	@echo "  make crypto-smoke"
	@echo "  make wotp-parity-check   # cross-language w-otp parity gate"
	@echo ""
	@echo "Bench:"
	@echo "  make bench-matrix        # runs benches across implementations"
	@echo "  BENCH_N=200000 make rust-bench go-bench ts-bench c-bench"
	@echo ""
	@echo "Docker:"
	@echo "  make docker              # build Docker image (Rust)"

all: setup check

install: setup

setup: $(addsuffix -setup,$(LANGS))

test: $(addsuffix -test,$(LANGS))

check: $(addsuffix -check,$(LANGS))

clean: $(addsuffix -clean,$(LANGS))

lint: rust-lint python-lint c-lint ts-lint go-lint

fmt: python-fmt

quick-check: python-test ts-check go-test next

doctor:
	@tools="bash python3 cargo node npm go"; \
	for tool in $$tools; do \
		command -v $$tool >/dev/null 2>&1 || { \
			echo "doctor: $$tool not found on PATH" >&2; \
			exit 1; \
		}; \
	done; \
	echo "doctor: required tooling available"

bench-matrix: rust-bench c-bench ts-bench go-bench

# ─── Rust ─────────────────────────────────────────────────────────────

rust-setup:
	cargo build

rust-test:
	cargo test

rust-lint:
	cargo clippy -- -D warnings

rust-check: rust-lint rust-test

rust-clean:
	cargo clean

rust-bench:
	cargo run --release -- bench --count $(or $(BENCH_N),100000)

rust-next:
	cargo run --release -- next

# ─── Python ───────────────────────────────────────────────────────────

PYTHON_ ?= python3
PYTHONPATH_LOCAL = PYTHONPATH=python
PYTHON ?= $(PYTHONPATH_LOCAL) $(PYTHON_)

PIP ?= $(PYTHON) -m pip

python-setup:
	$(PIP) install -e ".[dev]"

python-test:
	$(PYTHON) -m pytest python/tests -v

python-lint:
	$(PYTHON) -m ruff check python/

python-fmt:
	$(PYTHON) -m black python/
	$(PYTHON) -m ruff format python/

python-typecheck:
	$(PYTHON) -m mypy python/wid/

python-check: python-lint python-typecheck python-test

python-clean:
	find python -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf .mypy_cache .ruff_cache .coverage htmlcov

python-next:
	$(PYTHON) -m wid next

python-uninstall:
	@echo "Before uninstall:"
	@command -v wid || true
	-$(PYTHON) -m pip uninstall -y wid wid-py 2>/dev/null || true
	-$(PIP) uninstall -y wid wid-py 2>/dev/null || true
	@hash -r 2>/dev/null || true
	@echo "After uninstall:"
	@command -v wid || true

uninstall: python-uninstall

# ─── C ────────────────────────────────────────────────────────────────

c-setup:
	$(MAKE) -C c setup

c-test:
	$(MAKE) -C c test

c-lint:
	$(MAKE) -C c lint

c-check:
	$(MAKE) -C c check

c-clean:
	$(MAKE) -C c clean

c-bench:
	$(MAKE) -C c bench BENCH_N=$(or $(BENCH_N),50000)

c-next:
	$(MAKE) -C c next

# ─── TypeScript ───────────────────────────────────────────────────────

ts-setup:
	npm install
	@if [ "$$(uname -s)" = "Linux" ]; then \
		if [ "$$(uname -m)" = "aarch64" ]; then \
			npm i --no-save @rollup/rollup-linux-arm64-gnu 2>/dev/null || true; \
		elif [ "$$(uname -m)" = "x86_64" ]; then \
			npm i --no-save @rollup/rollup-linux-x64-gnu 2>/dev/null || true; \
		fi; \
	fi
	npm run build

ts-test:
	npm test

ts-lint:
	npm run lint

ts-build:
	npm run build

ts-check: ts-lint ts-test

ts-clean:
	rm -rf node_modules typescript/dist

ts-bench:
	node typescript/dist/cli.js bench --count $(or $(BENCH_N),50000)

ts-next:
	node typescript/dist/cli.js next

# ─── Go ───────────────────────────────────────────────────────────────

go-setup:
	cd go && go build ./...

go-test:
	cd go && go test -v ./...

go-lint:
	@command -v golangci-lint >/dev/null 2>&1 && \
		cd go && golangci-lint run || \
		cd go && go vet ./...

go-check: go-lint go-test

go-clean:
	rm -f go/cmd/wid/wid

go-bench:
	cd go && go run ./cmd/wid bench --count $(or $(BENCH_N),100000)

go-next:
	cd go && go run ./cmd/wid next

# ─── Shell ────────────────────────────────────────────────────────────

sh-setup:
	@true

sh-test:
	bash sh/wid selftest

sh-check: sh-test

sh-clean:
	@true

sh-next:
	bash sh/wid next

# ─── Quick CLI Wrappers (sh/wid) ─────────────────────────────────────

W ?= 4
Z ?= 6
T ?= sec
N ?= 10
D ?=
E ?= state
R ?= auto
I ?= auto
DIGITS ?= 6
MAX_AGE_SEC ?= 300
MAX_FUTURE_SEC ?= 5
MODE ?= gen

next:
	bash sh/wid A=next W=$(W) Z=$(Z) T=$(T)

id: next

stream:
	bash sh/wid A=stream W=$(W) Z=$(Z) T=$(T) N=$(N) L=0

do:
	bash sh/wid A=stream W=$(W) Z=$(Z) T=$(T) N=0 L=0

healthcheck:
	bash sh/wid A=healthcheck W=$(W) Z=$(Z) T=$(T)

start:
	bash sh/wid A=start W=$(W) Z=$(Z) T=$(T) N=$(N) D="$(D)" E="$(E)" R="$(R)" I="$(I)"

status:
	bash sh/wid A=status

stop:
	bash sh/wid A=stop

sign:
	@if [ -z "$(KEY)" ]; then echo "KEY=<private_key_path> is required"; exit 2; fi
	@wid_val="$(WID)"; \
	if [ -z "$$wid_val" ]; then wid_val="$$(bash sh/wid A=next W=$(W) Z=$(Z) T=$(T))"; fi; \
	if [ -n "$(DATA)" ]; then \
		bash sh/wid A=sign KEY="$(KEY)" WID="$$wid_val" DATA="$(DATA)" $(if $(OUT),OUT="$(OUT)"); \
	else \
		bash sh/wid A=sign KEY="$(KEY)" WID="$$wid_val" $(if $(OUT),OUT="$(OUT)"); \
	fi

verify:
	@if [ -z "$(KEY)" ]; then echo "KEY=<public_key_path> is required"; exit 2; fi
	@if [ -z "$(SIG)" ]; then echo "SIG=<signature> is required"; exit 2; fi
	@if [ -z "$(WID)" ]; then echo "WID=<wid_string> is required"; exit 2; fi
	@if [ -n "$(DATA)" ]; then \
		bash sh/wid A=verify KEY="$(KEY)" SIG="$(SIG)" WID="$(WID)" DATA="$(DATA)"; \
	else \
		bash sh/wid A=verify KEY="$(KEY)" SIG="$(SIG)" WID="$(WID)"; \
	fi

otp-gen:
	@if [ -z "$(KEY)" ]; then echo "KEY=<secret_or_path> is required"; exit 2; fi
	@wid_val="$(WID)"; \
	if [ -z "$$wid_val" ]; then wid_val="$$(bash sh/wid A=next W=$(W) Z=$(Z) T=$(T))"; fi; \
	bash sh/wid A=w-otp MODE=gen KEY="$(KEY)" WID="$$wid_val" DIGITS="$(DIGITS)"

otp: otp-gen

otp-verify:
	@if [ -z "$(KEY)" ]; then echo "KEY=<secret_or_path> is required"; exit 2; fi
	@if [ -z "$(WID)" ]; then echo "WID=<wid_string> is required"; exit 2; fi
	@if [ -z "$(CODE)" ]; then echo "CODE=<otp_code> is required"; exit 2; fi
	bash sh/wid A=w-otp MODE=verify KEY="$(KEY)" WID="$(WID)" CODE="$(CODE)" DIGITS="$(DIGITS)" MAX_AGE_SEC="$(MAX_AGE_SEC)" MAX_FUTURE_SEC="$(MAX_FUTURE_SEC)"

crypto-demo:
	@mkdir -p .local/crypto-demo
	@PRIV=.local/crypto-demo/ed25519_priv.pem; \
	PUB=.local/crypto-demo/ed25519_pub.pem; \
	DATA=.local/crypto-demo/data.txt; \
	printf 'wid crypto demo data\n' > $$DATA; \
	if [ ! -f "$$PRIV" ]; then openssl genpkey -algorithm Ed25519 -out $$PRIV >/dev/null 2>&1; fi; \
	openssl pkey -in $$PRIV -pubout -out $$PUB >/dev/null 2>&1; \
	WID_VAL="$$(bash sh/wid A=next W=$(W) Z=$(Z) T=$(T))"; \
	SIG_VAL="$$(bash sh/wid A=sign KEY=$$PRIV WID=$$WID_VAL DATA=$$DATA)"; \
	echo "wid=$$WID_VAL"; \
	echo "sig=$$SIG_VAL"; \
	bash sh/wid A=verify KEY=$$PUB WID=$$WID_VAL SIG=$$SIG_VAL DATA=$$DATA; \
	OTP_JSON="$$(bash sh/wid A=w-otp MODE=gen KEY='demo-secret' WID=$$WID_VAL DIGITS=$(DIGITS))"; \
	OTP_CODE="$$(printf '%s\n' "$$OTP_JSON" | sed -nE 's/.*\"otp\":\"([0-9]+)\".*/\1/p')"; \
	echo "$$OTP_JSON"; \
	bash sh/wid A=w-otp MODE=verify KEY='demo-secret' WID=$$WID_VAL CODE=$$OTP_CODE DIGITS=$(DIGITS)

mobile-arcade-fix-links:
	bash tools/patch_mobile_arcade_links.sh

mobile-arcade-zip: mobile-arcade-fix-links
	@mkdir -p dist
	@cd build/pages && zip -r ../../dist/mobile-arcade-web-$(shell date +%Y%m%d).zip mobile-arcade

# ─── Cross-cutting ───────────────────────────────────────────────────

conformance:
	$(PYTHON) -m pytest python/tests -v -k conformance

docker:
	docker build -t wid .

capabilities-check:
	python3 tools/check_capabilities.py

stream-conformance:
	python3 tools/check_stream_conformance.py

signed-envelope-check:
	python3 tools/check_signed_envelope_spec.py

security-matrix-check:
	python3 tools/check_security_matrix.py

key-rotation-drill-check:
	python3 tools/check_key_rotation_drill.py

envelope-compat-check:
	python3 tools/check_envelope_compat.py

soak-check:
	python3 tools/soak_stream_sql.py --duration-sec $(or $(SOAK_SECONDS),30) --workers $(or $(SOAK_WORKERS),4)

crypto-smoke:
	bash tools/smoke_crypto.sh

wotp-parity-check:
	bash tools/check_wotp_parity.sh

release-check: capabilities-check stream-conformance check
	npm run typecheck

hardening-check:
	bash tools/hardening_check.sh
