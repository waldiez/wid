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
	"regexp"
	"strconv"
	"strings"
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
	// intervalSecs is the canonical L= stream cadence: 0 (the stream
	// default, and always the flag-mode value) emits back-to-back; an
	// explicit L=n sleeps n seconds between emissions.
	intervalSecs int
}

type canon struct {
	a string
	w int
	l int
	// lExplicit is true only for a real L=<n> (not omitted, not the L=#
	// placeholder). A=stream treats an unset L as 0 (no sleep); the 3600
	// default applies to the Rust-only service loops, not streaming.
	lExplicit    bool
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

func main() {
	args := os.Args[1:]
	if len(args) == 0 {
		printHelp()
		os.Exit(2)
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
		o, err := parseOpts(args[1:], false, false)
		if err != nil {
			errln(err.Error())
			os.Exit(2)
		}
		exit(cmdNext(o))
	case "stream":
		o, err := parseOpts(args[1:], true, false)
		if err != nil {
			errln(err.Error())
			os.Exit(2)
		}
		exit(cmdStream(o))
	case "validate":
		if len(args) < 2 {
			errln("validate requires an id")
			os.Exit(2)
		}
		o, err := parseOpts(args[2:], false, false)
		if err != nil {
			errln(err.Error())
			os.Exit(2)
		}
		exit(cmdValidate(args[1], o))
	case "parse":
		if len(args) < 2 {
			errln("parse requires an id")
			os.Exit(2)
		}
		o, err := parseOpts(args[2:], false, true)
		if err != nil {
			errln(err.Error())
			os.Exit(2)
		}
		exit(cmdParse(args[1], o))
	case "healthcheck":
		o, err := parseOpts(args[1:], false, true)
		if err != nil {
			errln(err.Error())
			os.Exit(2)
		}
		exit(cmdHealthcheck(o))
	case "bench":
		o, err := parseOpts(args[1:], true, false)
		if err != nil {
			errln(err.Error())
			os.Exit(2)
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

func parseOpts(args []string, allowCount bool, allowJSON bool) (opts, error) {
	o := opts{
		kind:     "wid",
		node:     "go",
		w:        4,
		z:        6,
		timeUnit: wid.TimeUnitSec,
		count:    0,
		json:     false,
	}
	zExplicit := false
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
			zExplicit = true
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
			// --json belongs to parse/healthcheck only; the other five
			// implementations reject it elsewhere, so accepting (and
			// silently ignoring) it here was surface drift.
			if !allowJSON {
				return o, errors.New("unknown flag: --json")
			}
			o.json = true
		default:
			return o, fmt.Errorf("unknown flag: %s", args[i])
		}
	}
	if o.kind != "wid" && o.kind != "hlc" {
		return o, errors.New("--kind must be one of: wid, hlc")
	}
	if o.w <= 0 || o.w > wid.MaxW {
		return o, errors.New("W must be between 1 and 18")
	}
	if o.z < 0 || o.z > wid.MaxZ {
		return o, errors.New("Z must be between 0 and 64")
	}
	if o.count < 0 {
		return o, errors.New("count must be >= 0")
	}
	if o.kind == "hlc" && !wid.IsValidNode(o.node) {
		return o, errors.New("invalid node")
	}
	// HLC-WID defaults to Z=0 (no random padding) per spec convention;
	// plain WID keeps Z=6. An explicit --Z always wins.
	if o.kind == "hlc" && !zExplicit {
		o.z = 0
	}
	return o, nil
}

func cmdNext(o opts) int {
	if o.kind == "wid" {
		g, err := wid.NewWidGenWithUnit(o.w, o.z, o.timeUnit)
		if err != nil {
			errln(err.Error())
			return 2
		}
		fmt.Println(g.Next())
		return 0
	}
	g, err := wid.NewHLCWidGenWithUnit(o.node, o.w, o.z, o.timeUnit)
	if err != nil {
		errln(err.Error())
		return 2
	}
	fmt.Println(g.Next())
	return 0
}

func cmdStream(o opts) int {
	var next func() string
	if o.kind == "wid" {
		g, err := wid.NewWidGenWithUnit(o.w, o.z, o.timeUnit)
		if err != nil {
			errln(err.Error())
			return 2
		}
		next = g.Next
	} else {
		g, err := wid.NewHLCWidGenWithUnit(o.node, o.w, o.z, o.timeUnit)
		if err != nil {
			errln(err.Error())
			return 2
		}
		next = g.Next
	}
	for i := 0; o.count == 0 || i < o.count; i++ {
		fmt.Println(next())
		if o.intervalSecs > 0 && (o.count == 0 || i+1 < o.count) {
			time.Sleep(time.Duration(o.intervalSecs) * time.Second)
		}
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
		return 2
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
	stateMode := parseStateMode(c)
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
		interval := 0
		if c.lExplicit {
			interval = c.l
		}
		return cmdStream(opts{kind: "wid", w: c.w, z: c.z, timeUnit: c.t, count: c.n, intervalSecs: interval})
	case "healthcheck":
		return cmdHealthcheck(opts{kind: "wid", w: c.w, z: c.z, timeUnit: c.t, json: true})
	default:
		errln(fmt.Sprintf("unknown A=%s", c.a))
		return 2
	}
}

func b64urlEncode(b []byte) string {
	return base64.RawURLEncoding.EncodeToString(b)
}

func b64urlDecode(s string) ([]byte, error) {
	return base64.RawURLEncoding.DecodeString(s)
}

// buildSignVerifyMessage assumes the caller has already checked WID= is
// present (a missing WID is a usage error, exit 2; a missing data file is an
// operational failure, exit 1).
func buildSignVerifyMessage(c canon) ([]byte, error) {
	// Canonical message: "wid-sig-v1:" || len(WID) || ":" || WID || DATA.
	// The domain prefix and explicit WID byte-length frame the WID/DATA
	// boundary so no bytes can shift between them.
	msg := []byte(fmt.Sprintf("wid-sig-v1:%d:", len(c.wid)))
	msg = append(msg, []byte(c.wid)...)
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
		return 2
	}
	if strings.TrimSpace(c.wid) == "" {
		errln("WID=<wid_string> required")
		return 2
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
		return 2
	}
	if strings.TrimSpace(c.sig) == "" {
		errln("SIG=<signature_string> required for A=verify")
		return 2
	}
	if strings.TrimSpace(c.wid) == "" {
		errln("WID=<wid_string> required")
		return 2
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

// wotpWidTickMs extracts epoch-milliseconds from the leading timestamp of a WID,
// for the w-otp time-window (freshness) check only. It is deliberately lenient
// and independent of W/Z and of whether the WID is plain or HLC: the timestamp
// prefix is always YYYYMMDDThhmmss (seconds) or YYYYMMDDThhmmssSSS (milliseconds).
// Using the strict WID parser here made verify reject WIDs that gen had just
// accepted, and disagreed with the other language implementations.
func wotpWidTickMs(widValue string) (int64, error) {
	invalid := errors.New("WID timestamp is invalid for time-window verification")
	ts := widValue
	if i := strings.IndexByte(ts, '.'); i >= 0 {
		ts = ts[:i]
	}
	tIdx := strings.IndexByte(ts, 'T')
	if tIdx < 0 {
		return 0, invalid
	}
	date, tm := ts[:tIdx], ts[tIdx+1:]
	if len(date) != 8 || (len(tm) != 6 && len(tm) != 9) {
		return 0, invalid
	}
	allDigits := func(s string) bool {
		for i := 0; i < len(s); i++ {
			if s[i] < '0' || s[i] > '9' {
				return false
			}
		}
		return true
	}
	if !allDigits(date) || !allDigits(tm) {
		return 0, invalid
	}
	t, err := time.ParseInLocation("20060102T150405", date+"T"+tm[:6], time.UTC)
	if err != nil {
		return 0, invalid
	}
	ms := int64(0)
	if len(tm) == 9 {
		msPart, err := strconv.Atoi(tm[6:9])
		if err != nil {
			return 0, invalid
		}
		ms = int64(msPart)
	}
	return t.UnixMilli() + ms, nil
}

func computeWOtp(secret, widValue string, digits int) string {
	mac := hmac.New(sha256.New, []byte(secret))
	_, _ = mac.Write([]byte(widValue))
	sum := mac.Sum(nil)
	v := (uint64(sum[0]) << 24) | (uint64(sum[1]) << 16) | (uint64(sum[2]) << 8) | uint64(sum[3])
	// CRYPTO_SPEC: otp = value mod 10^DIGITS. The modulus must be 64-bit:
	// DIGITS may be 10 and 10^10 wraps a uint32 (10^10 mod 2^32 = 1410065408).
	mod := uint64(1)
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
		return 2
	}
	if strings.TrimSpace(c.key) == "" {
		errln("KEY=<secret_or_path> required for A=w-otp")
		return 2
	}
	secret, err := resolveWOtpSecret(c.key)
	if err != nil {
		errln(err.Error())
		return 1
	}
	// An empty secret *file* must be rejected like an empty inline secret
	// (the Python/TS/sh/C implementations already do).
	if secret == "" {
		errln("w-otp secret cannot be empty")
		return 2
	}
	digits := c.digits
	if digits == 0 {
		digits = 6
	}
	if digits < 4 || digits > 10 {
		errln("DIGITS must be an integer between 4 and 10")
		return 2
	}
	if c.maxAgeSec < 0 {
		errln("MAX_AGE_SEC must be a non-negative integer")
		return 2
	}
	if c.maxFutureSec < 0 {
		errln("MAX_FUTURE_SEC must be a non-negative integer")
		return 2
	}
	widValue := strings.TrimSpace(c.wid)
	if widValue == "" && mode == "gen" {
		g, err := wid.NewWidGenWithUnit(c.w, c.z, c.t)
		if err != nil {
			errln(err.Error())
			return 2
		}
		widValue = g.Next()
	}
	if widValue == "" {
		errln("WID=<wid_string> required for A=w-otp MODE=verify")
		return 2
	}
	otp := computeWOtp(secret, widValue, digits)
	if mode == "gen" {
		b, _ := json.Marshal(map[string]any{"wid": widValue, "otp": otp, "digits": digits})
		fmt.Println(string(b))
		return 0
	}
	if strings.TrimSpace(c.code) == "" {
		errln("CODE=<otp_code> required for A=w-otp MODE=verify")
		return 2
	}
	if c.maxAgeSec > 0 || c.maxFutureSec > 0 {
		widMs, err := wotpWidTickMs(widValue)
		if err != nil {
			errln("WID timestamp is invalid for time-window verification")
			return 1
		}
		nowMs := time.Now().UTC().UnixMilli()
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

// validStateKey reports whether k matches the expected state-key format
// wid:W:Z:T.  All callers build the key from trusted values (W and Z are
// parsed integers, T is the validated "sec"/"ms" enum), so this is a
// defence-in-depth guard, not a sanitizer for untrusted input.
var validStateKey = regexp.MustCompile(`^wid:\d+:\d+:(sec|ms)$`)

// The Go CLI's E=sql mode shells out to the external sqlite3 binary
// (see README.md for the rationale).  Because the SQL is passed as a
// command-line argument, driver-level parameterised queries are not
// available.  Every value interpolated into a statement below comes from
// one of two safe sources:
//
//   - State key: always wid:W:Z:T, guarded by validStateKey above.
//   - Tick / sequence: int64 formatted with %d – no SQL metacharacters
//     can appear.
//
// This is the only implementation that uses string interpolation; the
// other five all link an in-process SQLite library and use parameterised
// queries.

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

// The state key is deliberately language-agnostic (wid:W:Z:T, no
// implementation tag): all six implementations share one row per generator
// shape, so mixing languages on the same database cannot mint duplicate WIDs.
func sqlStateKey(c canon) string {
	return fmt.Sprintf("wid:%d:%d:%s", c.w, c.z, c.t)
}

func sqlEnsureState(dbPath string, key string) error {
	if !validStateKey.MatchString(key) {
		return errors.New("invalid state key format")
	}
	// key is safe for interpolation (guaranteed to match wid:\d+:\d+:(sec|ms)).
	sql := "CREATE TABLE IF NOT EXISTS wid_state (k TEXT PRIMARY KEY, last_tick INTEGER NOT NULL, last_seq INTEGER NOT NULL);" +
		fmt.Sprintf("INSERT OR IGNORE INTO wid_state(k,last_tick,last_seq) VALUES('%s',0,-1);", key)
	_, err := sqliteExec(dbPath, sql)
	return err
}

func sqlLoadState(dbPath string, key string) (int64, int64, error) {
	if !validStateKey.MatchString(key) {
		return 0, 0, errors.New("invalid state key format")
	}
	// key is safe for interpolation (guaranteed to match wid:\d+:\d+:(sec|ms)).
	sql := fmt.Sprintf("SELECT last_tick || '|' || last_seq FROM wid_state WHERE k='%s';", key)
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
	lastSeq, err := strconv.ParseInt(parts[1], 10, 64)
	if err != nil {
		return 0, 0, err
	}
	return lastTick, lastSeq, nil
}

func sqlCompareAndSwapState(dbPath string, key string, oldTick, oldSeq, newTick, newSeq int64) (bool, error) {
	if !validStateKey.MatchString(key) {
		return false, errors.New("invalid state key format")
	}
	// key is safe for interpolation (guaranteed to match wid:\d+:\d+:(sec|ms));
	// ticks and seqs are int64 formatted with %d – no SQL metacharacters.
	sql := fmt.Sprintf(
		"UPDATE wid_state SET last_tick=%d,last_seq=%d WHERE k='%s' AND last_tick=%d AND last_seq=%d;SELECT changes();",
		newTick,
		newSeq,
		key,
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
		if err := g.RestoreState(lastTick, lastSeq); err != nil {
			return "", fmt.Errorf("invalid SQL state values: %w", err)
		}
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
		if c.lExplicit && c.l > 0 && (c.n == 0 || i+1 < c.n) {
			time.Sleep(time.Duration(c.l) * time.Second)
		}
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
			c.lExplicit = kv[1] != "#"
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
	}
	// Reject out-of-range W/Z here (usage error, exit 2) instead of letting
	// the generator constructor report it as an operational failure.
	if c.w <= 0 || c.w > wid.MaxW {
		return c, errors.New("W must be between 1 and 18")
	}
	if c.z < 0 || c.z > wid.MaxZ {
		return c, errors.New("Z must be between 0 and 64")
	}
	if c.n < 0 || c.l < 0 {
		return c, errors.New("N/L must be >= 0")
	}
	if !isTransport(c.r) {
		return c, fmt.Errorf("transport R=%s is only available in the Rust implementation (services/transports are Rust-only)", c.r)
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

// Core transports only; MQTT/WS/Redis adapters live exclusively in the Rust
// implementation (see spec/SERVICES.md).
func isTransport(s string) bool {
	switch s {
	case "auto", "null", "stdout":
		return true
	default:
		return false
	}
}

// E may carry a "+transport" / ",transport" suffix from the full canonical
// grammar; only the state-mode half is meaningful here (transports are
// Rust-only).
func parseStateMode(c canon) string {
	if strings.Contains(c.e, "+") {
		return strings.SplitN(c.e, "+", 2)[0]
	}
	if strings.Contains(c.e, ",") {
		return strings.SplitN(c.e, ",", 2)[0]
	}
	return c.e
}

func dataDir(c canon) string {
	if strings.TrimSpace(c.d) == "" {
		return filepath.Clean(".local/services")
	}
	return filepath.Clean(c.d)
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
      A) vals="next stream healthcheck sign verify w-otp help-actions" ;;
      T) vals="sec ms" ;;
      I) vals="auto sh bash" ;;
      E) vals="state stateless sql" ;;
      R) vals="auto null stdout" ;;
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
      A) vals=(next stream healthcheck sign verify w-otp help-actions) ;;
      T) vals=(sec ms) ;;
      I) vals=(auto sh bash) ;;
      E) vals=(state stateless sql) ;;
      R) vals=(auto null stdout) ;;
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
complete -c wid -f -a 'A=next A=stream A=healthcheck A=sign A=verify A=w-otp A=help-actions' -d 'Action'
complete -c wid -f -a 'T=sec T=ms' -d 'Time unit'
complete -c wid -f -a 'I=auto I=sh I=bash' -d 'Input source'
complete -c wid -f -a 'E=state E=stateless E=sql' -d 'State mode'
complete -c wid -f -a 'R=auto R=null R=stdout' -d 'Transport'
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

Services (Rust implementation only -- see spec/SERVICES.md):
  A=start | A=stop | A=status | A=logs | A=run | A=discover | A=scaffold
  A=saf | A=saf-wid | A=wir | A=wism | A=wihp | A=wipr | A=duplex

Help:
  A=help-actions

State mode:
  E=state | E=stateless | E=sql`)
}

func errln(s string) { fmt.Fprintln(os.Stderr, "error:", s) }
func exit(code int)  { os.Exit(code) }
