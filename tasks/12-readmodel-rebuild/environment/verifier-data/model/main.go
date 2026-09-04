// projfold is the verifier's independent model of the rebuild specification.
//
// It exists so that "is generation v2 correct?" can be answered without asking
// generation v2, or anything that built it. Its only input is the canonical
// delivery log; it shares no code, no data structure and no language with the
// service. The service folds the log into Gel rows with EdgeQL upserts; this
// folds it into Go maps in one pass and sorts at the end. The service gets its
// New York dates from ICU; this derives them from the daylight-saving rule and
// checks that against tzdata.
//
// Usage:
//
//	projfold fold  -truth F -battery B [-seqs SPEC] [-generation v1|v2] -out O
//	projfold check
//
// SPEC is a comma-separated list of ranges: "1-1200,1205". Deliveries whose
// position is outside the set are ignored, which is how the verifier asks
// "given that the service claims to have folded exactly these positions, what
// should it be holding?".
package main

import (
	"bufio"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"sort"
	"strconv"
	"strings"
	"time"
)

type Delivery struct {
	Seq        int64    `json:"seq"`
	EventID    string   `json:"event_id"`
	OrgID      string   `json:"org_id"`
	UserID     string   `json:"user_id"`
	Tags       []string `json:"tags"`
	OccurredAt string   `json:"occurred_at"`
	SchemaVer  int      `json:"schema_ver"`
}

type FeedRow struct {
	Seq        int64    `json:"seq"`
	EventID    string   `json:"event_id"`
	OccurredAt string   `json:"occurred_at"`
	Tags       []string `json:"tags"`
	instant    time.Time
}

type bucketKey struct {
	name string
	day  string
}

// OrgBucket is what generation v2 keeps per organisation and day: how many
// deliveries landed, and how many different people they came from. The second
// is not recoverable from the first in either direction, so both are carried.
type OrgBucket struct {
	Count  int64 `json:"count"`
	Actors int64 `json:"actors"`
	// Kept so the count of people can be maintained rather than recomputed,
	// and so a mismatch can say who is missing.
	People []string `json:"people"`
	seen   map[string]bool
}

// TagBucket is what generation v2 keeps per tag and day: how many positions
// carried the tag, and which of them is newest. Newest is by the instant a
// delivery reports and then by position -- the order the feed is read in, and
// not the order deliveries arrive in.
type TagBucket struct {
	Count      int64  `json:"count"`
	NewestID   string `json:"newest_event_id"`
	NewestAt   string `json:"newest_at"`
	NewestSeq  int64  `json:"newest_seq"`
	newestWhen time.Time
}

// newer reports whether a delivery displaces the one this bucket points at.
func (b *TagBucket) newer(when time.Time, seq int64) bool {
	if b.NewestID == "" {
		return true
	}
	if !when.Equal(b.newestWhen) {
		return when.After(b.newestWhen)
	}
	return seq > b.NewestSeq
}

// Model is the folded log. Maps and slices, resolved in memory; the service
// keeps the same information as rows in three Gel tables.
type Model struct {
	feed map[string][]FeedRow
	org  map[bucketKey]*OrgBucket
	tag  map[bucketKey]*TagBucket
	seen map[int64]bool
	seqs []int64
}

func NewModel() *Model {
	return &Model{
		feed: map[string][]FeedRow{},
		org:  map[bucketKey]*OrgBucket{},
		tag:  map[bucketKey]*TagBucket{},
		seen: map[int64]bool{},
	}
}

// Fold applies the log in delivery order. A position already seen contributes
// nothing at all: the first delivery of a position is authoritative, including
// the event_id its feed row carries.
func (m *Model) Fold(log []Delivery, want func(int64) bool, generation string) error {
	for _, d := range log {
		if !want(d.Seq) {
			continue
		}
		if m.seen[d.Seq] {
			continue
		}
		m.seen[d.Seq] = true
		m.seqs = append(m.seqs, d.Seq)

		instant, err := time.Parse(time.RFC3339, d.OccurredAt)
		if err != nil {
			return fmt.Errorf("seq %d: bad occurred_at %q: %w", d.Seq, d.OccurredAt, err)
		}

		day := NewYorkDate(instant)
		if generation == "v1" {
			day = UTCDate(instant)
		}

		tags := d.Tags
		if tags == nil {
			tags = []string{}
		}
		m.feed[d.UserID] = append(m.feed[d.UserID], FeedRow{
			Seq:        d.Seq,
			EventID:    d.EventID,
			OccurredAt: instant.UTC().Format("2006-01-02T15:04:05.000Z"),
			Tags:       tags,
			instant:    instant.UTC(),
		})

		orgKey := bucketKey{d.OrgID, day}
		bucket := m.org[orgKey]
		if bucket == nil {
			bucket = &OrgBucket{seen: map[string]bool{}}
			m.org[orgKey] = bucket
		}
		bucket.Count++
		if !bucket.seen[d.UserID] {
			bucket.seen[d.UserID] = true
			bucket.Actors++
			bucket.People = append(bucket.People, d.UserID)
		}

		// A position that carries a tag twice counts once for that tag.
		distinct := map[string]bool{}
		for _, t := range tags {
			distinct[t] = true
		}
		for t := range distinct {
			key := bucketKey{t, day}
			tb := m.tag[key]
			if tb == nil {
				tb = &TagBucket{}
				m.tag[key] = tb
			}
			tb.Count++
			if tb.newer(instant.UTC(), d.Seq) {
				tb.NewestID = d.EventID
				tb.NewestAt = instant.UTC().Format("2006-01-02T15:04:05.000Z")
				tb.NewestSeq = d.Seq
				tb.newestWhen = instant.UTC()
			}
		}
	}

	for _, bucket := range m.org {
		sort.Strings(bucket.People)
	}

	// Newest first; ties broken by the later position.
	for user := range m.feed {
		rows := m.feed[user]
		sort.Slice(rows, func(i, j int) bool {
			if !rows[i].instant.Equal(rows[j].instant) {
				return rows[i].instant.After(rows[j].instant)
			}
			return rows[i].Seq > rows[j].Seq
		})
		m.feed[user] = rows
	}
	sort.Slice(m.seqs, func(i, j int) bool { return m.seqs[i] < m.seqs[j] })
	return nil
}

type BatteryQuery struct {
	ID     string `json:"id"`
	Kind   string `json:"kind"`
	UserID string `json:"user_id,omitempty"`
	Limit  int    `json:"limit,omitempty"`
	OrgID  string `json:"org_id,omitempty"`
	Tag    string `json:"tag,omitempty"`
	Day    string `json:"day,omitempty"`
}

type BatteryAnswer struct {
	ID       string    `json:"id"`
	Kind     string    `json:"kind"`
	Items    []FeedRow `json:"items,omitempty"`
	Count    int64     `json:"count"`
	Actors   *int64    `json:"actors,omitempty"`
	NewestID string    `json:"newest_event_id,omitempty"`
	NewestAt string    `json:"newest_at,omitempty"`
}

type Output struct {
	Generation string               `json:"generation"`
	Seqs       []int64              `json:"seqs"`
	SeqCount   int                  `json:"seq_count"`
	Feed       map[string][]FeedRow `json:"feed"`
	Org        map[string]OrgBucket `json:"org"`
	Tag        map[string]TagBucket `json:"tag"`
	Battery    []BatteryAnswer      `json:"battery"`
}

func (m *Model) Answer(q BatteryQuery) BatteryAnswer {
	switch q.Kind {
	case "feed":
		rows := m.feed[q.UserID]
		limit := q.Limit
		if limit <= 0 || limit > len(rows) {
			limit = len(rows)
		}
		out := make([]FeedRow, 0, limit)
		out = append(out, rows[:limit]...)
		return BatteryAnswer{ID: q.ID, Kind: q.Kind, Items: out, Count: int64(len(out))}
	case "org":
		answer := BatteryAnswer{ID: q.ID, Kind: q.Kind}
		if bucket := m.org[bucketKey{q.OrgID, q.Day}]; bucket != nil {
			answer.Count = bucket.Count
			actors := bucket.Actors
			answer.Actors = &actors
		} else {
			zero := int64(0)
			answer.Actors = &zero
		}
		return answer
	case "tag":
		answer := BatteryAnswer{ID: q.ID, Kind: q.Kind}
		if bucket := m.tag[bucketKey{q.Tag, q.Day}]; bucket != nil {
			answer.Count = bucket.Count
			answer.NewestID = bucket.NewestID
			answer.NewestAt = bucket.NewestAt
		}
		return answer
	}
	return BatteryAnswer{ID: q.ID, Kind: "unknown"}
}

func readLog(path string) ([]Delivery, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()

	var out []Delivery
	sc := bufio.NewScanner(f)
	sc.Buffer(make([]byte, 0, 1<<20), 1<<20)
	for sc.Scan() {
		line := strings.TrimSpace(sc.Text())
		if line == "" {
			continue
		}
		var d Delivery
		if err := json.Unmarshal([]byte(line), &d); err != nil {
			return nil, fmt.Errorf("bad log line: %w", err)
		}
		out = append(out, d)
	}
	return out, sc.Err()
}

func parseSpec(spec string) (func(int64) bool, error) {
	if strings.TrimSpace(spec) == "" {
		return func(int64) bool { return true }, nil
	}
	allowed := map[int64]bool{}
	for _, part := range strings.Split(spec, ",") {
		part = strings.TrimSpace(part)
		if part == "" {
			continue
		}
		if lo, hi, ok := strings.Cut(part, "-"); ok {
			a, err := strconv.ParseInt(strings.TrimSpace(lo), 10, 64)
			if err != nil {
				return nil, err
			}
			b, err := strconv.ParseInt(strings.TrimSpace(hi), 10, 64)
			if err != nil {
				return nil, err
			}
			for s := a; s <= b; s++ {
				allowed[s] = true
			}
			continue
		}
		v, err := strconv.ParseInt(part, 10, 64)
		if err != nil {
			return nil, err
		}
		allowed[v] = true
	}
	return func(s int64) bool { return allowed[s] }, nil
}

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintln(os.Stderr, "usage: projfold fold|check ...")
		os.Exit(2)
	}

	switch os.Args[1] {
	case "check":
		if err := selfCheck(); err != nil {
			fmt.Fprintln(os.Stderr, "FAIL:", err)
			os.Exit(1)
		}
		fmt.Println("day-bucket rule agrees with tzdata over 2024-2026")
		return

	case "fold":
		fs := flag.NewFlagSet("fold", flag.ExitOnError)
		truth := fs.String("truth", "", "canonical delivery log (jsonl)")
		battery := fs.String("battery", "", "battery of queries (json)")
		seqs := fs.String("seqs", "", "positions to fold, e.g. 1-1200,1205")
		generation := fs.String("generation", "v2", "v1 buckets in UTC, v2 in New York")
		out := fs.String("out", "-", "output path")
		_ = fs.Parse(os.Args[2:])

		if err := selfCheck(); err != nil {
			fmt.Fprintln(os.Stderr, "FAIL:", err)
			os.Exit(1)
		}

		log, err := readLog(*truth)
		if err != nil {
			fmt.Fprintln(os.Stderr, "FAIL:", err)
			os.Exit(1)
		}
		want, err := parseSpec(*seqs)
		if err != nil {
			fmt.Fprintln(os.Stderr, "FAIL:", err)
			os.Exit(1)
		}

		m := NewModel()
		if err := m.Fold(log, want, *generation); err != nil {
			fmt.Fprintln(os.Stderr, "FAIL:", err)
			os.Exit(1)
		}

		var queries []BatteryQuery
		if *battery != "" {
			raw, err := os.ReadFile(*battery)
			if err != nil {
				fmt.Fprintln(os.Stderr, "FAIL:", err)
				os.Exit(1)
			}
			if err := json.Unmarshal(raw, &queries); err != nil {
				fmt.Fprintln(os.Stderr, "FAIL:", err)
				os.Exit(1)
			}
		}

		result := Output{
			Generation: *generation,
			Seqs:       m.seqs,
			SeqCount:   len(m.seqs),
			Feed:       m.feed,
			Org:        map[string]OrgBucket{},
			Tag:        map[string]TagBucket{},
		}
		if result.Seqs == nil {
			result.Seqs = []int64{}
		}
		for k, v := range m.org {
			result.Org[k.name+"|"+k.day] = *v
		}
		for k, v := range m.tag {
			result.Tag[k.name+"|"+k.day] = *v
		}
		for _, q := range queries {
			result.Battery = append(result.Battery, m.Answer(q))
		}

		enc, err := json.MarshalIndent(result, "", " ")
		if err != nil {
			fmt.Fprintln(os.Stderr, "FAIL:", err)
			os.Exit(1)
		}
		if *out == "-" {
			os.Stdout.Write(enc)
			return
		}
		if err := os.WriteFile(*out, enc, 0o600); err != nil {
			fmt.Fprintln(os.Stderr, "FAIL:", err)
			os.Exit(1)
		}
		return
	}

	fmt.Fprintln(os.Stderr, "unknown command", os.Args[1])
	os.Exit(2)
}
