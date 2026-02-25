package main

import (
	"crypto/ed25519"
	"crypto/hmac"
	"crypto/sha256"
	"crypto/subtle"
	"crypto/x509"
	"encoding/base64"
	"encoding/json"
	"encoding/pem"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"time"

	wid "github.com/waldiez/wid/go"
)

type opts struct {
	kind     string
	node     string
	w        int
	z        int
	timeUnit wid.TimeUnit
	count    int
	json     bool
}

type canon struct {
	a            string
	w            int
	l            int
	d            string
	i            string
	e            string
	z            int
	t            wid.TimeUnit
	r            string
	m            bool
	n            int
	wid          string
	key          string
	sig          string
	data         string
	out          string
	mode         string
	code         string
	digits       int
	maxAgeSec    int
	maxFutureSec int
}

var localServiceTransports = map[string]bool{
	"mqtt": true, "ws": true, "redis": true, "null": true, "stdout": true,
}

func main() {
	args := os.Args[1:]
	if len(args) == 0 {
		printHelp()
		os.Exit(2)
	}

	if args[0] == "__daemon" {
		exit(runCanonical(args[1:]))
		return
	}

	if hasKVArg(args) {
		exit(runCanonical(args))
		return
	}

	switch args[0] {
	case "-h", "--help", "help":
		printHelp()
		return
	case "help-actions":
		printActions()
		return
	case "selftest":
		exit(runSelftest())
		return
	case "completion":
		if len(args) < 2 {
			fmt.Fprintln(os.Stderr, "usage: wid completion bash|zsh|fish")
			os.Exit(1)
		}
		printCompletion(args[1])
		return
	case "next":
		o, err := parseOpts(args[1:], false)
		if err != nil {
			errln(err.Error())
			os.Exit(1)
		}
		exit(cmdNext(o))
	case "stream":
		o, err := parseOpts(args[1:], true)
		if err != nil {
			errln(err.Error())
			os.Exit(1)
		}
		exit(cmdStream(o))
	case "validate":
		if len(args) < 2 {
			errln("validate requires an id")
			os.Exit(1)
		}
		o, err := parseOpts(args[2:], false)
		if err != nil {
			errln(err.Error())
			os.Exit(1)
		}
		exit(cmdValidate(args[1], o))
	case "parse":
		if len(args) < 2 {
			errln("parse requires an id")
			os.Exit(1)
		}
		o, err := parseOpts(args[2:], false)
		if err != nil {
			errln(err.Error())
			os.Exit(1)
		}
		exit(cmdParse(args[1], o))
	case "healthcheck":
		o, err := parseOpts(args[1:], false)
		if err != nil {
			errln(err.Error())
			os.Exit(1)
		}
		exit(cmdHealthcheck(o))
	case "bench":
		o, err := parseOpts(args[1:], true)
		if err != nil {
			errln(err.Error())
			os.Exit(1)
		}
		exit(cmdBench(o))
	default:
		errln("unknown command: " + args[0])
		os.Exit(2)
	}
}

func hasKVArg(args []string) bool {
	for _, a := range args {
		if strings.Contains(a, "=") {
			return true
		}
	}
	return false
}

func parseOpts(args []string, allowCount bool) (opts, error) {
	o := opts{
		kind:     "wid",
		node:     "go",
		w:        4,
		z:        6,
		timeUnit: wid.TimeUnitSec,
		count:    0,
		json:     false,
	}
	for i := 0; i < len(args); i++ {
		switch args[i] {
		case "--kind":
			if i+1 >= len(args) {
				return o, errors.New("missing value for --kind")
			}
			o.kind = args[i+1]
			i++
		case "--node":
			if i+1 >= len(args) {
				return o, errors.New("missing value for --node")
			}
			o.node = args[i+1]
			i++
		case "--W":
			if i+1 >= len(args) {
				return o, errors.New("missing value for --W")
			}
			n, err := strconv.Atoi(args[i+1])
			if err != nil {
				return o, errors.New("invalid integer for --W")
			}
			o.w = n
			i++
		case "--Z":
			if i+1 >= len(args) {
				return o, errors.New("missing value for --Z")
			}
			n, err := strconv.Atoi(args[i+1])
			if err != nil {
				return o, errors.New("invalid integer for --Z")
			}
			o.z = n
			i++
		case "--time-unit", "--T":
			if i+1 >= len(args) {
				return o, errors.New("missing value for --time-unit")
			}
			u, err := wid.ParseTimeUnit(args[i+1])
			if err != nil {
				return o, err
			}
			o.timeUnit = u
			i++
		case "--count":
			if !allowCount {
				return o, errors.New("unknown flag: --count")
			}
			if i+1 >= len(args) {
				return o, errors.New("missing value for --count")
			}
			n, err := strconv.Atoi(args[i+1])
			if err != nil {
				return o, errors.New("invalid integer for --count")
			}
			o.count = n
			i++
		case "--json":
			o.json = true
		default:
			return o, fmt.Errorf("unknown flag: %s", args[i])
		}
	}
	if o.kind != "wid" && o.kind != "hlc" {
		return o, errors.New("--kind must be one of: wid, hlc")
	}
	if o.w <= 0 {
		return o, errors.New("W must be > 0")
	}
	if o.z < 0 || o.count < 0 {
		return o, errors.New("Z/count must be >= 0")
	}
	if o.kind == "hlc" && !wid.IsValidNode(o.node) {
		return o, errors.New("invalid node")
	}
	return o, nil
}

func cmdNext(o opts) int {
	if o.kind == "wid" {
		g, err := wid.NewWidGenWithUnit(o.w, o.z, o.timeUnit)
		if err != nil {
			errln(err.Error())
			return 1
		}
		fmt.Println(g.Next())
		return 0
	}
	g, err := wid.NewHLCWidGenWithUnit(o.node, o.w, o.z, o.timeUnit)
	if err != nil {
		errln(err.Error())
		return 1
	}
	fmt.Println(g.Next())
	return 0
}

func cmdStream(o opts) int {
	if o.kind == "wid" {
		g, err := wid.NewWidGenWithUnit(o.w, o.z, o.timeUnit)
		if err != nil {
			errln(err.Error())
			return 1
		}
		for i := 0; o.count == 0 || i < o.count; i++ {
			fmt.Println(g.Next())
		}
		return 0
	}
	g, err := wid.NewHLCWidGenWithUnit(o.node, o.w, o.z, o.timeUnit)
	if err != nil {
		errln(err.Error())
		return 1
	}
	for i := 0; o.count == 0 || i < o.count; i++ {
		fmt.Println(g.Next())
	}
	return 0
}

func cmdValidate(id string, o opts) int {
	ok := false
	if o.kind == "wid" {
		ok = wid.ValidateWidWithUnit(id, o.w, o.z, o.timeUnit)
	} else {
		ok = wid.ValidateHlcWidWithUnit(id, o.w, o.z, o.timeUnit)
	}
	if ok {
		fmt.Println("true")
		return 0
	}
	fmt.Println("false")
	return 1
}

func cmdParse(id string, o opts) int {
	padStr := func(p *string) string {
		if p == nil {
			return ""
		}
		return *p
	}
	if o.kind == "wid" {
		p, err := wid.ParseWidWithUnit(id, o.w, o.z, o.timeUnit)
		if err != nil {
			fmt.Println("null")
			return 1
		}
		ts := p.Timestamp.UTC().Format(time.RFC3339)
		if o.json {
			payload := map[string]any{
				"raw":       p.Raw,
				"timestamp": ts,
				"sequence":  p.Sequence,
				"padding":   p.Padding,
			}
			b, _ := json.Marshal(payload)
			fmt.Println(string(b))
		} else {
			fmt.Printf("raw=%s\n", p.Raw)
			fmt.Printf("timestamp=%s\n", ts)
			fmt.Printf("sequence=%d\n", p.Sequence)
			fmt.Printf("padding=%s\n", padStr(p.Padding))
		}
		return 0
	}
	p, err := wid.ParseHlcWidWithUnit(id, o.w, o.z, o.timeUnit)
	if err != nil {
		fmt.Println("null")
		return 1
	}
	ts := p.Timestamp.UTC().Format(time.RFC3339)
	if o.json {
		payload := map[string]any{
			"raw":             p.Raw,
			"timestamp":       ts,
			"logical_counter": p.LogicalCounter,
			"node":            p.Node,
			"padding":         p.Padding,
		}
		b, _ := json.Marshal(payload)
		fmt.Println(string(b))
	} else {
		fmt.Printf("raw=%s\n", p.Raw)
		fmt.Printf("timestamp=%s\n", ts)
		fmt.Printf("logical_counter=%d\n", p.LogicalCounter)
		fmt.Printf("node=%s\n", p.Node)
		fmt.Printf("padding=%s\n", padStr(p.Padding))
	}
	return 0
}

func cmdHealthcheck(o opts) int {
	sample := ""
	ok := false
	if o.kind == "wid" {
		g, err := wid.NewWidGenWithUnit(o.w, o.z, o.timeUnit)
		if err != nil {
			errln(err.Error())
			return 1
		}
		sample = g.Next()
		ok = wid.ValidateWidWithUnit(sample, o.w, o.z, o.timeUnit)
	} else {
		g, err := wid.NewHLCWidGenWithUnit(o.node, o.w, o.z, o.timeUnit)
		if err != nil {
			errln(err.Error())
			return 1
		}
		sample = g.Next()
		ok = wid.ValidateHlcWidWithUnit(sample, o.w, o.z, o.timeUnit)
	}
	if o.json {
		payload := map[string]any{
			"ok":        ok,
			"kind":      o.kind,
			"W":         o.w,
			"Z":         o.z,
			"time_unit": string(o.timeUnit),
			"sample_id": sample,
		}
		b, _ := json.Marshal(payload)
		fmt.Println(string(b))
	} else {
		fmt.Printf("ok=%v kind=%s sample=%s\n", ok, o.kind, sample)
	}
	if ok {
		return 0
	}
	return 1
}

func cmdBench(o opts) int {
	n := o.count
	if n <= 0 {
		n = 100000
	}
	start := time.Now()
	if o.kind == "wid" {
		g, err := wid.NewWidGenWithUnit(o.w, o.z, o.timeUnit)
		if err != nil {
			errln(err.Error())
			return 1
		}
		for i := 0; i < n; i++ {
			_ = g.Next()
		}
	} else {
		g, err := wid.NewHLCWidGenWithUnit(o.node, o.w, o.z, o.timeUnit)
		if err != nil {
			errln(err.Error())
			return 1
		}
		for i := 0; i < n; i++ {
			_ = g.Next()
		}
	}
	secs := time.Since(start).Seconds()
	if secs <= 0 {
		secs = 1e-9
	}
	payload := map[string]any{
		"impl":        "go",
		"kind":        o.kind,
		"W":           o.w,
		"Z":           o.z,
		"time_unit":   string(o.timeUnit),
		"n":           n,
		"seconds":     secs,
		"ids_per_sec": float64(n) / secs,
	}
	b, _ := json.Marshal(payload)
	fmt.Println(string(b))
	return 0
}

func runCanonical(args []string) int {
	c, err := parseCanonical(args)
	if err != nil {
		errln(err.Error())
		return 1
	}
	if c.a == "help-actions" {
		printActions()
		return 0
	}
	if c.a == "sign" {
		return runSign(c)
	}
	if c.a == "verify" {
		return runVerify(c)
	}
	if c.a == "w-otp" {
		return runWOtp(c)
	}
	stateMode, _ := parseStateTransport(c)
	if stateMode == "sql" && (c.a == "next" || c.a == "stream") {
		switch c.a {
		case "next":
			return runCanonicalSQLNext(c)
		case "stream":
			return runCanonicalSQLStream(c)
		}
	}
	switch c.a {
	case "next":
		return cmdNext(opts{kind: "wid", w: c.w, z: c.z, timeUnit: c.t})
	case "stream":
		return cmdStream(opts{kind: "wid", w: c.w, z: c.z, timeUnit: c.t, count: c.n})
	case "healthcheck":
		return cmdHealthcheck(opts{kind: "wid", w: c.w, z: c.z, timeUnit: c.t, json: true})
	default:
		return runNativeOrchestration(c)
	}
}

func b64urlEncode(b []byte) string {
	return base64.RawURLEncoding.EncodeToString(b)
}

func b64urlDecode(s string) ([]byte, error) {
	return base64.RawURLEncoding.DecodeString(s)
}

func buildSignVerifyMessage(c canon) ([]byte, error) {
	if strings.TrimSpace(c.wid) == "" {
		return nil, errors.New("WID=<wid_string> required")
	}
	msg := []byte(c.wid)
	if strings.TrimSpace(c.data) != "" {
		b, err := os.ReadFile(c.data)
		if err != nil {
			return nil, fmt.Errorf("data file not found: %s", c.data)
		}
		msg = append(msg, b...)
	}
	return msg, nil
}

func loadEd25519PrivateKey(path string) (ed25519.PrivateKey, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	blk, _ := pem.Decode(b)
	if blk == nil {
		return nil, errors.New("failed to parse PEM private key")
	}
	keyAny, err := x509.ParsePKCS8PrivateKey(blk.Bytes)
	if err != nil {
		return nil, err
	}
	pk, ok := keyAny.(ed25519.PrivateKey)
	if !ok {
		return nil, errors.New("loaded key is not an Ed25519 private key")
	}
	return pk, nil
}

func loadEd25519PublicKey(path string) (ed25519.PublicKey, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	blk, _ := pem.Decode(b)
	if blk == nil {
		return nil, errors.New("failed to parse PEM public key")
	}
	keyAny, err := x509.ParsePKIXPublicKey(blk.Bytes)
	if err != nil {
		return nil, err
	}
	pk, ok := keyAny.(ed25519.PublicKey)
	if !ok {
		return nil, errors.New("loaded key is not an Ed25519 public key")
	}
	return pk, nil
}

func runSign(c canon) int {
	if strings.TrimSpace(c.key) == "" {
		errln("KEY=<private_key_path> required for A=sign")
		return 1
	}
	msg, err := buildSignVerifyMessage(c)
	if err != nil {
		errln(err.Error())
		return 1
	}
	pk, err := loadEd25519PrivateKey(c.key)
	if err != nil {
		errln(err.Error())
		return 1
	}
	sig := ed25519.Sign(pk, msg)
	enc := b64urlEncode(sig)
	if strings.TrimSpace(c.out) != "" {
		if err := os.WriteFile(c.out, []byte(enc), 0o644); err != nil {
			errln(err.Error())
			return 1
		}
		return 0
	}
	fmt.Println(enc)
	return 0
}

func runVerify(c canon) int {
	if strings.TrimSpace(c.key) == "" {
		errln("KEY=<public_key_path> required for A=verify")
		return 1
	}
	if strings.TrimSpace(c.sig) == "" {
		errln("SIG=<signature_string> required for A=verify")
		return 1
	}
	msg, err := buildSignVerifyMessage(c)
	if err != nil {
		errln(err.Error())
		return 1
	}
	pk, err := loadEd25519PublicKey(c.key)
	if err != nil {
		errln(err.Error())
		return 1
	}
	sig, err := b64urlDecode(c.sig)
	if err != nil {
		errln("invalid signature encoding")
		return 1
	}
	if ed25519.Verify(pk, msg, sig) {
		fmt.Println("Signature valid.")
		return 0
	}
	errln("Signature invalid.")
	return 1
}

func resolveWOtpSecret(raw string) (string, error) {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return "", errors.New("w-otp secret cannot be empty")
	}
	if b, err := os.ReadFile(raw); err == nil {
		return strings.TrimSpace(string(b)), nil
	}
	return raw, nil
}

func computeWOtp(secret, widValue string, digits int) string {
	mac := hmac.New(sha256.New, []byte(secret))
	_, _ = mac.Write([]byte(widValue))
	sum := mac.Sum(nil)
	v := (uint32(sum[0]) << 24) | (uint32(sum[1]) << 16) | (uint32(sum[2]) << 8) | uint32(sum[3])
	mod := uint32(1)
	for i := 0; i < digits; i++ {
		mod *= 10
	}
	code := v % mod
	return fmt.Sprintf("%0*d", digits, code)
}

func runWOtp(c canon) int {
	mode := strings.ToLower(strings.TrimSpace(c.mode))
	if mode == "" {
		mode = "gen"
	}
	if mode != "gen" && mode != "verify" {
		errln("MODE must be gen or verify for A=w-otp")
		return 1
	}
	if strings.TrimSpace(c.key) == "" {
		errln("KEY=<secret_or_path> required for A=w-otp")
		return 1
	}
	secret, err := resolveWOtpSecret(c.key)
	if err != nil {
		errln(err.Error())
		return 1
	}
	digits := c.digits
	if digits == 0 {
		digits = 6
	}
	if digits < 4 || digits > 10 {
		errln("DIGITS must be an integer between 4 and 10")
		return 1
	}
	if c.maxAgeSec < 0 {
		errln("MAX_AGE_SEC must be a non-negative integer")
		return 1
	}
	if c.maxFutureSec < 0 {
		errln("MAX_FUTURE_SEC must be a non-negative integer")
		return 1
	}
	widValue := strings.TrimSpace(c.wid)
	if widValue == "" && mode == "gen" {
		g, err := wid.NewWidGenWithUnit(c.w, c.z, c.t)
		if err != nil {
			errln(err.Error())
			return 1
		}
		widValue = g.Next()
	}
	if widValue == "" {
		errln("WID=<wid_string> required for A=w-otp MODE=verify")
		return 1
	}
	otp := computeWOtp(secret, widValue, digits)
	if mode == "gen" {
		b, _ := json.Marshal(map[string]any{"wid": widValue, "otp": otp, "digits": digits})
		fmt.Println(string(b))
		return 0
	}
	if strings.TrimSpace(c.code) == "" {
		errln("CODE=<otp_code> required for A=w-otp MODE=verify")
		return 1
	}
	if c.maxAgeSec > 0 || c.maxFutureSec > 0 {
		parsed, err := wid.ParseWidWithUnit(widValue, c.w, c.z, c.t)
		if err != nil {
			errln("WID timestamp is invalid for time-window verification")
			return 1
		}
		nowMs := time.Now().UTC().UnixMilli()
		widMs := parsed.Timestamp.UnixMilli()
		delta := nowMs - widMs
		if delta < 0 {
			if -delta > int64(c.maxFutureSec)*1000 {
				errln("OTP invalid: WID timestamp is too far in the future")
				return 1
			}
		} else if c.maxAgeSec > 0 && delta > int64(c.maxAgeSec)*1000 {
			errln("OTP invalid: WID timestamp is too old")
			return 1
		}
	}
	if subtle.ConstantTimeCompare([]byte(c.code), []byte(otp)) == 1 {
		fmt.Println("OTP valid.")
		return 0
	}
	errln("OTP invalid.")
	return 1
}

func sqlEscapeSingle(s string) string {
	return strings.ReplaceAll(s, "'", "''")
}

func sqliteExec(dbPath string, sql string) (string, error) {
	if _, err := exec.LookPath("sqlite3"); err != nil {
		return "", errors.New("sqlite3 command not found (required for E=sql)")
	}
	out, err := exec.Command("sqlite3", "-cmd", ".timeout 5000", dbPath, sql).Output()
	if err != nil {
		return "", err
	}
	return strings.TrimSpace(string(out)), nil
}

func sqlStatePath(c canon) string {
	return filepath.Join(dataDir(c), "wid_state.sqlite")
}

func sqlStateKey(c canon) string {
	return fmt.Sprintf("wid:go:%d:%d:%s", c.w, c.z, c.t)
}

func sqlEnsureState(dbPath string, key string) error {
	escaped := sqlEscapeSingle(key)
	sql := "CREATE TABLE IF NOT EXISTS wid_state (k TEXT PRIMARY KEY, last_tick INTEGER NOT NULL, last_seq INTEGER NOT NULL);" +
		fmt.Sprintf("INSERT OR IGNORE INTO wid_state(k,last_tick,last_seq) VALUES('%s',0,-1);", escaped)
	_, err := sqliteExec(dbPath, sql)
	return err
}

func sqlLoadState(dbPath string, key string) (int64, int, error) {
	escaped := sqlEscapeSingle(key)
	sql := fmt.Sprintf("SELECT last_tick || '|' || last_seq FROM wid_state WHERE k='%s';", escaped)
	raw, err := sqliteExec(dbPath, sql)
	if err != nil {
		return 0, 0, err
	}
	parts := strings.SplitN(raw, "|", 2)
	if len(parts) != 2 {
		return 0, 0, errors.New("invalid sql state row")
	}
	lastTick, err := strconv.ParseInt(parts[0], 10, 64)
	if err != nil {
		return 0, 0, err
	}
	lastSeq64, err := strconv.ParseInt(parts[1], 10, 64)
	if err != nil {
		return 0, 0, err
	}
	return lastTick, int(lastSeq64), nil
}

func sqlCompareAndSwapState(dbPath string, key string, oldTick int64, oldSeq int, newTick int64, newSeq int) (bool, error) {
	escaped := sqlEscapeSingle(key)
	sql := fmt.Sprintf(
		"UPDATE wid_state SET last_tick=%d,last_seq=%d WHERE k='%s' AND last_tick=%d AND last_seq=%d;SELECT changes();",
		newTick,
		newSeq,
		escaped,
		oldTick,
		oldSeq,
	)
	raw, err := sqliteExec(dbPath, sql)
	if err != nil {
		return false, err
	}
	return strings.TrimSpace(raw) == "1", nil
}

func sqlAllocateNextWid(c canon) (string, error) {
	dbPath := sqlStatePath(c)
	key := sqlStateKey(c)
	if err := sqlEnsureState(dbPath, key); err != nil {
		return "", err
	}
	for i := 0; i < 64; i++ {
		lastTick, lastSeq, err := sqlLoadState(dbPath, key)
		if err != nil {
			return "", err
		}
		g, err := wid.NewWidGenWithUnit(c.w, c.z, c.t)
		if err != nil {
			return "", err
		}
		g.RestoreState(lastTick, lastSeq)
		id := g.Next()
		nextTick, nextSeq := g.State()
		ok, err := sqlCompareAndSwapState(dbPath, key, lastTick, lastSeq, nextTick, nextSeq)
		if err != nil {
			return "", err
		}
		if ok {
			return id, nil
		}
	}
	return "", errors.New("sql allocation contention: retry budget exhausted")
}

func runCanonicalSQLNext(c canon) int {
	dd := dataDir(c)
	if err := os.MkdirAll(dd, 0o755); err != nil {
		errln(err.Error())
		return 1
	}
	id, err := sqlAllocateNextWid(c)
	if err != nil {
		errln("failed to allocate SQL WID: " + err.Error())
		return 1
	}
	fmt.Println(id)
	return 0
}

func runCanonicalSQLStream(c canon) int {
	dd := dataDir(c)
	if err := os.MkdirAll(dd, 0o755); err != nil {
		errln(err.Error())
		return 1
	}
	for i := 0; c.n == 0 || i < c.n; i++ {
		id, err := sqlAllocateNextWid(c)
		if err != nil {
			errln("failed to allocate SQL WID: " + err.Error())
			return 1
		}
		fmt.Println(id)
	}
	return 0
}

func parseCanonical(args []string) (canon, error) {
	c := canon{a: "next", w: 4, l: 3600, d: "", i: "auto", e: "state", z: 6, t: wid.TimeUnitSec, r: "auto", m: false, n: 0, wid: "", key: "", sig: "", data: "", out: "", mode: "", code: "", digits: 6, maxAgeSec: 0, maxFutureSec: 5}
	for _, arg := range args {
		kv := strings.SplitN(arg, "=", 2)
		if len(kv) != 2 {
			return c, fmt.Errorf("expected KEY=VALUE, got: %s", arg)
		}
		k, v := kv[0], kv[1]
		if v == "#" {
			v = defaultForKey(k)
		}
		switch k {
		case "A":
			c.a = strings.ToLower(v)
		case "W":
			n, err := strconv.Atoi(v)
			if err != nil {
				return c, errors.New("invalid W")
			}
			c.w = n
		case "L":
			n, err := strconv.Atoi(v)
			if err != nil {
				return c, errors.New("invalid L")
			}
			c.l = n
		case "D":
			c.d = v
		case "I":
			c.i = v
		case "E":
			c.e = v
		case "Z":
			n, err := strconv.Atoi(v)
			if err != nil {
				return c, errors.New("invalid Z")
			}
			c.z = n
		case "T":
			u, err := wid.ParseTimeUnit(v)
			if err != nil {
				return c, err
			}
			c.t = u
		case "R":
			c.r = v
		case "M":
			s := strings.ToLower(v)
			c.m = s == "1" || s == "true" || s == "yes" || s == "on" || s == "y"
		case "N":
			n, err := strconv.Atoi(v)
			if err != nil {
				return c, errors.New("invalid N")
			}
			c.n = n
		case "WID":
			c.wid = v
		case "KEY":
			c.key = v
		case "SIG":
			c.sig = v
		case "DATA":
			c.data = v
		case "OUT":
			c.out = v
		case "MODE":
			c.mode = v
		case "CODE":
			c.code = v
		case "DIGITS":
			n, err := strconv.Atoi(v)
			if err != nil {
				return c, errors.New("invalid DIGITS")
			}
			c.digits = n
		case "MAX_AGE_SEC":
			n, err := strconv.Atoi(v)
			if err != nil {
				return c, errors.New("invalid MAX_AGE_SEC")
			}
			c.maxAgeSec = n
		case "MAX_FUTURE_SEC":
			n, err := strconv.Atoi(v)
			if err != nil {
				return c, errors.New("invalid MAX_FUTURE_SEC")
			}
			c.maxFutureSec = n
		default:
			return c, fmt.Errorf("unknown key: %s", k)
		}
	}
	if c.m {
		c.t = wid.TimeUnitMs
	}
	switch c.a {
	case "id", "default":
		c.a = "next"
	case "hc":
		c.a = "healthcheck"
	case "raf":
		c.a = "saf"
	case "waf", "wraf":
		c.a = "saf-wid"
	case "witr":
		c.a = "wir"
	case "wim":
		c.a = "wism"
	case "wih":
		c.a = "wihp"
	case "wip":
		c.a = "wipr"
	}
	if c.w <= 0 || c.z < 0 || c.n < 0 || c.l < 0 {
		return c, errors.New("W must be >0 and Z/N/L >=0")
	}
	if !isTransport(c.r) {
		return c, errors.New("invalid R transport")
	}
	return c, nil
}

func defaultForKey(k string) string {
	switch k {
	case "A":
		return "next"
	case "W":
		return "4"
	case "L":
		return "3600"
	case "D":
		return ""
	case "I":
		return "auto"
	case "E":
		return "state"
	case "Z":
		return "6"
	case "T":
		return "sec"
	case "R":
		return "auto"
	case "M":
		return "false"
	case "N":
		return "0"
	case "DIGITS":
		return "6"
	case "MAX_AGE_SEC":
		return "0"
	case "MAX_FUTURE_SEC":
		return "5"
	default:
		return ""
	}
}

func isTransport(s string) bool {
	switch s {
	case "auto", "mqtt", "ws", "redis", "null", "stdout":
		return true
	default:
		return false
	}
}

func parseStateTransport(c canon) (string, string) {
	stateMode := c.e
	transport := c.r
	if strings.Contains(c.e, "+") {
		parts := strings.SplitN(c.e, "+", 2)
		stateMode = parts[0]
		if transport == "auto" {
			transport = parts[1]
		}
	} else if strings.Contains(c.e, ",") {
		parts := strings.SplitN(c.e, ",", 2)
		stateMode = parts[0]
		if transport == "auto" {
			transport = parts[1]
		}
	}
	return stateMode, transport
}

func runtimeDir() string { return filepath.Clean(".local/wid/go") }
func runtimePid() string { return filepath.Join(runtimeDir(), "service.pid") }
func runtimeLog() string { return filepath.Join(runtimeDir(), "service.log") }

func dataDir(c canon) string {
	if strings.TrimSpace(c.d) == "" {
		return filepath.Clean(".local/services")
	}
	return filepath.Clean(c.d)
}

func readPid(path string) (int, bool) {
	b, err := os.ReadFile(path)
	if err != nil {
		return 0, false
	}
	pid, err := strconv.Atoi(strings.TrimSpace(string(b)))
	if err != nil || pid <= 0 {
		return 0, false
	}
	return pid, true
}

func pidAlive(pid int) bool {
	return syscall.Kill(pid, 0) == nil
}

func runNativeOrchestration(c canon) int {
	switch c.a {
	case "discover":
		payload := map[string]any{
			"impl":          "go",
			"orchestration": "native",
			"actions": []string{
				"discover", "scaffold", "run", "start", "stop", "status", "logs",
				"saf", "saf-wid", "wir", "wism", "wihp", "wipr", "duplex",
			},
			"transports": []string{"auto", "mqtt", "ws", "redis", "null", "stdout"},
		}
		printJSON(payload)
		return 0
	case "scaffold":
		if strings.TrimSpace(c.d) == "" {
			errln("D=<name> required for A=scaffold")
			return 1
		}
		if err := os.MkdirAll(filepath.Join(c.d, "state"), 0o755); err != nil {
			errln(err.Error())
			return 1
		}
		if err := os.MkdirAll(filepath.Join(c.d, "logs"), 0o755); err != nil {
			errln(err.Error())
			return 1
		}
		fmt.Printf("scaffolded %s\n", c.d)
		return 0
	case "run", "saf", "saf-wid", "wir", "wism", "wihp", "wipr", "duplex":
		return runServiceLoop(c, c.a)
	case "start":
		return runStart(c)
	case "stop":
		return runStop()
	case "status":
		return runStatus()
	case "logs":
		return runLogs()
	default:
		errln("unknown A=" + c.a)
		return 1
	}
}

func runServiceLoop(c canon, action string) int {
	stateMode, transport := parseStateTransport(c)
	if transport == "auto" {
		transport = "mqtt"
	}
	if (action == "saf-wid" || action == "wir" || action == "wism" || action == "wihp" || action == "wipr" || action == "duplex") &&
		!localServiceTransports[transport] {
		errln(fmt.Sprintf("invalid transport for A=%s: %s", action, transport))
		return 1
	}
	dd := dataDir(c)
	_ = os.MkdirAll(dd, 0o755)
	logLevel := os.Getenv("LOG_LEVEL")
	if logLevel == "" {
		logLevel = "INFO"
	}

	g, err := wid.NewWidGenWithUnit(c.w, c.z, c.t)
	if err != nil {
		errln(err.Error())
		return 1
	}
	max := c.n
	if max <= 0 {
		max = int(^uint(0) >> 1)
	}

	for i := 1; i <= max; i++ {
		id := g.Next()
		if transport != "null" {
			switch action {
			case "saf-wid", "wism", "wihp", "wipr":
				printJSON(map[string]any{
					"impl":      "go",
					"action":    action,
					"tick":      i,
					"transport": transport,
					"W":         c.w,
					"Z":         c.z,
					"time_unit": string(c.t),
					"wid":       id,
					"interval":  c.l,
					"log_level": logLevel,
					"data_dir":  dd,
				})
			case "duplex":
				bTransport := "ws"
				if c.i != "auto" && localServiceTransports[c.i] {
					bTransport = c.i
				}
				printJSON(map[string]any{
					"impl":        "go",
					"action":      "duplex",
					"tick":        i,
					"a_transport": transport,
					"b_transport": bTransport,
					"interval":    c.l,
					"data_dir":    dd,
				})
			default:
				printJSON(map[string]any{
					"impl":       "go",
					"action":     action,
					"tick":       i,
					"transport":  transport,
					"interval":   c.l,
					"log_level":  logLevel,
					"data_dir":   dd,
					"state_mode": stateMode,
				})
			}
		}
		if i < max && c.l > 0 {
			time.Sleep(time.Duration(c.l) * time.Second)
		}
	}
	return 0
}

func runStart(c canon) int {
	_ = os.MkdirAll(runtimeDir(), 0o755)
	if pid, ok := readPid(runtimePid()); ok && pidAlive(pid) {
		fmt.Printf("wid-go start: already-running pid=%d log=%s\n", pid, runtimeLog())
		return 0
	}

	exe, err := os.Executable()
	if err != nil {
		errln("failed to resolve executable: " + err.Error())
		return 1
	}
	logf, err := os.OpenFile(runtimeLog(), os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o644)
	if err != nil {
		errln("failed to open log: " + err.Error())
		return 1
	}
	defer logf.Close()

	args := []string{
		"__daemon",
		fmt.Sprintf("A=%s", "run"),
		fmt.Sprintf("W=%d", c.w),
		fmt.Sprintf("L=%d", c.l),
		fmt.Sprintf("D=%s", valueOrHash(c.d)),
		fmt.Sprintf("I=%s", c.i),
		fmt.Sprintf("E=%s", c.e),
		fmt.Sprintf("Z=%d", c.z),
		fmt.Sprintf("T=%s", c.t),
		fmt.Sprintf("R=%s", c.r),
		fmt.Sprintf("M=%t", c.m),
		fmt.Sprintf("N=%d", c.n),
	}

	cmd := exec.Command(exe, args...)
	cmd.Stdout = logf
	cmd.Stderr = logf
	cmd.Stdin = nil
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	if err := cmd.Start(); err != nil {
		errln("failed to start daemon: " + err.Error())
		return 1
	}
	_ = os.WriteFile(runtimePid(), []byte(fmt.Sprintf("%d\n", cmd.Process.Pid)), 0o644)
	fmt.Printf("wid-go start: started pid=%d log=%s\n", cmd.Process.Pid, runtimeLog())
	return 0
}

func runStatus() int {
	pid, ok := readPid(runtimePid())
	if ok && pidAlive(pid) {
		fmt.Printf("wid-go status=running pid=%d log=%s\n", pid, runtimeLog())
		return 0
	}
	_ = os.Remove(runtimePid())
	fmt.Println("wid-go status=stopped")
	return 0
}

func runStop() int {
	pid, ok := readPid(runtimePid())
	if !ok || !pidAlive(pid) {
		_ = os.Remove(runtimePid())
		fmt.Println("wid-go stop: not running")
		return 0
	}
	if err := syscall.Kill(pid, syscall.SIGTERM); err != nil {
		errln(fmt.Sprintf("failed to stop pid=%d: %v", pid, err))
		return 1
	}
	_ = os.Remove(runtimePid())
	fmt.Printf("wid-go stop: stopped pid=%d\n", pid)
	return 0
}

func runLogs() int {
	b, err := os.ReadFile(runtimeLog())
	if err != nil {
		fmt.Println("wid-go logs: empty")
		return 0
	}
	fmt.Print(string(b))
	return 0
}

func printJSON(v any) {
	b, _ := json.Marshal(v)
	fmt.Println(string(b))
}

func valueOrHash(s string) string {
	if strings.TrimSpace(s) == "" {
		return "#"
	}
	return s
}

func runSelftest() int {
	wg, _ := wid.NewWidGen(4, 0)
	a := wg.Next()
	b := wg.Next()
	if !(a < b) {
		return 1
	}
	if !wid.ValidateWid(a, 4, 0) {
		return 1
	}
	hg, _ := wid.NewHLCWidGen("node01", 4, 0)
	h := hg.Next()
	if !wid.ValidateHlcWid(h, 4, 0) {
		return 1
	}
	if wid.ValidateWid("20260212T091530.0000Z-node01", 4, 0) {
		return 1
	}
	if wid.ValidateHlcWid("20260212T091530.0000Z", 4, 0) {
		return 1
	}
	if !wid.ValidateWidWithUnit("20260212T091530123.0000Z", 4, 0, wid.TimeUnitMs) {
		return 1
	}
	return 0
}

func printCompletion(shell string) {
	switch shell {
	case "bash":
		os.Stdout.WriteString(`_wid_complete() {
  local cur="${COMP_WORDS[COMP_CWORD]}"
  local cmds="next stream healthcheck validate parse help-actions bench selftest completion"
  if [[ "$cur" == *=* ]]; then
    local key="${cur%%=*}" val="${cur#*=}" vals=""
    case "$key" in
      A) vals="next stream healthcheck sign verify w-otp discover scaffold run start stop status logs saf saf-wid wir wism wihp wipr duplex help-actions" ;;
      T) vals="sec ms" ;;
      I) vals="auto sh bash" ;;
      E) vals="state stateless sql" ;;
      R) vals="auto mqtt ws redis null stdout" ;;
      M) vals="true false" ;;
    esac
    local IFS=$'\n'
    COMPREPLY=($(for v in $vals; do [[ "$v" == "$val"* ]] && printf '%s\n' "${key}=${v}"; done))
  else
    local kv="A= W= Z= T= N= L= D= I= E= R= M="
    COMPREPLY=($(compgen -W "$cmds $kv" -- "$cur"))
  fi
}
complete -o nospace -F _wid_complete wid
`)
	case "zsh":
		os.Stdout.WriteString(`#compdef wid
_wid_complete() {
  local cur="${words[-1]}"
  local -a cmds=(next stream healthcheck validate parse help-actions bench selftest completion)
  if [[ "$cur" == *=* ]]; then
    local key="${cur%%=*}"
    local -a vals=()
    case "$key" in
      A) vals=(next stream healthcheck sign verify w-otp discover scaffold run start stop status logs saf saf-wid wir wism wihp wipr duplex help-actions) ;;
      T) vals=(sec ms) ;;
      I) vals=(auto sh bash) ;;
      E) vals=(state stateless sql) ;;
      R) vals=(auto mqtt ws redis null stdout) ;;
      M) vals=(true false) ;;
    esac
    compadd -P "${key}=" -- "${vals[@]}"
  else
    compadd -- "${cmds[@]}" A= W= Z= T= N= L= D= I= E= R= M=
  fi
}
_wid_complete "$@"
`)
	case "fish":
		os.Stdout.WriteString(`complete -c wid -e
complete -c wid -f -n 'not __fish_seen_subcommand_from next stream healthcheck validate parse help-actions bench selftest completion' -a next -d 'Emit one WID'
complete -c wid -f -n 'not __fish_seen_subcommand_from next stream healthcheck validate parse help-actions bench selftest completion' -a stream -d 'Stream WIDs continuously'
complete -c wid -f -n 'not __fish_seen_subcommand_from next stream healthcheck validate parse help-actions bench selftest completion' -a healthcheck -d 'Generate and validate a sample WID'
complete -c wid -f -n 'not __fish_seen_subcommand_from next stream healthcheck validate parse help-actions bench selftest completion' -a validate -d 'Validate a WID string'
complete -c wid -f -n 'not __fish_seen_subcommand_from next stream healthcheck validate parse help-actions bench selftest completion' -a parse -d 'Parse a WID string'
complete -c wid -f -n 'not __fish_seen_subcommand_from next stream healthcheck validate parse help-actions bench selftest completion' -a help-actions -d 'Show canonical action matrix'
complete -c wid -f -n 'not __fish_seen_subcommand_from next stream healthcheck validate parse help-actions bench selftest completion' -a completion -d 'Print shell completion script'
complete -c wid -f -a 'A=next A=stream A=healthcheck A=sign A=verify A=w-otp A=start A=stop A=status A=logs A=help-actions' -d 'Action'
complete -c wid -f -a 'T=sec T=ms' -d 'Time unit'
complete -c wid -f -a 'I=auto I=sh I=bash' -d 'Input source'
complete -c wid -f -a 'E=state E=stateless E=sql' -d 'State mode'
complete -c wid -f -a 'R=auto R=mqtt R=ws R=redis R=null R=stdout' -d 'Transport'
complete -c wid -f -a 'M=true M=false' -d 'Milliseconds mode'
complete -c wid -f -a 'W=' -d 'Sequence width'
complete -c wid -f -a 'Z=' -d 'Padding length'
complete -c wid -f -a 'N=' -d 'Count'
complete -c wid -f -a 'L=' -d 'Interval seconds'
`)
	default:
		fmt.Fprintf(os.Stderr, "error: unknown shell '%s'. Use: wid completion bash|zsh|fish\n", shell)
		os.Exit(1)
	}
}

func printHelp() {
	fmt.Fprintln(os.Stderr, "wid - WID/HLC-WID generator CLI")
	fmt.Fprintln(os.Stderr)
	fmt.Fprintln(os.Stderr, "Usage:")
	fmt.Fprintln(os.Stderr, "  wid next [--kind wid|hlc] [--node <name>] [--W <n>] [--Z <n>] [--time-unit sec|ms]")
	fmt.Fprintln(os.Stderr, "  wid stream [--kind wid|hlc] [--node <name>] [--W <n>] [--Z <n>] [--time-unit sec|ms] [--count <n>]")
	fmt.Fprintln(os.Stderr, "  wid validate <id> [--kind wid|hlc] [--W <n>] [--Z <n>] [--time-unit sec|ms]")
	fmt.Fprintln(os.Stderr, "  wid parse <id> [--kind wid|hlc] [--W <n>] [--Z <n>] [--time-unit sec|ms] [--json]")
	fmt.Fprintln(os.Stderr, "  wid healthcheck [--kind wid|hlc] [--node <name>] [--W <n>] [--Z <n>] [--time-unit sec|ms] [--json]")
	fmt.Fprintln(os.Stderr, "  wid bench [--kind wid|hlc] [--node <name>] [--W <n>] [--Z <n>] [--time-unit sec|ms] [--count <n>]")
	fmt.Fprintln(os.Stderr, "  wid selftest")
	fmt.Fprintln(os.Stderr)
	fmt.Fprintln(os.Stderr, "Canonical mode:")
	fmt.Fprintln(os.Stderr, "  wid W=# A=# L=# D=# I=# E=# Z=# T=sec|ms R=auto|mqtt|ws|redis|null|stdout N=#")
	fmt.Fprintln(os.Stderr, "  wid A=w-otp MODE=gen|verify KEY=<secret|path> [WID=<wid>] [CODE=<otp>] [DIGITS=6] [MAX_AGE_SEC=0] [MAX_FUTURE_SEC=5]")
	fmt.Fprintln(os.Stderr, "  For A=stream: N=0 means infinite stream")
	fmt.Fprintln(os.Stderr, "  E supports: state | stateless | sql")
}

func printActions() {
	fmt.Println(`wid action matrix

Core ID:
  A=next | A=stream | A=healthcheck | A=sign | A=verify | A=w-otp

Service lifecycle (native):
  A=discover | A=scaffold | A=run | A=start | A=stop | A=status | A=logs

Service modules (native):
  A=saf      (alias: raf)
  A=saf-wid  (aliases: waf, wraf)
  A=wir      (alias: witr)
  A=wism     (alias: wim)
  A=wihp     (alias: wih)
  A=wipr     (alias: wip)
  A=duplex

Help:
  A=help-actions

State mode:
  E=state | E=stateless | E=sql`)
}

func errln(s string) { fmt.Fprintln(os.Stderr, "error:", s) }
func exit(code int)  { os.Exit(code) }
