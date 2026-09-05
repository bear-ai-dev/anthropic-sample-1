package recurrence

import "time"

// Resolution records how a nominal local time related to the zone's offset
// changes. It is carried alongside every produced instant so that a series
// crossing a transition can be explained rather than merely computed.
type Resolution int

const (
	// Exact means the wall time happened once, as written.
	Exact Resolution = iota
	// Skipped means the wall time never happened: an offset change jumped
	// over it. The instant produced is the first one that does exist.
	Skipped
	// Repeated means the wall time happened twice. The earlier of the two
	// instants is the one produced.
	Repeated
)

// String names the resolution for reports.
func (r Resolution) String() string {
	switch r {
	case Skipped:
		return "skipped"
	case Repeated:
		return "repeated"
	default:
		return "exact"
	}
}

// InstantAt resolves "this many seconds after local midnight on this date, in
// this zone" to a single instant.
//
// Most of the year that is a one-liner. Twice a year in most zones it is not,
// and time.Date cannot be taken at its word in either direction.
//
// A fall-back repeats a stretch of clock, so a wall time inside it happens
// twice, and time.Date picks one without saying which. Its choice is not
// consistently the earlier one: for New York's 01:30 on 1 November it returns
// the first pass, and for Berlin's 02:30 on 25 October it returns the second.
// Trusting it was a bug here, and one that hid behind an American test zone.
// The earlier pass is the one wanted, so both are constructed and the earlier
// is taken.
//
// A spring-forward removes a stretch of clock, so a wall time inside it never
// happens, and time.Date quietly returns a real instant reading something
// else. Which side of the gap it lands on is not fixed either -- Los Angeles
// comes back an hour early, Lisbon an hour late -- so neither edge can be
// assumed. The instant wanted is the first one that exists at or after the
// nominal time, which is the transition itself: the boundary whose own wall
// clock has passed the nominal time while the second before it has not.
//
// Both cases are handled by the same move: build every instant the zone's
// nearby offsets could put the requested wall clock at, and keep the ones that
// actually read back as it. Two survivors mean an ambiguous time, one means an
// ordinary one, and none means a gap.
//
// Nothing here is hour-shaped, because not every transition is an hour. Lord
// Howe Island shifts by thirty minutes, so its ambiguous window is half an
// hour long and its gap is too.
//
// Either way the occurrence keeps its local calendar date, so a series never
// gains or loses a slot to a transition -- which matters, because the end
// rules count slots.
func InstantAt(d LocalDate, secondsFromMidnight int, loc *time.Location) (time.Time, Resolution) {
	if loc == nil {
		loc = time.UTC
	}

	// An offset of a day or more is not expected but is representable, so it
	// is carried into the date rather than silently folded away.
	day := d
	secs := secondsFromMidnight
	if secs >= 86400 || secs < 0 {
		shift := secs / 86400
		secs -= shift * 86400
		if secs < 0 {
			secs += 86400
			shift--
		}
		day = d.AddDays(shift)
	}
	hh, mm, ss := secs/3600, (secs%3600)/60, secs%60

	// The requested wall clock, held as a UTC instant purely so that two wall
	// clocks can be compared with one another.
	asked := time.Date(day.Year, time.Month(day.Month), day.Day, hh, mm, ss, 0, time.UTC)

	// time.Date's answer is not necessarily the one wanted, but it is a real
	// instant close to the right part of the year, which is what is needed to
	// find out which offsets are in play.
	near := time.Date(day.Year, time.Month(day.Month), day.Day, hh, mm, ss, 0, loc)
	start, end := near.ZoneBounds()

	var best time.Time
	found := 0
	for _, offset := range nearbyOffsets(near, start, end) {
		cand := time.Unix(asked.Unix()-int64(offset), 0).In(loc)
		if !wallClock(cand).Equal(asked) {
			continue
		}
		found++
		if best.IsZero() || cand.Before(best) {
			best = cand
		}
	}
	switch {
	case found > 1:
		return best, Repeated
	case found == 1:
		return best, Exact
	}

	// A gap. Its far edge is a transition whose wall clock has moved past the
	// requested one while the instant before it has not, which distinguishes
	// the transition that jumped over the request from the other boundary of
	// whatever period time.Date happened to land in.
	for _, edge := range []time.Time{start, end} {
		if edge.IsZero() {
			continue
		}
		if wallClock(edge).After(asked) &&
			wallClock(edge.Add(-time.Second)).Before(asked) {
			return edge, Skipped
		}
	}
	// No boundary to appeal to. Returning what Go produced is better than
	// returning nothing, and no zone in the database reaches here.
	return near, Skipped
}

// nearbyOffsets lists the UTC offsets, in seconds, that the zone uses around
// an instant: its own, the one before the period it sits in, and the one
// after. A transition sits between two of those, so any wall clock near one is
// reachable through this list, and the list is short enough that trying all of
// them is cheaper than reasoning about which applies.
func nearbyOffsets(t, start, end time.Time) []int {
	var out []int
	add := func(x time.Time) {
		_, offset := x.Zone()
		for _, seen := range out {
			if seen == offset {
				return
			}
		}
		out = append(out, offset)
	}
	add(t)
	if !start.IsZero() {
		add(start.Add(-time.Second))
	}
	if !end.IsZero() {
		add(end)
	}
	return out
}

// wallClock re-reads an instant's local calendar reading as a UTC instant, so
// that two readings can be compared without their offsets confusing the
// question.
func wallClock(t time.Time) time.Time {
	return time.Date(t.Year(), t.Month(), t.Day(),
		t.Hour(), t.Minute(), t.Second(), 0, time.UTC)
}

// LoadLocation resolves a zone name, treating an empty name as UTC. An empty
// name is what the database column defaults to, so it is a legitimate value
// rather than an error.
func LoadLocation(name string) (*time.Location, error) {
	if name == "" {
		return time.UTC, nil
	}
	return time.LoadLocation(name)
}
