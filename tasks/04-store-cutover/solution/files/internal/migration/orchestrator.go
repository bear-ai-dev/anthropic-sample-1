package migration

import (
	"context"
	"errors"
	"fmt"

	"membershipledger/internal/clock"
	"membershipledger/internal/config"
	"membershipledger/internal/legacy"
	"membershipledger/internal/store"
)

// ErrNotImplemented is kept for callers that still look for it.
var ErrNotImplemented = errors.New("migration not implemented")

// ErrRefused is for an advance that cannot run: the phase's gate does not
// hold, or this worker is not the one entitled to run it.
var ErrRefused = errors.New("migration advance refused")

// Deps is everything the migration is allowed to touch.
type Deps struct {
	Cfg    config.Config
	Legacy *legacy.Store
	Store  *store.Client
	Clock  *clock.Clock
}

// Status is what the admin surface reports. The field names are part of the
// service's contract with the tooling that drives a migration.
type Status struct {
	Phase              string `json:"phase"`
	Authority          string `json:"authority"`
	Fence              int64  `json:"fence"`
	Cursor             int64  `json:"cursor"`
	DivergenceCount    int64  `json:"divergence_count"`
	ShadowBoundary     int64  `json:"shadow_boundary"`
	LegacyMaxGlobalSeq int64  `json:"legacy_max_global_seq"`
	LegacyEntryCount   int64  `json:"legacy_entry_count"`
	DestinationEntries int64  `json:"destination_entries"`
	Holder             string `json:"holder"`
}

type Orchestrator struct {
	deps Deps
}

func New(deps Deps) *Orchestrator { return &Orchestrator{deps: deps} }

func (o *Orchestrator) Deps() Deps { return o.deps }

// Status reports where the migration is, from the stores rather than from
// memory, so a restarted process reports the same thing the old one did.
func (o *Orchestrator) Status(ctx context.Context) (Status, error) {
	meta, err := o.deps.Store.MetaGet()
	if err != nil {
		return Status{}, err
	}
	status := Status{
		Phase:           meta.Phase,
		Authority:       meta.Authority,
		Fence:           meta.Fence,
		Cursor:          meta.Cursor,
		DivergenceCount: meta.Divergence,
		ShadowBoundary:  o.deps.Cfg.ShadowBoundary,
		Holder:          o.deps.Cfg.LeaseHolder,
	}
	if maxSeq, err := o.deps.Legacy.MaxGlobalSeq(ctx); err == nil {
		status.LegacyMaxGlobalSeq = maxSeq
	}
	if count, err := o.deps.Legacy.EntryCount(ctx); err == nil {
		status.LegacyEntryCount = count
	}
	if count, err := o.deps.Store.EntryCount(); err == nil {
		status.DestinationEntries = count
	}
	return status, nil
}

// Advance moves the migration on by one phase.
//
// Everything it needs it reads back out of the stores, so it does not matter
// whether this process is the one that ran the previous phase, how many times
// this has been called, or how the last attempt ended.
func (o *Orchestrator) Advance(ctx context.Context) (Status, error) {
	meta, err := o.deps.Store.MetaGet()
	if err != nil {
		return Status{}, err
	}
	held, err := o.takeLease(meta)
	if err != nil {
		return Status{}, err
	}
	// takeLease may have raised the record's fence, so read it again and
	// confirm the record names the fence this worker is acting under.
	meta, err = o.deps.Store.MetaGet()
	if err != nil {
		return Status{}, err
	}
	if meta.Fence != held.Fence {
		return Status{}, fmt.Errorf("%w: acting under fence %d, the record is at %d",
			ErrRefused, held.Fence, meta.Fence)
	}

	next, ok := Next(Phase(meta.Phase))
	if !ok {
		return o.Status(ctx)
	}

	var result outcome
	switch next {
	case PhaseShadowCopy:
		result, err = o.runShadowCopy(ctx, held)
	case PhaseDualRead:
		result, err = o.runDualRead(ctx, held)
	case PhaseCatchUp:
		result, err = o.runCatchUp(ctx, held)
	case PhaseReconcile:
		result, err = o.runReconcile(ctx, held)
	case PhaseCutover:
		result, err = o.runCutover(ctx, held)
	case PhaseLateReplay:
		result, err = o.runLateReplay(ctx, held)
	case PhaseLegacyRetired:
		result, err = o.runRetire(ctx, held)
	case PhaseComplete:
		result, err = o.runComplete(ctx, held)
	default:
		err = fmt.Errorf("%w: no work defined for %s", ErrRefused, next)
	}
	if err != nil {
		return Status{}, err
	}
	if err := o.commit(next, result, held); err != nil {
		return Status{}, err
	}
	// A convenience mirror for anything watching the coordination keyspace.
	_ = o.deps.Store.KVSet(phaseKey, string(next))
	return o.Status(ctx)
}

// commit records the phase and whatever the phase decided, in one write.
//
// The record is read again here, immediately before the write, and the write
// is conditional on it not having changed. That is what stops a worker landing
// the result of work it started while it still held the lease and finished
// after it had lost it: the fence it is acting under no longer matches, and the
// conditional write refuses.
func (o *Orchestrator) commit(next Phase, result outcome, held lease) error {
	current, err := o.deps.Store.MetaGet()
	if err != nil {
		return err
	}
	if current.Fence != held.Fence {
		return fmt.Errorf("%w: the record moved to fence %d while phase %s was running",
			ErrRefused, current.Fence, next)
	}
	if Index(Phase(current.Phase)) >= Index(next) {
		return nil
	}
	want := current
	want.Phase = string(next)
	if result.cursor != nil {
		want.Cursor = *result.cursor
	}
	if result.divergence != nil {
		want.Divergence = *result.divergence
	}
	if result.authority != "" {
		if current.Authority != AuthorityLegacy {
			return fmt.Errorf("%w: the authority has already moved", ErrRefused)
		}
		want.Authority = result.authority
	}
	after, swapped, err := o.publishMeta(want, &current)
	if err != nil {
		return err
	}
	if !swapped {
		return fmt.Errorf("%w: the record changed while %s was being recorded (now fence %d, phase %s)",
			ErrRefused, next, after.Fence, after.Phase)
	}
	return nil
}
