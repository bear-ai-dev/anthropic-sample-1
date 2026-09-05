package migration

import (
	"context"
	"fmt"
)

// runCatchUp applies the rest of the legacy log, checkpointing as it goes so a
// restart carries on rather than starting again.
func (o *Orchestrator) runCatchUp(ctx context.Context, held lease) (outcome, error) {
	return o.drain(ctx, held)
}

// runLateReplay applies the writes that reached legacy after the authority
// moved. There is no fixed set of them; whatever is not in the destination is
// one.
func (o *Orchestrator) runLateReplay(ctx context.Context, held lease) (outcome, error) {
	meta, err := o.deps.Store.MetaGet()
	if err != nil {
		return outcome{}, err
	}
	if meta.Authority != AuthorityDestination {
		return outcome{}, fmt.Errorf("%w: the authority has not moved", ErrRefused)
	}
	return o.drain(ctx, held)
}

// runRetire takes legacy out of the read path, which is only safe once nothing
// is left in it that the destination does not have.
func (o *Orchestrator) runRetire(ctx context.Context, held lease) (outcome, error) {
	if _, err := o.drain(ctx, held); err != nil {
		return outcome{}, err
	}
	remaining, legacyMax, err := o.reconcile(ctx, held)
	if err != nil {
		return outcome{}, err
	}
	if remaining != 0 {
		return outcome{}, fmt.Errorf(
			"%w: cannot retire legacy with %d movement(s) differing", ErrRefused, remaining)
	}
	zero := int64(0)
	return outcome{cursor: &legacyMax, divergence: &zero}, nil
}

func (o *Orchestrator) runComplete(ctx context.Context, held lease) (outcome, error) {
	remaining, legacyMax, err := o.reconcile(ctx, held)
	if err != nil {
		return outcome{}, err
	}
	if remaining != 0 {
		return outcome{}, fmt.Errorf("%w: %d movement(s) still differ", ErrRefused, remaining)
	}
	zero := int64(0)
	return outcome{cursor: &legacyMax, divergence: &zero}, nil
}

// drain applies everything the legacy log holds that the destination does not.
func (o *Orchestrator) drain(ctx context.Context, held lease) (outcome, error) {
	applier, err := o.newApplier(ctx, held)
	if err != nil {
		return outcome{}, err
	}
	from, err := o.resume(applier.snap)
	if err != nil {
		return outcome{}, err
	}
	cursor, err := applier.applyLog(ctx, from, 0, held)
	if err != nil {
		return outcome{}, err
	}
	return outcome{cursor: &cursor}, nil
}

// runCutover moves the serving authority to the destination. The gate is
// judged on the stores as they are at this moment, not on what a previous
// phase found, because production has been writing to legacy the whole time.
func (o *Orchestrator) runCutover(ctx context.Context, held lease) (outcome, error) {
	remaining, legacyMax, err := o.reconcile(ctx, held)
	if err != nil {
		return outcome{}, err
	}
	if remaining != 0 {
		return outcome{}, fmt.Errorf(
			"%w: cannot move the authority with %d movement(s) differing", ErrRefused, remaining)
	}
	zero := int64(0)
	return outcome{cursor: &legacyMax, divergence: &zero, authority: AuthorityDestination}, nil
}
