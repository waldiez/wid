package wid

import "testing"

// TestWidGenMonotonic verifies generated WIDs stay strictly increasing.
func TestWidGenMonotonic(t *testing.T) {
	g, _ := NewWidGen(4, 0)
	a := g.Next()
	b := g.Next()
	if a >= b {
		t.Errorf("expected %s < %s", a, b)
	}
}

// TestWidGenWithPadding ensures generators with padding produce values that still validate.
func TestWidGenWithPadding(t *testing.T) {
	g, _ := NewWidGen(4, 6)
	w := g.Next()
	if !ValidateWid(w, 4, 6) {
		t.Errorf("generated WID %q failed validation", w)
	}
}

// TestWidValidateConformance sweeps valid and invalid WIDs through ValidateWid.
func TestWidValidateConformance(t *testing.T) {
	cases := []struct {
		wid   string
		w, z  int
		valid bool
	}{
		{"20260212T091530.0000Z", 4, 0, true},
		{"20260212T091530.0042Z", 4, 0, true},
		{"20260212T091530.0042Z-a3f91c", 4, 6, true},
		{"20260212T091530.9999Z", 4, 0, true},
		{"20260101T000000.0000Z", 4, 0, true},
		{"20261231T235959.0000Z", 4, 0, true},
		{"waldiez", 4, 6, false},
		{"20260212T091530.0000", 4, 0, false},
		{"20260212T091530.0000Z-A3F91C", 4, 6, false},
		{"20261312T091530.0000Z", 4, 0, false},
		{"20260232T091530.0000Z", 4, 0, false},
		{"20260212T091530.0000Z-node01", 4, 0, false},
	}
	for _, tc := range cases {
		got := ValidateWid(tc.wid, tc.w, tc.z)
		if got != tc.valid {
			t.Errorf("ValidateWid(%q, %d, %d) = %v, want %v", tc.wid, tc.w, tc.z, got, tc.valid)
		}
	}
}

// TestWidMsValidateAndParse checks millisecond WIDs stay valid and parse back their ms value.
func TestWidMsValidateAndParse(t *testing.T) {
	id := "20260212T091530123.0042Z-a3f91c"
	if !ValidateWidWithUnit(id, 4, 6, TimeUnitMs) {
		t.Fatalf("expected ms wid valid: %s", id)
	}
	p, err := ParseWidWithUnit(id, 4, 6, TimeUnitMs)
	if err != nil {
		t.Fatal(err)
	}
	if p.Millisecond != 123 {
		t.Fatalf("expected ms=123, got %d", p.Millisecond)
	}
}

// TestHlcWidValidateConformance exercises HLC validation acceptance and rejection cases.
func TestHlcWidValidateConformance(t *testing.T) {
	cases := []struct {
		wid   string
		w, z  int
		valid bool
	}{
		{"20260212T091530.0000Z-node01", 4, 0, true},
		{"20260212T091530.0042Z-node01-a3f91c", 4, 6, true},
		{"20260212T091530.0000Z-my_node_01", 4, 0, true},
		{"20260212T091530.0000Z-Server42ABC", 4, 0, true},
		{"20260212T091530.0000Z", 4, 0, false},
		{"20260212T091530.0000Z-node-01", 4, 0, false},
	}
	for _, tc := range cases {
		got := ValidateHlcWid(tc.wid, tc.w, tc.z)
		if got != tc.valid {
			t.Errorf("ValidateHlcWid(%q, %d, %d) = %v, want %v", tc.wid, tc.w, tc.z, got, tc.valid)
		}
	}
}

// TestParseWid confirms sequence and padding members after parsing a WID.
func TestParseWid(t *testing.T) {
	p, err := ParseWid("20260212T091530.0042Z-a3f91c", 4, 6)
	if err != nil {
		t.Fatal(err)
	}
	if p.Sequence != 42 {
		t.Errorf("seq = %d, want 42", p.Sequence)
	}
	if p.Padding == nil || *p.Padding != "a3f91c" {
		t.Error("padding mismatch")
	}
}

// TestParseHlcWid asserts logical counter and node fields for HLC-WIDs.
func TestParseHlcWid(t *testing.T) {
	p, err := ParseHlcWid("20260212T091530.0042Z-node01-a3f91c", 4, 6)
	if err != nil {
		t.Fatal(err)
	}
	if p.LogicalCounter != 42 {
		t.Errorf("lc = %d, want 42", p.LogicalCounter)
	}
	if p.Node != "node01" {
		t.Errorf("node = %s, want node01", p.Node)
	}
}

// TestParseHlcWidMs verifies millisecond-precision HLC parsing includes ms and lc values.
func TestParseHlcWidMs(t *testing.T) {
	p, err := ParseHlcWidWithUnit("20260212T091530123.0042Z-node01-a3f91c", 4, 6, TimeUnitMs)
	if err != nil {
		t.Fatal(err)
	}
	if p.LogicalCounter != 42 {
		t.Errorf("lc = %d, want 42", p.LogicalCounter)
	}
	if p.Millisecond != 123 {
		t.Errorf("ms = %d, want 123", p.Millisecond)
	}
}

// TestHLCWidGenMonotonic ensures the hybrid logical clock keeps growing across Next calls.
func TestHLCWidGenMonotonic(t *testing.T) {
	g, _ := NewHLCWidGen("node01", 4, 0)
	a := g.Next()
	b := g.Next()
	if a >= b {
		t.Errorf("expected %s < %s", a, b)
	}
}

// TestHLCWidGenObserve confirms Observe merges remote timestamps without regressing pt.
func TestHLCWidGenObserve(t *testing.T) {
	g, _ := NewHLCWidGen("node01", 4, 0)
	g.Observe(10, 5)
	pt, _ := g.State()
	if pt < 10 {
		t.Errorf("pt = %d, expected >= 10", pt)
	}
}

// TestInvalidParams checks generators reject invalid W/Z and node inputs early.
func TestInvalidParams(t *testing.T) {
	_, err := NewWidGen(0, 0)
	if err != ErrInvalidW {
		t.Errorf("expected ErrInvalidW, got %v", err)
	}
	_, err = NewHLCWidGen("bad-node", 4, 0)
	if err != ErrInvalidNode {
		t.Errorf("expected ErrInvalidNode, got %v", err)
	}
}
