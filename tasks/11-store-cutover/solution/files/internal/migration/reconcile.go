package migration

import (
	"context"
	"fmt"

	"membershipledger/internal/legacy"
)

// survey is what the two stores disagree about right now.
//
// Divergence has three directions and they need different repairs. A movement
// legacy has and the destination does not is applied. A movement the
// destination holds that legacy never had is taken out. A movement the
// destination holds more than once is taken out and applied again, because the
// store's removal names a movement and not a row. A pass that only ever adds
// closes the first of those and leaves the other two exactly as they were,
// which is the state a stopped worker's in-flight write leaves behind.
type survey struct {
	missing   []legacy.Entry
	extra     []key
	repeated  []legacy.Entry
	stale     int
	legacyMax int64
	touched   map[string]bool
}

func (s survey) divergence() int64 {
	return int64(len(s.missing) + len(s.extra) + len(s.repeated) + s.stale)
}

// compare walks the whole legacy log against the destination. It is deliberately
// not incremental: divergence is a statement about the stores as they are, and
// a cursor is exactly the thing that would hide a movement that went missing
// behind it.
func (a *applier) compare(ctx context.Context) (survey, error) {
	result := survey{touched: map[string]bool{}}
	seen := map[key]bool{}
	cursor := int64(0)
	page := 500
	for {
		entries, err := a.orchestrator.deps.Legacy.EntriesAfter(ctx, cursor, page)
		if err != nil {
			return result, err
		}
		if len(entries) == 0 {
			break
		}
		for _, entry := range entries {
			identity := key{entry.MemberID, entry.Seq}
			seen[identity] = true
			switch count := a.snap.counts[identity]; {
			case count == 0:
				result.missing = append(result.missing, entry)
				result.touched[entry.MemberID] = true
			case count > 1:
				// Held more than once. Keeping the legacy row means the repair
				// can put it back after taking every copy of it out.
				result.repeated = append(result.repeated, entry)
				result.touched[entry.MemberID] = true
			}
			if entry.GlobalSeq > result.legacyMax {
				result.legacyMax = entry.GlobalSeq
			}
		}
		cursor = entries[len(entries)-1].GlobalSeq
		if len(entries) < page {
			break
		}
	}

	for identity, count := range a.snap.counts {
		if count > 0 && !seen[identity] {
			result.extra = append(result.extra, identity)
			result.touched[identity.memberID] = true
		}
	}
	// A member row that does not match the movements under it is a divergence
	// too: the ledger invariant is part of what the destination has to hold.
	for id, source := range a.book {
		want := a.snap.wanted(source)
		if have, present := a.snap.members[id]; !present || have != want {
			result.touched[id] = true
			result.stale++
		}
	}
	return result, nil
}

// reconcile repairs whatever it can and reports what is left over.
//
// The order is forced: everything that should not be in the destination comes
// out first, and only then is what belongs there put in. Doing it the other way
// round would take a movement back out immediately after applying it, because
// removal names the movement and not the copy.
func (o *Orchestrator) reconcile(ctx context.Context, held lease) (int64, int64, error) {
	applier, err := o.newApplier(ctx, held)
	if err != nil {
		return 0, 0, err
	}
	found, err := applier.compare(ctx)
	if err != nil {
		return 0, 0, err
	}
	drop := found.extra
	for _, entry := range found.repeated {
		drop = append(drop, key{entry.MemberID, entry.Seq})
	}
	if err := applier.remove(drop); err != nil {
		return 0, 0, err
	}
	restore := append(append([]legacy.Entry{}, found.missing...), found.repeated...)
	if len(restore) > 0 {
		if err := applier.write(restore); err != nil {
			return 0, 0, err
		}
	}
	if len(found.touched) > 0 {
		if err := applier.syncMembers(found.touched); err != nil {
			return 0, 0, err
		}
	}
	// Ask again, of the stores as they now are.
	if err := applier.refresh(); err != nil {
		return 0, 0, err
	}
	after, err := applier.compare(ctx)
	if err != nil {
		return 0, 0, err
	}
	if after.divergence() == 0 {
		o.saveCheckpoint(after.legacyMax, held)
	}
	return after.divergence(), after.legacyMax, nil
}

func (o *Orchestrator) runReconcile(ctx context.Context, held lease) (outcome, error) {
	remaining, legacyMax, err := o.reconcile(ctx, held)
	if err != nil {
		return outcome{}, err
	}
	if remaining > 0 {
		// Reconciling is allowed to be run again; it is not allowed to claim
		// it succeeded.
		return outcome{divergence: &remaining, cursor: &legacyMax},
			fmt.Errorf("%w: %d movement(s) still differ", ErrRefused, remaining)
	}
	zero := int64(0)
	return outcome{divergence: &zero, cursor: &legacyMax}, nil
}
