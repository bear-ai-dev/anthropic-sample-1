package migration

import (
	"context"
	"errors"
	"fmt"

	"membershipledger/internal/legacy"
	"membershipledger/internal/store"
)

// applier moves ledger movements from the legacy log into the destination.
//
// The destination puts no uniqueness constraint on ledger rows, so exactly-once
// is entirely this type's problem. It keeps the set of movements the
// destination already holds and writes only what is missing from it; when the
// store declines to say whether a write landed, it reloads that set instead of
// guessing. Every path through here is safe to run again from the start.
//
// It also carries the lease it is acting under, and checks the migration record
// still names that fence before every single write. That is not tidiness. A
// worker can be stopped anywhere, including inside a store call, and come back
// to a world where another worker has taken the migration off it and moved it
// on; the write it was making is already gone and cannot be recalled, but every
// write after that one is a write it is not entitled to make. Checking the
// fence only on the way in, or only when publishing the record, leaves a
// stopped worker free to finish a whole phase's worth of work into a store that
// has moved past it.
type applier struct {
	orchestrator *Orchestrator
	snap         *snapshot
	book         map[string]legacy.Member
	held         lease
}

func (o *Orchestrator) newApplier(ctx context.Context, held lease) (*applier, error) {
	snap, err := loadSnapshot(o.deps.Store)
	if err != nil {
		return nil, fmt.Errorf("read the destination: %w", err)
	}
	members, err := o.deps.Legacy.Members(ctx)
	if err != nil {
		return nil, fmt.Errorf("read the member book: %w", err)
	}
	book := make(map[string]legacy.Member, len(members))
	for _, member := range members {
		book[member.MemberID] = member
	}
	return &applier{orchestrator: o, snap: snap, book: book, held: held}, nil
}

// entitled reports whether this worker may still write. The record's fence is
// the authority, not the lease key: a lease can be renewed, handed on, or
// simply run out, and the fence is the thing that is published where every
// worker can see it and that never goes backwards.
func (a *applier) entitled() error {
	meta, err := a.orchestrator.deps.Store.MetaGet()
	if err != nil {
		return err
	}
	if meta.Fence != a.held.Fence {
		return fmt.Errorf("%w: acting under fence %d, the record is at %d",
			ErrRefused, a.held.Fence, meta.Fence)
	}
	return nil
}

func (a *applier) refresh() error {
	snap, err := loadSnapshot(a.orchestrator.deps.Store)
	if err != nil {
		return err
	}
	a.snap = snap
	return nil
}

func (a *applier) missing(entries []legacy.Entry) []legacy.Entry {
	var out []legacy.Entry
	for _, entry := range entries {
		if !a.snap.has(entry.MemberID, entry.Seq) {
			out = append(out, entry)
		}
	}
	return out
}

// write applies the movements in entries that are not in the destination yet.
func (a *applier) write(entries []legacy.Entry) error {
	limit := a.orchestrator.deps.Cfg.ApplyBatchMax

	// Every member these movements belong to, not merely the ones this process
	// happened to write. A run that comes back to a batch already in the
	// destination still owes that batch's member rows an update: the write that
	// should have made them may have been the one that never happened.
	touched := map[string]bool{}
	for _, entry := range entries {
		touched[entry.MemberID] = true
	}

	pending := a.missing(entries)
	for attempt := 0; len(pending) > 0; attempt++ {
		if attempt > 8 {
			return fmt.Errorf("gave up with %d movement(s) unapplied", len(pending))
		}
		batch := pending
		if len(batch) > limit {
			batch = batch[:limit]
		}
		rows := make([]store.Entry, 0, len(batch))
		for _, entry := range batch {
			rows = append(rows, storeEntry(entry))
		}

		if err := a.entitled(); err != nil {
			return err
		}
		err := a.orchestrator.deps.Store.EntryAdd(rows)
		switch {
		case err == nil:
			for _, entry := range batch {
				a.snap.note(storeEntry(entry))
			}
			pending = pending[len(batch):]
		case errors.Is(err, store.ErrOutcomeUnknown):
			// Either all of this batch landed or none of it did. Reload what
			// the destination holds and work out which from that.
			if err := a.refresh(); err != nil {
				return err
			}
			pending = a.missing(entries)
		default:
			return err
		}
	}
	return a.syncMembers(touched)
}

// syncMembers brings member rows back into line with the movements the
// destination holds. It runs after every apply, which is what repairs a member
// row whose update was lost when the process went down between the two writes.
func (a *applier) syncMembers(touched map[string]bool) error {
	ids := make([]string, 0, len(touched))
	for id := range touched {
		ids = append(ids, id)
	}
	return a.putMembers(ids)
}

func (a *applier) putMembers(ids []string) error {
	var pending []store.Member
	for _, id := range ids {
		source, known := a.book[id]
		if !known {
			continue
		}
		want := a.snap.wanted(source)
		if have, present := a.snap.members[id]; present && have == want {
			continue
		}
		pending = append(pending, want)
	}
	if len(pending) == 0 {
		return nil
	}
	limit := a.orchestrator.deps.Cfg.ApplyBatchMax
	for start := 0; start < len(pending); {
		end := min(start+limit, len(pending))
		batch := pending[start:end]
		if err := a.entitled(); err != nil {
			return err
		}
		err := a.orchestrator.deps.Store.MemberPut(batch)
		switch {
		case err == nil:
			for _, member := range batch {
				a.snap.members[member.MemberID] = member
			}
			start = end
		case errors.Is(err, store.ErrOutcomeUnknown):
			// Member rows are written whole, so re-reading tells us whether
			// this batch needs doing again, and writing it again is harmless.
			if err := a.refresh(); err != nil {
				return err
			}
			same := true
			for _, member := range batch {
				if a.snap.members[member.MemberID] != member {
					same = false
					break
				}
			}
			if same {
				start = end
			}
		default:
			return err
		}
	}
	return nil
}

// remove takes movements out of the destination.
//
// The store removes a movement, not a row, so a movement it holds twice comes
// out altogether and has to be put back afterwards. That is why removal and
// re-application are one operation here and not two phases: between the two
// writes the destination is short a movement it is supposed to have, and the
// only thing that makes that survivable is that the next pass over the log
// finds it missing and applies it again.
func (a *applier) remove(keys []key) error {
	if len(keys) == 0 {
		return nil
	}
	limit := a.orchestrator.deps.Cfg.ApplyBatchMax
	pending := keys
	for attempt := 0; len(pending) > 0; attempt++ {
		if attempt > 8 {
			return fmt.Errorf("gave up with %d movement(s) still to remove", len(pending))
		}
		batch := pending
		if len(batch) > limit {
			batch = batch[:limit]
		}
		rows := make([]store.EntryKey, 0, len(batch))
		for _, identity := range batch {
			rows = append(rows, store.EntryKey{MemberID: identity.memberID, Seq: identity.seq})
		}
		if err := a.entitled(); err != nil {
			return err
		}
		err := a.orchestrator.deps.Store.EntryRemove(rows)
		switch {
		case err == nil:
			for _, identity := range batch {
				a.snap.forget(identity)
			}
			pending = pending[len(batch):]
		case errors.Is(err, store.ErrOutcomeUnknown):
			if err := a.refresh(); err != nil {
				return err
			}
			var left []key
			for _, identity := range pending {
				if a.snap.counts[identity] > 0 {
					left = append(left, identity)
				}
			}
			pending = left
		default:
			return err
		}
	}
	// The member totals have to be reloaded, not adjusted: what the fold should
	// say now is a question about the rows the store is left holding.
	return a.refresh()
}

// ensureBook makes sure every member has a row in the destination, closed ones
// included. A closed member still owns its history.
func (a *applier) ensureBook() error {
	ids := make([]string, 0, len(a.book))
	for id := range a.book {
		ids = append(ids, id)
	}
	return a.putMembers(ids)
}

// applyLog reads the legacy log forward from a position and applies it, up to
// and including upto (0 for the whole log). It returns the position it reached.
func (a *applier) applyLog(ctx context.Context, from, upto int64, held lease) (int64, error) {
	cursor := from
	page := a.orchestrator.deps.Cfg.ApplyBatchMax
	for {
		entries, err := a.orchestrator.deps.Legacy.EntriesAfter(ctx, cursor, page)
		if err != nil {
			return cursor, err
		}
		if len(entries) == 0 {
			return cursor, nil
		}
		exhausted := len(entries) < page
		if upto > 0 {
			kept := entries[:0]
			for _, entry := range entries {
				if entry.GlobalSeq <= upto {
					kept = append(kept, entry)
				}
			}
			if len(kept) < len(entries) {
				exhausted = true
			}
			entries = kept
		}
		if len(entries) == 0 {
			return cursor, nil
		}
		if err := a.write(entries); err != nil {
			return cursor, err
		}
		cursor = entries[len(entries)-1].GlobalSeq
		// The position is filed only once the movements it covers are durable.
		a.orchestrator.saveCheckpoint(cursor, held)
		a.orchestrator.renew(held)
		if exhausted {
			return cursor, nil
		}
	}
}
