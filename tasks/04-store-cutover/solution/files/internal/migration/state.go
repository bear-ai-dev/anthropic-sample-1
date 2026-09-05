package migration

import (
	"membershipledger/internal/legacy"
	"membershipledger/internal/store"
)

// key identifies a ledger movement. The same key from either store is one
// movement, however many rows happen to carry it.
type key struct {
	memberID string
	seq      int64
}

type aggregate struct {
	balance int64
	version int64
}

// snapshot is the destination as it stands, indexed by the questions the
// migration needs answered: is this movement here, is it here more than once,
// and what do the members fold to.
type snapshot struct {
	counts    map[key]int
	agg       map[string]aggregate
	members   map[string]store.Member
	maxGlobal int64
	memberMax map[string]int64
}

func newSnapshot() *snapshot {
	return &snapshot{
		counts:    map[key]int{},
		agg:       map[string]aggregate{},
		members:   map[string]store.Member{},
		memberMax: map[string]int64{},
	}
}

func loadSnapshot(client *store.Client) (*snapshot, error) {
	snap := newSnapshot()
	const page = 1000
	after := int64(0)
	for {
		entries, err := client.EntryList(after, page)
		if err != nil {
			return nil, err
		}
		for _, entry := range entries {
			snap.note(entry)
			if entry.GlobalSeq > after {
				after = entry.GlobalSeq
			}
		}
		if len(entries) < page {
			break
		}
	}
	members, err := client.MemberList()
	if err != nil {
		return nil, err
	}
	for _, member := range members {
		snap.members[member.MemberID] = member
	}
	return snap, nil
}

// note records a row the destination holds. Only the first row for a movement
// counts towards the fold; the rest are duplicates and are a defect, not a
// second movement.
func (s *snapshot) note(entry store.Entry) {
	identity := key{entry.MemberID, entry.Seq}
	s.counts[identity]++
	if s.counts[identity] == 1 {
		totals := s.agg[entry.MemberID]
		totals.balance += entry.DeltaCents
		totals.version++
		s.agg[entry.MemberID] = totals
	}
	if entry.GlobalSeq > s.maxGlobal {
		s.maxGlobal = entry.GlobalSeq
	}
	if entry.GlobalSeq > s.memberMax[entry.MemberID] {
		s.memberMax[entry.MemberID] = entry.GlobalSeq
	}
}

func (s *snapshot) has(memberID string, seq int64) bool {
	return s.counts[key{memberID, seq}] > 0
}

// forget records that a movement has been taken out of the destination
// altogether, however many rows were carrying it. The member totals are not
// adjusted here: whoever removed the movement reloads the destination
// afterwards, because the totals have to come from what the store holds rather
// than from arithmetic on what it used to hold.
func (s *snapshot) forget(identity key) {
	delete(s.counts, identity)
}

// wanted is the member row the destination should hold: identity out of the
// member book, totals out of the movements applied so far.
func (s *snapshot) wanted(source legacy.Member) store.Member {
	totals := s.agg[source.MemberID]
	return store.Member{
		MemberID:     source.MemberID,
		Tier:         source.Tier,
		Deleted:      source.Deleted,
		UpdatedAt:    source.UpdatedAt,
		BalanceCents: totals.balance,
		Version:      totals.version,
	}
}

func storeEntry(entry legacy.Entry) store.Entry {
	return store.Entry{
		EntryID:    entry.EntryID,
		MemberID:   entry.MemberID,
		Seq:        entry.Seq,
		GlobalSeq:  entry.GlobalSeq,
		DeltaCents: entry.DeltaCents,
		Reason:     entry.Reason,
		WrittenAt:  entry.WrittenAt,
	}
}
