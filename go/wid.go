// Package wid provides WID and HLC-WID generation, validation, and parsing.
package wid

import (
	"crypto/rand"
	"encoding/hex"
	"errors"
	"fmt"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"time"
)

var (
	ErrInvalidW            = errors.New("W must be > 0")
	ErrInvalidZ            = errors.New("Z must be >= 0")
	ErrInvalidNode         = errors.New("node must be non-empty, no whitespace or hyphens")
	ErrInvalidFormat       = errors.New("invalid WID format")
	ErrInvalidTimestamp    = errors.New("invalid timestamp in WID")
	ErrInvalidRemoteClock  = errors.New("remote clock values must be non-negative")
	ErrInvalidTimeUnit     = errors.New("time-unit must be sec or ms")
	ErrInvalidTimeUnitText = errors.New("invalid time-unit")
)

// TimeUnit enumerates the supported time-precision modes for WID and HLC helpers.
type TimeUnit string

const (
	TimeUnitSec TimeUnit = "sec"
	TimeUnitMs  TimeUnit = "ms"
)

// ParseTimeUnit validates and converts textual time units into the typed TimeUnit.
func ParseTimeUnit(s string) (TimeUnit, error) {
	switch strings.ToLower(s) {
	case "sec":
		return TimeUnitSec, nil
	case "ms":
		return TimeUnitMs, nil
	default:
		return "", ErrInvalidTimeUnit
	}
}

func timeDigits(unit TimeUnit) int {
	if unit == TimeUnitMs {
		return 9
	}
	return 6
}

func nowTick(unit TimeUnit) int64 {
	if unit == TimeUnitMs {
		return time.Now().UnixMilli()
	}
	return time.Now().Unix()
}

func formatTS(tick int64, unit TimeUnit) string {
	if unit == TimeUnitMs {
		return time.UnixMilli(tick).UTC().Format("20060102T150405000")
	}
	return time.Unix(tick, 0).UTC().Format("20060102T150405")
}

func randomHex(z int) string {
	if z <= 0 {
		return ""
	}
	b := make([]byte, (z+1)/2)
	if _, err := rand.Read(b); err != nil {
		// fallback path is deterministic enough for non-security use in tests
		now := time.Now().UnixNano()
		for i := range b {
			b[i] = byte(now >> uint((i%8)*8))
		}
	}
	return hex.EncodeToString(b)[:z]
}

func isValidNode(node string) bool {
	if node == "" {
		return false
	}
	for _, c := range node {
		if c == '-' || c == ' ' || c == '\t' || c == '\n' || c == '\r' {
			return false
		}
	}
	return true
}

// IsValidNode rejects empty or whitespace-containing node names.
func IsValidNode(node string) bool {
	return isValidNode(node)
}

func pow10(n int) int {
	v := 1
	for i := 0; i < n; i++ {
		v *= 10
	}
	return v
}

func parseCalendar(dateStr, timeStr string, unit TimeUnit) (time.Time, error) {
	if len(dateStr) != 8 || len(timeStr) != timeDigits(unit) {
		return time.Time{}, ErrInvalidTimestamp
	}
	year, _ := strconv.Atoi(dateStr[0:4])
	month, _ := strconv.Atoi(dateStr[4:6])
	day, _ := strconv.Atoi(dateStr[6:8])
	hour, _ := strconv.Atoi(timeStr[0:2])
	minute, _ := strconv.Atoi(timeStr[2:4])
	second, _ := strconv.Atoi(timeStr[4:6])
	ms := 0
	if unit == TimeUnitMs {
		ms, _ = strconv.Atoi(timeStr[6:9])
	}
	if month < 1 || month > 12 || day < 1 || day > 31 || hour > 23 || minute > 59 || second > 59 || ms < 0 || ms > 999 {
		return time.Time{}, ErrInvalidTimestamp
	}
	t := time.Date(year, time.Month(month), day, hour, minute, second, ms*1_000_000, time.UTC)
	if t.Day() != day || int(t.Month()) != month {
		return time.Time{}, ErrInvalidTimestamp
	}
	return t, nil
}

// ParsedWid represents each component extracted from a WID string.
type ParsedWid struct {
	Raw         string
	Timestamp   time.Time
	Sequence    int
	Padding     *string
	Millisecond int
}

// ParsedHlcWid captures fields produced by parsing an HLC-WID.
type ParsedHlcWid struct {
	Raw            string
	Timestamp      time.Time
	LogicalCounter int
	Node           string
	Padding        *string
	Millisecond    int
}

var (
	widReMu sync.Mutex
	widReC  = map[string]*regexp.Regexp{}
	hlcReMu sync.Mutex
	hlcReC  = map[string]*regexp.Regexp{}
	hexReMu sync.Mutex
	hexReC  = map[int]*regexp.Regexp{}
)

func widRe(w int, unit TimeUnit) *regexp.Regexp {
	key := fmt.Sprintf("%d:%s", w, unit)
	widReMu.Lock()
	defer widReMu.Unlock()
	if r, ok := widReC[key]; ok {
		return r
	}
	r := regexp.MustCompile(fmt.Sprintf(`^(\d{8})T(\d{%d})\.(\d{%d})Z(.*)$`, timeDigits(unit), w))
	widReC[key] = r
	return r
}

func hlcRe(w int, unit TimeUnit) *regexp.Regexp {
	key := fmt.Sprintf("%d:%s", w, unit)
	hlcReMu.Lock()
	defer hlcReMu.Unlock()
	if r, ok := hlcReC[key]; ok {
		return r
	}
	r := regexp.MustCompile(fmt.Sprintf(`^(\d{8})T(\d{%d})\.(\d{%d})Z-([^\s-]+)(.*)$`, timeDigits(unit), w))
	hlcReC[key] = r
	return r
}

func hexReFor(z int) *regexp.Regexp {
	hexReMu.Lock()
	defer hexReMu.Unlock()
	if r, ok := hexReC[z]; ok {
		return r
	}
	r := regexp.MustCompile(fmt.Sprintf(`^[0-9a-f]{%d}$`, z))
	hexReC[z] = r
	return r
}

// ValidateWid checks the string against the expected W/Z parameters in seconds.
func ValidateWid(wid string, w, z int) bool {
	return ValidateWidWithUnit(wid, w, z, TimeUnitSec)
}

// ValidateWidWithUnit checks the string against W/Z parameters at the given time unit.
func ValidateWidWithUnit(wid string, w, z int, unit TimeUnit) bool {
	_, err := ParseWidWithUnit(wid, w, z, unit)
	return err == nil
}

// ValidateHlcWid validates an HLC-WID using the default (`sec`) time unit.
func ValidateHlcWid(wid string, w, z int) bool {
	return ValidateHlcWidWithUnit(wid, w, z, TimeUnitSec)
}

// ValidateHlcWidWithUnit validates an HLC-WID for the specified time unit.
func ValidateHlcWidWithUnit(wid string, w, z int, unit TimeUnit) bool {
	_, err := ParseHlcWidWithUnit(wid, w, z, unit)
	return err == nil
}

// ParseWid extracts timestamp and sequence from a WID using second precision.
func ParseWid(wid string, w, z int) (*ParsedWid, error) {
	return ParseWidWithUnit(wid, w, z, TimeUnitSec)
}

// ParseWidWithUnit extracts components from a WID using the requested time unit.
func ParseWidWithUnit(wid string, w, z int, unit TimeUnit) (*ParsedWid, error) {
	if w <= 0 {
		return nil, ErrInvalidW
	}
	if z < 0 {
		return nil, ErrInvalidZ
	}
	if unit != TimeUnitSec && unit != TimeUnitMs {
		return nil, ErrInvalidTimeUnit
	}
	m := widRe(w, unit).FindStringSubmatch(wid)
	if m == nil {
		return nil, ErrInvalidFormat
	}
	dateStr, timeStr, seqStr, suffix := m[1], m[2], m[3], m[4]
	ts, err := parseCalendar(dateStr, timeStr, unit)
	if err != nil {
		return nil, err
	}
	seq, _ := strconv.Atoi(seqStr)
	var padding *string
	if suffix != "" {
		if !strings.HasPrefix(suffix, "-") {
			return nil, ErrInvalidFormat
		}
		seg := suffix[1:]
		if z == 0 {
			return nil, ErrInvalidFormat
		}
		if !hexReFor(z).MatchString(seg) {
			return nil, ErrInvalidFormat
		}
		padding = &seg
	}
	ms := ts.Nanosecond() / 1_000_000
	return &ParsedWid{Raw: wid, Timestamp: ts, Sequence: seq, Padding: padding, Millisecond: ms}, nil
}

// ParseHlcWid parses an HLC-WID string in second precision.
func ParseHlcWid(wid string, w, z int) (*ParsedHlcWid, error) {
	return ParseHlcWidWithUnit(wid, w, z, TimeUnitSec)
}

// ParseHlcWidWithUnit parses an HLC-WID with the chosen time unit.
func ParseHlcWidWithUnit(wid string, w, z int, unit TimeUnit) (*ParsedHlcWid, error) {
	if w <= 0 {
		return nil, ErrInvalidW
	}
	if z < 0 {
		return nil, ErrInvalidZ
	}
	if unit != TimeUnitSec && unit != TimeUnitMs {
		return nil, ErrInvalidTimeUnit
	}
	m := hlcRe(w, unit).FindStringSubmatch(wid)
	if m == nil {
		return nil, ErrInvalidFormat
	}
	dateStr, timeStr, lcStr, node, suffix := m[1], m[2], m[3], m[4], m[5]
	if !isValidNode(node) {
		return nil, ErrInvalidNode
	}
	ts, err := parseCalendar(dateStr, timeStr, unit)
	if err != nil {
		return nil, err
	}
	lc, _ := strconv.Atoi(lcStr)
	var padding *string
	if suffix != "" {
		if !strings.HasPrefix(suffix, "-") {
			return nil, ErrInvalidFormat
		}
		seg := suffix[1:]
		if z == 0 {
			return nil, ErrInvalidFormat
		}
		if !hexReFor(z).MatchString(seg) {
			return nil, ErrInvalidFormat
		}
		padding = &seg
	}
	ms := ts.Nanosecond() / 1_000_000
	return &ParsedHlcWid{Raw: wid, Timestamp: ts, LogicalCounter: lc, Node: node, Padding: padding, Millisecond: ms}, nil
}

// WidGen maintains monotonic sequence state and optional persistence for WID generation.
type WidGen struct {
	W        int
	Z        int
	TimeUnit TimeUnit
	maxSeq   int
	lastTick int64
	lastSeq  int
	mu       sync.Mutex
}

// NewWidGen creates a generator in seconds precision with W/Z defaults.
func NewWidGen(w, z int) (*WidGen, error) {
	return NewWidGenWithUnit(w, z, TimeUnitSec)
}

// NewWidGenWithUnit creates a generator with a specific time-unit.
func NewWidGenWithUnit(w, z int, unit TimeUnit) (*WidGen, error) {
	if w <= 0 {
		return nil, ErrInvalidW
	}
	if z < 0 {
		return nil, ErrInvalidZ
	}
	if unit != TimeUnitSec && unit != TimeUnitMs {
		return nil, ErrInvalidTimeUnit
	}
	return &WidGen{W: w, Z: z, TimeUnit: unit, maxSeq: pow10(w) - 1, lastSeq: -1}, nil
}

func (g *WidGen) Next() string {
	g.mu.Lock()
	defer g.mu.Unlock()
	now := nowTick(g.TimeUnit)
	tick := now
	if tick <= g.lastTick {
		tick = g.lastTick
	}
	seq := 0
	if tick == g.lastTick {
		seq = g.lastSeq + 1
	}
	if seq > g.maxSeq {
		tick++
		seq = 0
	}
	g.lastTick = tick
	g.lastSeq = seq
	ts := formatTS(tick, g.TimeUnit)
	seqStr := fmt.Sprintf("%0*d", g.W, seq)
	if g.Z > 0 {
		return fmt.Sprintf("%s.%sZ-%s", ts, seqStr, randomHex(g.Z))
	}
	return fmt.Sprintf("%s.%sZ", ts, seqStr)
}

func (g *WidGen) NextN(n int) []string {
	out := make([]string, n)
	for i := range out {
		out[i] = g.Next()
	}
	return out
}

func (g *WidGen) State() (int64, int) {
	g.mu.Lock()
	defer g.mu.Unlock()
	return g.lastTick, g.lastSeq
}

func (g *WidGen) RestoreState(lastTick int64, lastSeq int) {
	g.mu.Lock()
	defer g.mu.Unlock()
	g.lastTick = lastTick
	g.lastSeq = lastSeq
}

// HLCWidGen tracks hybrid logical clock state for HLC-WID generation.
type HLCWidGen struct {
	W        int
	Z        int
	Node     string
	TimeUnit TimeUnit
	maxLC    int
	pt       int64
	lc       int
	mu       sync.Mutex
}

// NewHLCWidGen creates an HLC generator that emits clock-synced IDs.
func NewHLCWidGen(node string, w, z int) (*HLCWidGen, error) {
	return NewHLCWidGenWithUnit(node, w, z, TimeUnitSec)
}

// NewHLCWidGenWithUnit invests the generator with a custom time precision.
func NewHLCWidGenWithUnit(node string, w, z int, unit TimeUnit) (*HLCWidGen, error) {
	if w <= 0 {
		return nil, ErrInvalidW
	}
	if z < 0 {
		return nil, ErrInvalidZ
	}
	if !isValidNode(node) {
		return nil, ErrInvalidNode
	}
	if unit != TimeUnitSec && unit != TimeUnitMs {
		return nil, ErrInvalidTimeUnit
	}
	return &HLCWidGen{W: w, Z: z, Node: node, TimeUnit: unit, maxLC: pow10(w) - 1}, nil
}

func (g *HLCWidGen) rollover() {
	if g.lc > g.maxLC {
		g.pt++
		g.lc = 0
	}
}

// Observe merges remote timestamps into the local hybrid clock.
func (g *HLCWidGen) Observe(remotePT int64, remoteLC int) error {
	if remotePT < 0 || remoteLC < 0 {
		return ErrInvalidRemoteClock
	}
	g.mu.Lock()
	defer g.mu.Unlock()
	now := nowTick(g.TimeUnit)
	newPT := now
	if g.pt > newPT {
		newPT = g.pt
	}
	if remotePT > newPT {
		newPT = remotePT
	}
	switch {
	case newPT == g.pt && newPT == remotePT:
		if g.lc > remoteLC {
			g.lc++
		} else {
			g.lc = remoteLC + 1
		}
	case newPT == g.pt:
		g.lc++
	case newPT == remotePT:
		g.lc = remoteLC + 1
	default:
		g.lc = 0
	}
	g.pt = newPT
	g.rollover()
	return nil
}

// Next generates the next HLC-WID string from the hybrid clock.
func (g *HLCWidGen) Next() string {
	g.mu.Lock()
	defer g.mu.Unlock()
	now := nowTick(g.TimeUnit)
	if now > g.pt {
		g.pt = now
		g.lc = 0
	} else {
		g.lc++
	}
	g.rollover()
	ts := formatTS(g.pt, g.TimeUnit)
	lcStr := fmt.Sprintf("%0*d", g.W, g.lc)
	if g.Z > 0 {
		return fmt.Sprintf("%s.%sZ-%s-%s", ts, lcStr, g.Node, randomHex(g.Z))
	}
	return fmt.Sprintf("%s.%sZ-%s", ts, lcStr, g.Node)
}

// NextN produces a batch of HLC-WIDs for `n` sequential ticks.
func (g *HLCWidGen) NextN(n int) []string {
	out := make([]string, n)
	for i := range out {
		out[i] = g.Next()
	}
	return out
}

// State reports the current physical and logical counter.
func (g *HLCWidGen) State() (int64, int) {
	g.mu.Lock()
	defer g.mu.Unlock()
	return g.pt, g.lc
}

// RestoreState forces the generator to a previous hybrid clock state.
func (g *HLCWidGen) RestoreState(pt int64, lc int) error {
	if pt < 0 || lc < 0 {
		return ErrInvalidRemoteClock
	}
	g.mu.Lock()
	defer g.mu.Unlock()
	g.pt = pt
	g.lc = lc
	return nil
}
