package recurrence

import (
	"errors"
	"fmt"
	"time"
)

// Unit names the calendar step a series repeats on.
type Unit string

// The three units the repeat configuration allows.
const (
	UnitDay   Unit = "day"
	UnitWeek  Unit = "week"
	UnitMonth Unit = "month"
)

// EndRule names how a series stops.
type EndRule string

// The two end rules the repeat configuration allows.
const (
	EndAfterOccurrences EndRule = "afterOccurrences"
	EndOnDate           EndRule = "onDate"
)

// slotCeiling bounds any walk of the lattice. A configuration cannot be
// trusted not to describe an unbounded series -- an onDate rule with a
// far-future date and a daily interval of one is enough -- and a request that
// wedges the process is worse than a request that is refused. No legitimate
// series in this system comes near it.
const slotCeiling = 600

// ErrRunaway is returned when a walk hits the ceiling, which means the
// configuration does not describe a finite series.
var ErrRunaway = errors.New("recurrence: repeat configuration does not terminate")

// Config is everything the lattice depends on, resolved out of the stored
// repeat configuration: a zone rather than a zone name, a local date rather
// than a timestamp.
type Config struct {
	Unit         Unit
	Interval     int
	SelectedDays []int
	Location     *time.Location

	EndRule EndRule
	// Count applies when EndRule is EndAfterOccurrences.
	Count int
	// EndDate applies when EndRule is EndOnDate, and is a calendar date in
	// Location rather than an instant: a series ends on a day, and which day
	// an instant falls on depends on the zone.
	EndDate    LocalDate
	HasEndDate bool
}

// Validate reports a configuration that cannot produce a series at all.
func (c Config) Validate() error {
	if c.Interval < 1 {
		return fmt.Errorf("recurrence: repeat interval %d is not at least 1", c.Interval)
	}
	switch c.Unit {
	case UnitDay, UnitWeek, UnitMonth:
	default:
		return fmt.Errorf("recurrence: unknown repeat unit %q", c.Unit)
	}
	switch c.EndRule {
	case EndAfterOccurrences:
		if c.Count < 1 {
			return fmt.Errorf("recurrence: occurrence count %d is not at least 1", c.Count)
		}
	case EndOnDate:
		if !c.HasEndDate {
			return errors.New("recurrence: onDate rule with no end date")
		}
	default:
		return fmt.Errorf("recurrence: unknown end rule %q", c.EndRule)
	}
	return nil
}

// Slot is one place in the series: the local calendar date the rule put there,
// and the instant that date and the series' time of day resolve to.
type Slot struct {
	Date       LocalDate
	Instant    time.Time
	Resolution Resolution
}

// lattice walks the local dates a configuration occupies, in ascending order,
// starting from an anchor. It is a cursor rather than a slice because the two
// callers stop on different conditions: creating a series stops on the
// configuration's end rule, extending one stops on a count of dates past a
// date it already holds.
type lattice struct {
	cfg    Config
	anchor LocalDate

	// weekly state: the Sunday that starts the current week, and where we are
	// in that week's selected days.
	weekStart LocalDate
	weekdays  []int
	dayIndex  int

	// daily and monthly state: how many strides have been taken.
	step int

	visited int
}

func newLattice(cfg Config, anchor LocalDate) *lattice {
	l := &lattice{cfg: cfg, anchor: anchor}
	if cfg.Unit == UnitWeek {
		l.weekdays = NormaliseWeekdays(cfg.SelectedDays)
		if len(l.weekdays) == 0 {
			// A weekly series that names no days repeats on the anchor's own
			// day of the week.
			l.weekdays = []int{anchor.Weekday()}
		}
		l.weekStart = SundayOnOrBefore(anchor)
	}
	return l
}

// next yields the following date on the lattice. It returns false only when
// the ceiling has been reached.
func (l *lattice) next() (LocalDate, bool) {
	for {
		if l.visited >= slotCeiling {
			return LocalDate{}, false
		}
		l.visited++

		switch l.cfg.Unit {
		case UnitDay:
			d := l.anchor.AddDays(l.step * l.cfg.Interval)
			l.step++
			return d, true

		case UnitMonth:
			// Always measured from the anchor, never from the previous
			// result, so that a February clamp does not become permanent.
			d := AddMonthsClamped(l.anchor, l.step*l.cfg.Interval)
			l.step++
			return d, true

		case UnitWeek:
			if l.dayIndex >= len(l.weekdays) {
				l.dayIndex = 0
				l.weekStart = l.weekStart.AddDays(7 * l.cfg.Interval)
			}
			d := l.weekStart.AddDays(l.weekdays[l.dayIndex])
			l.dayIndex++
			// The anchor's own week is week zero even when the anchor is not a
			// Sunday, so some of that week's selected days fall before the
			// series begins. They are skipped rather than emitted: a series
			// does not start before its start date.
			if d.Before(l.anchor) {
				continue
			}
			return d, true

		default:
			return LocalDate{}, false
		}
	}
}

// Dates returns the local dates a configuration puts in a series, applying its
// own end rule.
func Dates(cfg Config, anchor LocalDate) ([]LocalDate, error) {
	if err := cfg.Validate(); err != nil {
		return nil, err
	}
	l := newLattice(cfg, anchor)
	out := make([]LocalDate, 0, 16)
	for {
		if cfg.EndRule == EndAfterOccurrences && len(out) >= cfg.Count {
			return out, nil
		}
		d, ok := l.next()
		if !ok {
			return nil, ErrRunaway
		}
		if cfg.EndRule == EndOnDate {
			// The end date is inclusive, and it is compared as a calendar date
			// in the series' zone. Comparing instants instead makes the last
			// day of a series depend on the time of day it happens to run at.
			if d.After(cfg.EndDate) {
				return out, nil
			}
		}
		out = append(out, d)
	}
}

// DatesFilling returns the next n dates on the lattice that the series does
// not already hold, walking from the anchor and ignoring the configuration's
// end rule.
//
// Ignoring the end rule is deliberate: extending a series is the act of going
// past the point it was set to stop at. Neither of the other two inputs may be
// ignored, and each is a separate way to get this wrong.
//
// The anchor decides which sequence the continuation belongs to. For a monthly
// series clamped into February, the lattice measured from the original anchor
// and the lattice measured from the last occurrence are different sequences --
// the first continues on the 31st, the second on the 28th.
//
// `held` decides which of that sequence's dates are still free, and it is a
// set rather than a high-water mark because a series need not be contiguous.
// An occurrence deleted from the middle, or dropped by a regenerate that moved
// the pattern off it, leaves a date on the lattice that nothing occupies, and
// that date comes before anything past the latest occurrence. Skipping ahead
// to the end instead produces a different set of dates and quietly leaves the
// hole behind.
func DatesFilling(cfg Config, anchor LocalDate, held map[string]bool, n int) ([]LocalDate, error) {
	if n < 1 {
		return nil, nil
	}
	// Only the shape of the lattice matters here, so an end rule that would
	// stop the walk early is replaced rather than validated.
	walk := cfg
	walk.EndRule = EndAfterOccurrences
	walk.Count = 1
	if err := walk.Validate(); err != nil {
		return nil, err
	}

	// A private copy, so that a date this walk claims cannot be claimed twice
	// and the caller's own view of the series is not rewritten underneath it.
	taken := make(map[string]bool, len(held)+n)
	for k := range held {
		taken[k] = true
	}

	l := newLattice(cfg, anchor)
	out := make([]LocalDate, 0, n)
	for len(out) < n {
		d, ok := l.next()
		if !ok {
			return nil, ErrRunaway
		}
		if taken[d.String()] {
			continue
		}
		taken[d.String()] = true
		out = append(out, d)
	}
	return out, nil
}

// Materialise attaches instants to a list of local dates.
func Materialise(dates []LocalDate, secondsFromMidnight int, loc *time.Location) []Slot {
	out := make([]Slot, 0, len(dates))
	for _, d := range dates {
		inst, res := InstantAt(d, secondsFromMidnight, loc)
		out = append(out, Slot{Date: d, Instant: inst, Resolution: res})
	}
	return out
}

// Slots is the whole of creating a series: the dates its rule occupies, turned
// into instants.
func Slots(cfg Config, anchor LocalDate, secondsFromMidnight int) ([]Slot, error) {
	dates, err := Dates(cfg, anchor)
	if err != nil {
		return nil, err
	}
	return Materialise(dates, secondsFromMidnight, cfg.Location), nil
}

// Continue is the whole of extending a series.
func Continue(cfg Config, anchor LocalDate, held map[string]bool, n, secondsFromMidnight int) ([]Slot, error) {
	dates, err := DatesFilling(cfg, anchor, held, n)
	if err != nil {
		return nil, err
	}
	return Materialise(dates, secondsFromMidnight, cfg.Location), nil
}
