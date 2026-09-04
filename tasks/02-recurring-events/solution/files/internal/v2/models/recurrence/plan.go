package recurrence

import (
	"fmt"
	"sort"
	"time"
)

// Existing is one stored occurrence, reduced to what deciding its fate needs.
// It carries no form data and no model types, so that this package stays a
// leaf and the models package can import it.
type Existing struct {
	// Id is the stored occurrence_id. Preserving it across a regenerate is
	// what makes a published slot the same slot afterwards, and what keeps a
	// published event's link to it meaningful.
	Id string
	// Instant is the occurrence's stored date.
	Instant time.Time
	// PublishedEvent is the linked event's identifier, empty when the slot has
	// not been published.
	PublishedEvent string
	// Edited records that the row carries an update timestamp, which is what
	// an individual edit through the occurrence endpoint leaves behind.
	Edited bool
	// LiveReceipts counts receipt items on the published event that represent
	// money actually taken: not pending, not refunded, not abandoned.
	LiveReceipts int
}

// Published reports whether the slot has an event attached.
func (e Existing) Published() bool { return e.PublishedEvent != "" }

// Sold reports whether the slot's event has taken money. It is the stronger
// condition: publishing an event and selling nothing to it are different
// states, and only the second one is irreversible.
func (e Existing) Sold() bool { return e.Published() && e.LiveReceipts > 0 }

// Disposition says why a row survived a regenerate, or did not.
type Disposition string

// The reasons a row can be kept or dropped, recorded so that a regenerate can
// be explained after the fact.
const (
	KeptPublished  Disposition = "published"
	KeptEdited     Disposition = "edited-on-pattern"
	DroppedOffPat  Disposition = "edited-off-pattern"
	DroppedRoutine Disposition = "regenerated"
)

// Decision pairs a row with what is to be done about it.
type Decision struct {
	Row         Existing
	Date        LocalDate
	Disposition Disposition
}

// Plan is the outcome of thinking about a regenerate before doing any of it.
type Plan struct {
	// Keep are rows that must survive untouched: same occurrence_id, same
	// date, same form data, same publish link.
	Keep []Decision
	// Drop are rows to be unlinked and deleted.
	Drop []Decision
	// Insert are the generated slots that no kept row already occupies.
	Insert []Slot
	// Claimed maps every local date a kept row occupies to that row's id.
	Claimed map[string]string
	// Slots is the full generated lattice, kept for reporting.
	Slots []Slot
}

// PlanRegenerate decides what a regenerate must do, without doing any of it.
//
// Retention has two tiers and conflating them is the usual mistake:
//
// A published occurrence is kept unconditionally. It may well sit on a date
// the current configuration would never generate -- that is exactly what has
// happened when the configuration was changed after something was published --
// and it is kept anyway. An event exists for it and, possibly, tickets have
// been sold for that event; regenerating a template is not grounds for
// destroying either.
//
// An occurrence that was edited individually but never published is kept only
// while its own local date is still on the lattice. That single condition is
// what makes an edit survive an ordinary regenerate and not survive one taken
// after the repeat configuration changed, and it needs nothing to remember
// that the configuration changed: a changed configuration produces a different
// set of dates, and the edit's date is no longer among them.
//
// Everything else is replaced.
//
// A kept row then owns its local calendar date, and the generated slot for
// that date is not inserted. Without this a regenerate double-books every
// published date -- the old row and a freshly generated one, an hour or a
// minute apart, both claiming to be the same event -- which is the failure the
// one-per-date invariant exists to prevent.
func PlanRegenerate(cfg Config, existing []Existing, anchor LocalDate, secondsFromMidnight int) (*Plan, error) {
	slots, err := Slots(cfg, anchor, secondsFromMidnight)
	if err != nil {
		return nil, err
	}

	onPattern := make(map[string]bool, len(slots))
	for _, s := range slots {
		onPattern[s.Date.String()] = true
	}

	plan := &Plan{Claimed: map[string]string{}, Slots: slots}

	for _, row := range existing {
		d := DateIn(row.Instant, cfg.Location)
		switch {
		case row.Published():
			plan.Keep = append(plan.Keep, Decision{row, d, KeptPublished})
		case row.Edited && onPattern[d.String()]:
			plan.Keep = append(plan.Keep, Decision{row, d, KeptEdited})
		case row.Edited:
			plan.Drop = append(plan.Drop, Decision{row, d, DroppedOffPat})
		default:
			plan.Drop = append(plan.Drop, Decision{row, d, DroppedRoutine})
		}
	}

	for _, k := range plan.Keep {
		key := k.Date.String()
		if prior, clash := plan.Claimed[key]; clash {
			// Two rows the rules both say to keep, on one calendar date. The
			// store should not be able to reach this state, and quietly
			// picking one would hide however it did.
			return nil, fmt.Errorf(
				"recurrence: occurrences %s and %s both claim local date %s",
				prior, k.Row.Id, key)
		}
		plan.Claimed[key] = k.Row.Id
	}

	for _, s := range slots {
		if _, taken := plan.Claimed[s.Date.String()]; !taken {
			plan.Insert = append(plan.Insert, s)
		}
	}

	return plan, nil
}

// PlanExtend decides which slots an extend appends.
//
// The earliest occurrence gives the lattice its anchor, which is what keeps the
// continuation on the same sequence the series has been following -- a monthly
// series whose latest slot was clamped to 28 February continues on the 31st,
// because the anchor says 31 and February merely could not hold it.
//
// What the extend then adds is the first `additional` dates of that sequence
// the series does not already hold. That is a set difference and not an append,
// which matters whenever the series is not contiguous: a date that a delete or
// a regenerate left vacant is still a date on the pattern that the series does
// not hold, and it comes before anything past the latest occurrence.
func PlanExtend(cfg Config, existing []Existing, additional, secondsFromMidnight int) ([]Slot, error) {
	if additional < 1 {
		return nil, nil
	}
	if len(existing) == 0 {
		return nil, fmt.Errorf("recurrence: cannot extend a series with no occurrences")
	}

	dates := make([]LocalDate, 0, len(existing))
	for _, row := range existing {
		dates = append(dates, DateIn(row.Instant, cfg.Location))
	}
	sort.Slice(dates, func(i, j int) bool { return dates[i].Before(dates[j]) })

	held := make(map[string]bool, len(dates))
	for _, d := range dates {
		held[d.String()] = true
	}
	return Continue(cfg, dates[0], held, additional, secondsFromMidnight)
}

// ScopedMove is one row a scoped edit rewrites: it keeps its local calendar
// date and its identity, and takes a new instant because the edit carried a new
// time of day.
type ScopedMove struct {
	Row        Existing
	Date       LocalDate
	Instant    time.Time
	Resolution Resolution
}

// ScopedEdit is what a thisAndFollowing edit does, decided before any of it is
// done.
type ScopedEdit struct {
	// Target is the local date the scope starts at.
	Target LocalDate
	// Move are the rows the edit rewrites.
	Move []ScopedMove
	// Paid are rows on or after the target that the edit steps over because
	// their published event has taken money.
	Paid []Existing
	// Earlier are rows before the target, which a scope never reaches.
	Earlier []Existing
}

// PlanScopedEdit decides which occurrences a thisAndFollowing edit reaches.
//
// Three things decide it, and each is a separate way to get it wrong.
//
// "On or after the target" is a comparison of local calendar dates in the
// series' zone, not of stored instants. The two disagree exactly when the edit
// moves the time of day: an occurrence a few hours later on the previous local
// date can sit at a larger instant than the target does, and a filter written
// on the stored column would drag it in.
//
// A paid occurrence is stepped over. Somebody outside the system is holding a
// ticket that says when that event starts, so it keeps both its instant and its
// form data -- the same rule the delete path refuses on, applied to a different
// verb. Note that publication alone is not enough: an event published and sold
// nothing to moves like any other row.
//
// The rows it does move keep their local dates. A scope changes what time of day
// an occurrence happens at, never which day it happens on, so the one
// occurrence per local date invariant is preserved by construction rather than
// by being repaired afterwards.
func PlanScopedEdit(cfg Config, existing []Existing, targetId string, secondsFromMidnight int) (*ScopedEdit, error) {
	var target *Existing
	for i := range existing {
		if existing[i].Id == targetId {
			target = &existing[i]
			break
		}
	}
	if target == nil {
		return nil, fmt.Errorf("recurrence: occurrence %s is not in the series", targetId)
	}

	out := &ScopedEdit{Target: DateIn(target.Instant, cfg.Location)}
	for _, row := range existing {
		d := DateIn(row.Instant, cfg.Location)
		switch {
		case d.Before(out.Target):
			out.Earlier = append(out.Earlier, row)
		case row.Sold():
			out.Paid = append(out.Paid, row)
		default:
			inst, res := InstantAt(d, secondsFromMidnight, cfg.Location)
			out.Move = append(out.Move, ScopedMove{
				Row: row, Date: d, Instant: inst, Resolution: res,
			})
		}
	}
	return out, nil
}
