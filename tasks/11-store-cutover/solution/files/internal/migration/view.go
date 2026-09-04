package migration

import (
	"context"
	"sort"

	"membershipledger/internal/ledger"
	"membershipledger/internal/legacy"
	"membershipledger/internal/store"
)

// View answers the public endpoints while a migration is in progress.
//
// Which store an answer comes from is decided per member, per request, from the
// migration record and from how far that member's history has been applied.
// Nothing is cached: the phase can change between two requests and the second
// one has to notice.
type View struct {
	deps     Deps
	fallback ledger.View
}

func NewView(deps Deps, fallback ledger.View) View {
	return View{deps: deps, fallback: fallback}
}

func (v View) phase() Phase {
	meta, err := v.deps.Store.MetaGet()
	if err != nil {
		// If the migration record cannot be read, the legacy store is still
		// the one that has always worked.
		return PhaseInit
	}
	return Phase(meta.Phase)
}

// retired is true once legacy has left the read path.
func retired(phase Phase) bool {
	return Index(phase) >= Index(PhaseLegacyRetired)
}

func (v View) Member(ctx context.Context, memberID string) (legacy.Member, error) {
	phase := v.phase()
	if phase == PhaseInit {
		return v.fallback.Member(ctx, memberID)
	}
	if retired(phase) {
		member, found, err := v.deps.Store.MemberGet(memberID)
		if err != nil {
			return legacy.Member{}, err
		}
		if !found {
			return legacy.Member{}, legacy.ErrNotFound
		}
		return fromStore(member), nil
	}

	source, err := v.fallback.Member(ctx, memberID)
	if err != nil {
		return legacy.Member{}, err
	}
	behind, err := v.behind(ctx, memberID)
	if err != nil {
		return legacy.Member{}, err
	}
	if behind {
		// The destination has not caught up with this member, so the only
		// store that can answer without serving stale data is legacy.
		return source, nil
	}
	member, found, err := v.deps.Store.MemberGet(memberID)
	if err != nil || !found {
		return source, err
	}
	return fromStore(member), nil
}

// behind reports whether legacy holds movements for this member that the
// destination has not applied.
func (v View) behind(ctx context.Context, memberID string) (bool, error) {
	applied, err := v.deps.Store.EntryForMember(memberID)
	if err != nil {
		return true, err
	}
	highest := int64(0)
	for _, entry := range applied {
		if entry.GlobalSeq > highest {
			highest = entry.GlobalSeq
		}
	}
	history, err := v.deps.Legacy.Ledger(ctx, memberID)
	if err != nil {
		return true, err
	}
	for _, entry := range history {
		if entry.GlobalSeq > highest {
			return true, nil
		}
	}
	return false, nil
}

func (v View) Ledger(ctx context.Context, memberID string) ([]legacy.Entry, error) {
	phase := v.phase()
	if phase == PhaseInit {
		return v.fallback.Ledger(ctx, memberID)
	}
	if retired(phase) {
		if _, found, err := v.deps.Store.MemberGet(memberID); err != nil {
			return nil, err
		} else if !found {
			return nil, legacy.ErrNotFound
		}
		applied, err := v.deps.Store.EntryForMember(memberID)
		if err != nil {
			return nil, err
		}
		return sortedEntries(mergeByIdentity(nil, applied)), nil
	}

	history, err := v.fallback.Ledger(ctx, memberID)
	if err != nil {
		return nil, err
	}
	applied, err := v.deps.Store.EntryForMember(memberID)
	if err != nil {
		return nil, err
	}
	// The two stores overlap. A movement is a (member, sequence) pair, so the
	// same pair from both sides is one line in the answer.
	return sortedEntries(mergeByIdentity(history, applied)), nil
}

func (v View) Adjust(ctx context.Context, memberID string, deltaCents int64, reason string) (legacy.Entry, legacy.Member, error) {
	if retired(v.phase()) {
		return legacy.Entry{}, legacy.Member{}, ledger.ErrWriteRefused
	}
	return v.fallback.Adjust(ctx, memberID, deltaCents, reason)
}

func mergeByIdentity(history []legacy.Entry, applied []store.Entry) map[int64]legacy.Entry {
	merged := make(map[int64]legacy.Entry, len(history)+len(applied))
	for _, entry := range applied {
		merged[entry.Seq] = legacy.Entry{
			EntryID:    entry.EntryID,
			MemberID:   entry.MemberID,
			Seq:        entry.Seq,
			GlobalSeq:  entry.GlobalSeq,
			DeltaCents: entry.DeltaCents,
			Reason:     entry.Reason,
			WrittenAt:  entry.WrittenAt,
		}
	}
	for _, entry := range history {
		merged[entry.Seq] = entry
	}
	return merged
}

func sortedEntries(merged map[int64]legacy.Entry) []legacy.Entry {
	out := make([]legacy.Entry, 0, len(merged))
	for _, entry := range merged {
		out = append(out, entry)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Seq < out[j].Seq })
	return out
}

func fromStore(member store.Member) legacy.Member {
	return legacy.Member{
		MemberID:     member.MemberID,
		Tier:         member.Tier,
		BalanceCents: member.BalanceCents,
		Version:      member.Version,
		Deleted:      member.Deleted,
		UpdatedAt:    member.UpdatedAt,
	}
}
