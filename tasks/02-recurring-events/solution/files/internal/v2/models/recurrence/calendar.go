// Package recurrence turns a repeat configuration into the calendar dates a
// series occupies, and turns those dates into instants in the series' own time
// zone.
//
// The two halves are kept apart on purpose. A recurrence rule is a statement
// about local calendar dates -- "the 31st of every month", "every Sunday and
// Wednesday at seven" -- and only becomes a set of instants once a zone and a
// time of day are applied to it. Doing the arithmetic on instants instead is
// what produces the familiar faults: a weekly series that slips an hour when
// its zone changes offset, or a monthly series that overshoots the end of
// February and never lands on the 31st again.
//
// Nothing in this package imports the models package, so that models can
// import it.
package recurrence

import (
	"fmt"
	"time"
)

// LocalDate is a calendar date with no time of day and no zone attached. It is
// the unit a recurrence rule is written in.
type LocalDate struct {
	Year  int
	Month int
	Day   int
}

// DateIn reads the calendar date an instant falls on in a given zone.
func DateIn(t time.Time, loc *time.Location) LocalDate {
	l := t.In(loc)
	return LocalDate{Year: l.Year(), Month: int(l.Month()), Day: l.Day()}
}

// String renders the date as YYYY-MM-DD.
func (d LocalDate) String() string {
	return fmt.Sprintf("%04d-%02d-%02d", d.Year, d.Month, d.Day)
}

// Compare orders two dates: negative if d is earlier, zero if equal.
func (d LocalDate) Compare(o LocalDate) int {
	if d.Year != o.Year {
		return d.Year - o.Year
	}
	if d.Month != o.Month {
		return d.Month - o.Month
	}
	return d.Day - o.Day
}

// Before reports whether d falls earlier in the calendar than o.
func (d LocalDate) Before(o LocalDate) bool { return d.Compare(o) < 0 }

// After reports whether d falls later in the calendar than o.
func (d LocalDate) After(o LocalDate) bool { return d.Compare(o) > 0 }

// Equal reports whether two dates are the same calendar day.
func (d LocalDate) Equal(o LocalDate) bool { return d.Compare(o) == 0 }

// midday turns a date into a time only so that Go's calendar can be consulted
// about it. Noon is chosen because it is hours away from any offset change in
// every zone in the database, so a question about which day it is can never
// come back with a daylight-saving answer.
func (d LocalDate) midday() time.Time {
	return time.Date(d.Year, time.Month(d.Month), d.Day, 12, 0, 0, 0, time.UTC)
}

// AddDays moves the date by whole days, rolling over months and years.
func (d LocalDate) AddDays(n int) LocalDate {
	t := d.midday().AddDate(0, 0, n)
	return LocalDate{Year: t.Year(), Month: int(t.Month()), Day: t.Day()}
}

// Weekday reports the day of the week with Sunday as 0, which is the
// convention selectedDays is written in.
func (d LocalDate) Weekday() int {
	return int(d.midday().Weekday())
}

// SundayOnOrBefore returns the start of the week the date falls in, weeks
// being taken to begin on Sunday.
func SundayOnOrBefore(d LocalDate) LocalDate {
	return d.AddDays(-d.Weekday())
}

// DaysInMonth reports how many days a given month has, leap years included.
//
// Day zero of the following month is the last day of this one; Go normalises
// out-of-range components, so this needs no leap-year rule of its own and
// cannot disagree with the calendar Go uses everywhere else.
func DaysInMonth(year, month int) int {
	return time.Date(year, time.Month(month+1), 0, 12, 0, 0, 0, time.UTC).Day()
}

// AddMonthsClamped advances a monthly anchor by n months, keeping the anchor's
// day of the month and clamping to the last day of a month too short to hold
// it.
//
// The anchor is passed in every time rather than being carried forward from
// the previously produced date, and that is the whole point of the function. A
// series anchored on the 31st goes 31 January, 28 February, 31 March: the
// clamp applies to February and then stops applying. Reading the day back off
// the previous result instead makes the clamp permanent, so the series would
// spend the rest of its life on the 28th. Handing the arithmetic to
// AddDate(0, n, 0) is worse again -- it does not clamp at all, it overflows,
// so 31 January plus one month is 3 March.
func AddMonthsClamped(anchor LocalDate, n int) LocalDate {
	total := anchor.Year*12 + (anchor.Month - 1) + n
	year := total / 12
	month := total%12 + 1
	if month < 1 {
		year--
		month += 12
	}
	day := anchor.Day
	if limit := DaysInMonth(year, month); day > limit {
		day = limit
	}
	return LocalDate{Year: year, Month: month, Day: day}
}

// NormaliseWeekdays reduces a selectedDays list to the sorted, deduplicated
// set of weekday numbers it names. Values outside 0-6 are folded into range
// rather than rejected, because the column is a plain integer array and older
// rows are not guaranteed to respect the range.
func NormaliseWeekdays(days []int) []int {
	seen := make(map[int]bool, len(days))
	for _, d := range days {
		v := d % 7
		if v < 0 {
			v += 7
		}
		seen[v] = true
	}
	out := make([]int, 0, len(seen))
	for v := 0; v < 7; v++ {
		if seen[v] {
			out = append(out, v)
		}
	}
	return out
}
