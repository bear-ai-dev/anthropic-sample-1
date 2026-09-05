package migration

import (
	"context"
	"fmt"
)

// outcome is what a phase's work leaves behind for the migration record. Only
// the fields a phase actually decided are set, and they are written together
// with the phase itself so a half-recorded phase is not a state the migration
// can be in.
type outcome struct {
	cursor     *int64
	divergence *int64
	authority  string
}

// runShadowCopy copies the member book and the ledger as far as the phase-one
// boundary, and no further.
func (o *Orchestrator) runShadowCopy(ctx context.Context, held lease) (outcome, error) {
	applier, err := o.newApplier(ctx, held)
	if err != nil {
		return outcome{}, err
	}
	if len(applier.book) == 0 {
		return outcome{}, fmt.Errorf("%w: the legacy member book is empty", ErrRefused)
	}
	if err := applier.ensureBook(); err != nil {
		return outcome{}, err
	}
	boundary := o.deps.Cfg.ShadowBoundary
	cursor, err := applier.applyLog(ctx, 0, boundary, held)
	if err != nil {
		return outcome{}, err
	}
	return outcome{cursor: &cursor}, nil
}

// runDualRead has no work of its own: it is the point at which reads start
// consulting both stores, and its gate is that the shadow copy really did
// cover the boundary.
func (o *Orchestrator) runDualRead(ctx context.Context, held lease) (outcome, error) {
	applier, err := o.newApplier(ctx, held)
	if err != nil {
		return outcome{}, err
	}
	boundary := o.deps.Cfg.ShadowBoundary
	cursor := int64(0)
	page := 500
	for {
		entries, err := o.deps.Legacy.EntriesAfter(ctx, cursor, page)
		if err != nil {
			return outcome{}, err
		}
		if len(entries) == 0 {
			break
		}
		for _, entry := range entries {
			if entry.GlobalSeq > boundary {
				return outcome{}, nil
			}
			if !applier.snap.has(entry.MemberID, entry.Seq) {
				return outcome{}, fmt.Errorf(
					"%w: the shadow copy is missing %s#%d", ErrRefused, entry.MemberID, entry.Seq)
			}
			cursor = entry.GlobalSeq
		}
		if len(entries) < page {
			break
		}
	}
	for id := range applier.book {
		if _, present := applier.snap.members[id]; !present {
			return outcome{}, fmt.Errorf("%w: member %s was never copied", ErrRefused, id)
		}
	}
	return outcome{}, nil
}
