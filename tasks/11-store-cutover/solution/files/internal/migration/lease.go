package migration

import (
	"encoding/json"
	"errors"
	"fmt"

	"membershipledger/internal/store"
)

const (
	leaseKey      = "migration:lease"
	checkpointKey = "migration:checkpoint"
	phaseKey      = "migration:phase"
)

// lease is what one worker holds while it runs the migration. The fence is the
// part that matters after the fact: a worker can go on believing it holds a
// lease long after it stopped holding one, and the fence is how everything
// else notices.
type lease struct {
	Holder      string `json:"holder"`
	Fence       int64  `json:"fence"`
	ExpiresUnix int64  `json:"expires_unix"`
}

// takeLease acquires or renews the migration lease and makes sure the
// migration record names the fence this worker is entitled to act under.
func (o *Orchestrator) takeLease(meta store.Meta) (lease, error) {
	me := o.deps.Cfg.LeaseHolder
	now := o.deps.Clock.Unix()

	raw, present, err := o.deps.Store.KVGet(leaseKey)
	if err != nil {
		return lease{}, err
	}
	var current lease
	if present {
		if err := json.Unmarshal([]byte(raw), &current); err != nil {
			present = false
		}
	}

	mine := present && current.Holder == me && current.ExpiresUnix > now
	if present && !mine && current.ExpiresUnix > now {
		return lease{}, fmt.Errorf("%w: %s holds the lease until %d",
			ErrRefused, current.Holder, current.ExpiresUnix)
	}
	// Renewing keeps the fence already published. Taking over a lease that has
	// run out mints a new one, above anything ever published before.
	next := lease{Holder: me, ExpiresUnix: now + o.deps.Cfg.LeaseTTLSecs}
	if mine {
		next.Fence = current.Fence
		if current.Fence != meta.Fence {
			return lease{}, fmt.Errorf("%w: holding fence %d but the record is at %d",
				ErrRefused, current.Fence, meta.Fence)
		}
	} else {
		next.Fence = max(current.Fence, meta.Fence) + 1
	}

	blob, err := json.Marshal(next)
	if err != nil {
		return lease{}, err
	}
	var expect *string
	if present {
		expect = &raw
	}
	swapped, _, err := o.deps.Store.KVCAS(leaseKey, expect, string(blob))
	switch {
	case errors.Is(err, store.ErrOutcomeUnknown):
		// The swap either happened or it did not. Read the key rather than
		// picking one.
		after, ok, readErr := o.deps.Store.KVGet(leaseKey)
		if readErr != nil {
			return lease{}, readErr
		}
		if !ok || after != string(blob) {
			return lease{}, fmt.Errorf("%w: the lease was not taken", ErrRefused)
		}
	case err != nil:
		return lease{}, err
	case !swapped:
		return lease{}, fmt.Errorf("%w: the lease changed hands while it was being taken", ErrRefused)
	}

	if next.Fence != meta.Fence {
		raised := meta
		raised.Fence = next.Fence
		current, ok, err := o.publishMeta(raised, &meta)
		if err != nil {
			return lease{}, err
		}
		if !ok {
			return lease{}, fmt.Errorf("%w: the record moved to fence %d", ErrRefused, current.Fence)
		}
	}
	return next, nil
}

// renew extends the lease this worker holds without changing its fence, so a
// long phase does not lose it halfway through.
func (o *Orchestrator) renew(held lease) {
	raw, present, err := o.deps.Store.KVGet(leaseKey)
	if err != nil || !present {
		return
	}
	var current lease
	if json.Unmarshal([]byte(raw), &current) != nil {
		return
	}
	if current.Holder != held.Holder || current.Fence != held.Fence {
		// Someone else has it. Losing the renewal is not what stops this
		// worker acting; the fence on the migration record is.
		return
	}
	current.ExpiresUnix = o.deps.Clock.Unix() + o.deps.Cfg.LeaseTTLSecs
	blob, err := json.Marshal(current)
	if err != nil {
		return
	}
	_, _, _ = o.deps.Store.KVCAS(leaseKey, &raw, string(blob))
}

// publishMeta writes the migration record, and resolves an unreported outcome
// by reading the record back rather than assuming either way.
func (o *Orchestrator) publishMeta(want store.Meta, expect *store.Meta) (store.Meta, bool, error) {
	current, swapped, err := o.deps.Store.MetaPut(want, expect)
	if errors.Is(err, store.ErrOutcomeUnknown) {
		got, readErr := o.deps.Store.MetaGet()
		if readErr != nil {
			return store.Meta{}, false, readErr
		}
		return got, got == want, nil
	}
	if err != nil {
		return store.Meta{}, false, err
	}
	return current, swapped, nil
}
