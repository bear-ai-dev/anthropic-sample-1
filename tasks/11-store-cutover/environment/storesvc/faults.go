package main

import (
	"encoding/json"
	"fmt"
	"log"
	"os"
	"strings"
	"sync"
	"time"
)

// Actions a rule can take on a write.
const (
	ActionProceed         = "proceed"
	ActionUnknownCommit   = "unknown_after_commit"
	ActionUnknownRollback = "unknown_after_rollback"
	ActionKillAfterCommit = "kill_client_after_commit"
	ActionStall           = "stall"
)

// Rule matches a write and says what to do with it. Matching is on what the
// write contains, not on how many calls the caller happened to make, so the
// same rule lands in the same place whatever batch size an implementation
// chooses.
type Rule struct {
	ID       string   `json:"id"`
	Op       string   `json:"op"`
	Action   string   `json:"action"`
	Limit    int      `json:"limit"`
	Pid      int      `json:"pid"`
	Key      string   `json:"key"`
	SeqMin   *int64   `json:"global_seq_min"`
	SeqMax   *int64   `json:"global_seq_max"`
	Contains []int64  `json:"contains_global_seq"`
	Values   []string `json:"value_contains"`

	fired int
}

type FaultTable struct {
	mu sync.Mutex
	// pinned is set once an operator installs a plan over the control socket.
	// After that the watched plan file is ignored, so a workspace-writable file
	// cannot take a graded run's faults away.
	pinned bool
	rules  []*Rule
}

func NewFaultTable() *FaultTable { return &FaultTable{} }

func (f *FaultTable) Len() int {
	f.mu.Lock()
	defer f.mu.Unlock()
	return len(f.rules)
}

func (f *FaultTable) pinnedNow() bool {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.pinned
}

// Pin installs a plan and stops the watched file from having any further say.
func (f *FaultTable) Pin(rules []*Rule) {
	f.set(rules)
	f.mu.Lock()
	f.pinned = true
	f.mu.Unlock()
}

func (f *FaultTable) LoadFile(path string) error {
	blob, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	var doc struct {
		Rules []*Rule `json:"rules"`
	}
	if err := json.Unmarshal(blob, &doc); err != nil {
		return err
	}
	f.Set(doc.Rules)
	return nil
}

// smokeRules is the fixed set of faults the box will inject for whoever is
// working on it. One withheld outcome that did commit, one that did not, and one
// writer killed the moment its write became durable: one of each mechanic, so a
// submission can be seen to cope with the *kind* of thing that happens.
//
// It is fixed on purpose, and it is not the schedule a graded run uses. The
// positions are the development ledger's, the ops are the obvious ones, and
// there is no stall in it — nothing here parks a write so a lease can be taken
// off its author mid-flight, and nothing here interleaves two workers. Those
// arrive over the control socket at grading time and cannot be arranged from
// the workspace. A submission that only works against the sequence it was able
// to run for itself is the thing this is meant to stop being enough.
func smokeRules() []*Rule {
	seq := func(n int64) *int64 { return &n }
	return []*Rule{
		{ID: "smoke-withheld-committed", Op: "entry_add",
			Action: ActionUnknownCommit, SeqMin: seq(700), Limit: 1},
		{ID: "smoke-withheld-lost", Op: "entry_add",
			Action: ActionUnknownRollback, SeqMin: seq(900), Limit: 1},
		{ID: "smoke-recycled", Op: "entry_add",
			Action: ActionKillAfterCommit, SeqMin: seq(1100), Limit: 1},
	}
}

// describeSmoke says what the fixed rules are, so the box is honest about what
// it is doing to a submission rather than leaving it to be inferred from a
// failure.
func describeSmoke() string {
	parts := make([]string, 0, 3)
	for _, rule := range smokeRules() {
		at := "any"
		if rule.SeqMin != nil {
			at = fmt.Sprintf("global_seq >= %d", *rule.SeqMin)
		}
		parts = append(parts, fmt.Sprintf("%s: %s on %s at %s",
			rule.ID, rule.Action, rule.Op, at))
	}
	return "[" + strings.Join(parts, "; ") + "]"
}

// watchSmoke turns the fixed smoke faults on and off by the presence of a file.
// Only its presence is read: there is deliberately nothing to author here, so
// the file's contents are ignored and said to be ignored rather than quietly
// dropped.
func (s *Server) watchSmoke(path string) {
	log.Printf("smoke faults: create %s to switch them on, remove it to switch them off", path)
	on := false
	stamp := ""
	for {
		if f := s.faults; f.pinnedNow() {
			log.Printf("smoke faults: an operator plan is in force; %s is ignored", path)
			return
		}
		info, err := os.Stat(path)
		want := err == nil
		now := ""
		if want {
			now = fmt.Sprintf("%d/%d", info.ModTime().UnixNano(), info.Size())
		}
		if want != on {
			on = want
			if on {
				s.faults.Set(smokeRules())
				log.Printf("smoke faults on: %d fixed rule(s) %s", s.faults.Len(),
					describeSmoke())
			} else {
				s.faults.Set(nil)
				log.Printf("smoke faults off")
			}
		}
		// Said every time the file changes, not only when it is first noticed.
		// Someone who writes a plan into it while the faults are already on has
		// otherwise no way to tell that it did nothing, and would spend their
		// time wondering why their own fault never fires.
		if on && now != stamp && info.Size() > 0 {
			log.Printf("smoke faults: %s has contents and they are ignored — only "+
				"whether it exists is read, and the rules are fixed %s",
				path, describeSmoke())
		}
		stamp = now
		time.Sleep(time.Second)
	}
}

// Set applies a plan unless an operator plan has been pinned.
func (f *FaultTable) Set(rules []*Rule) {
	if f.pinnedNow() {
		return
	}
	f.set(rules)
}

func (f *FaultTable) set(rules []*Rule) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.rules = rules
	for _, r := range f.rules {
		r.fired = 0
		if r.Limit == 0 {
			r.Limit = 1
		}
	}
}

// Fired reports how many times each rule has been used, so a run can be
// checked for having actually exercised the faults it meant to.
func (f *FaultTable) Fired() map[string]int {
	f.mu.Lock()
	defer f.mu.Unlock()
	out := map[string]int{}
	for _, r := range f.rules {
		out[r.ID] = r.fired
	}
	return out
}

// writeFacts is what a rule can look at: enough to place a fault precisely,
// nothing about the caller's internal state.
type writeFacts struct {
	Op         string
	Pid        int
	Key        string
	Value      string
	GlobalSeqs []int64
}

func (f *FaultTable) Match(w writeFacts) (string, string) {
	f.mu.Lock()
	defer f.mu.Unlock()
	for _, r := range f.rules {
		if r.fired >= r.Limit || r.Op != w.Op {
			continue
		}
		if r.Pid != 0 && r.Pid != w.Pid {
			continue
		}
		if r.Key != "" && r.Key != w.Key {
			continue
		}
		if len(r.Values) > 0 && !containsAny(w.Value, r.Values) {
			continue
		}
		if r.SeqMin != nil && !anyAtLeast(w.GlobalSeqs, *r.SeqMin) {
			continue
		}
		if r.SeqMax != nil && !anyAtMost(w.GlobalSeqs, *r.SeqMax) {
			continue
		}
		if len(r.Contains) > 0 && !anyOf(w.GlobalSeqs, r.Contains) {
			continue
		}
		r.fired++
		log.Printf("rule %s fires %s on %s pid=%d", r.ID, r.Action, w.Op, w.Pid)
		return r.Action, r.ID
	}
	return ActionProceed, ""
}

func containsAny(haystack string, needles []string) bool {
	for _, n := range needles {
		if len(n) <= len(haystack) && indexOf(haystack, n) >= 0 {
			return true
		}
	}
	return false
}

func indexOf(haystack, needle string) int {
	for i := 0; i+len(needle) <= len(haystack); i++ {
		if haystack[i:i+len(needle)] == needle {
			return i
		}
	}
	return -1
}

func anyAtLeast(values []int64, bound int64) bool {
	for _, v := range values {
		if v >= bound {
			return true
		}
	}
	return false
}

func anyAtMost(values []int64, bound int64) bool {
	for _, v := range values {
		if v <= bound {
			return true
		}
	}
	return false
}

func anyOf(values, wanted []int64) bool {
	for _, v := range values {
		for _, w := range wanted {
			if v == w {
				return true
			}
		}
	}
	return false
}

// StallGate holds writes inside the store call until they are released. A
// parked caller is not sleeping and not racing: it is stopped at a point of the
// operator's choosing with everything it believed about the world still intact.
//
// There are as many slots as the operator arms, each named, so two workers can
// be held in two different writes at the same time and let go independently.
// That is what a takeover looks like from the outside: one worker frozen inside
// a write it thinks it is entitled to make, another one carrying on.
type StallGate struct {
	mu    sync.Mutex
	slots map[string]*stallSlot
	// forced is the slot a plan rule's stall action parks in when the operator
	// named no slot of its own.
	forced *stallSlot
}

type stallSlot struct {
	id       string
	pid      int
	op       string
	value    []string
	armed    bool
	parked   int
	released int
	release  chan struct{}
}

func NewStallGate() *StallGate {
	gate := &StallGate{slots: map[string]*stallSlot{}}
	gate.forced = gate.slot("forced")
	return gate
}

// slot finds or makes a slot. Called with the lock held, or during setup.
func (g *StallGate) slot(id string) *stallSlot {
	if found, ok := g.slots[id]; ok {
		return found
	}
	made := &stallSlot{id: id, release: make(chan struct{})}
	g.slots[id] = made
	return made
}

// Arm makes a slot ready to catch one write. A slot armed twice starts again
// with a fresh channel, so anything already parked in it stays parked until
// that older channel is closed.
func (g *StallGate) Arm(id string, pid int, op string, value []string) {
	if id == "" {
		id = "forced"
	}
	g.mu.Lock()
	defer g.mu.Unlock()
	target := g.slot(id)
	target.pid = pid
	target.op = op
	target.value = value
	target.armed = true
	target.release = make(chan struct{})
}

// Park holds the write if some armed slot asked for it, or if a plan rule
// forced it. The slot disarms behind the write it caught, so the caller makes
// progress once released and a later write of the same shape runs freely.
func (g *StallGate) Park(pid int, op string, value string, forced bool) bool {
	g.mu.Lock()
	var caught *stallSlot
	for _, candidate := range g.slots {
		if !candidate.armed {
			continue
		}
		if candidate.pid != 0 && candidate.pid != pid {
			continue
		}
		if candidate.op != "" && candidate.op != op {
			continue
		}
		if len(candidate.value) > 0 && !containsAny(value, candidate.value) {
			continue
		}
		caught = candidate
		break
	}
	if caught == nil && forced {
		caught = g.forced
	}
	if caught == nil {
		g.mu.Unlock()
		return false
	}
	caught.armed = false
	caught.parked++
	channel := caught.release
	g.mu.Unlock()

	<-channel

	g.mu.Lock()
	caught.parked--
	caught.released++
	g.mu.Unlock()
	return true
}

// Release lets a slot's parked write go. An empty id releases every slot, which
// is what a reset does.
//
// The channel is replaced as well as closed. Whoever is already waiting holds
// the old one and goes free; the slot is left able to catch something again,
// which matters for the slot a plan rule's stall parks in, since nothing arms
// that one explicitly.
func (g *StallGate) Release(id string) {
	g.mu.Lock()
	defer g.mu.Unlock()
	for _, candidate := range g.slots {
		if id != "" && candidate.id != id {
			continue
		}
		candidate.armed = false
		close(candidate.release)
		candidate.release = make(chan struct{})
	}
}

// Stats reports each slot, and the totals across all of them so a caller that
// armed one slot can go on asking the same question it always did.
func (g *StallGate) Stats() map[string]any {
	g.mu.Lock()
	defer g.mu.Unlock()
	slots := map[string]any{}
	parked, released, armed := 0, 0, false
	for id, candidate := range g.slots {
		slots[id] = map[string]any{
			"parked": candidate.parked, "released": candidate.released,
			"armed": candidate.armed,
		}
		parked += candidate.parked
		released += candidate.released
		armed = armed || candidate.armed
	}
	return map[string]any{
		"parked": parked, "released": released, "armed": armed, "slots": slots,
	}
}
