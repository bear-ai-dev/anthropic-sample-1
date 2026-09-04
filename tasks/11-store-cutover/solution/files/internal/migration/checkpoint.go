package migration

import (
	"encoding/json"
	"errors"

	"membershipledger/internal/store"
)

// checkpoint is how far the legacy log has been applied. It is a position, not
// a claim: it is written after the movements it covers are durable, so a
// restart re-reads a stretch of log it may already have applied. That is safe
// only because applying a movement twice is prevented on the way in, and it is
// the trade that makes a checkpoint recoverable at all.
type checkpoint struct {
	Cursor int64  `json:"cursor"`
	Holder string `json:"holder"`
	Fence  int64  `json:"fence"`
}

func (o *Orchestrator) readCheckpoint() (checkpoint, error) {
	raw, present, err := o.deps.Store.KVGet(checkpointKey)
	if err != nil {
		return checkpoint{}, err
	}
	if !present {
		return checkpoint{}, nil
	}
	var out checkpoint
	if err := json.Unmarshal([]byte(raw), &out); err != nil {
		return checkpoint{}, nil
	}
	return out, nil
}

// saveCheckpoint records the position. It never reports failure upwards: a
// checkpoint that did not land costs a repeat of work that is safe to repeat,
// whereas abandoning a phase because a position could not be filed away costs
// the phase.
func (o *Orchestrator) saveCheckpoint(cursor int64, held lease) {
	blob, err := json.Marshal(checkpoint{Cursor: cursor, Holder: held.Holder, Fence: held.Fence})
	if err != nil {
		return
	}
	if err := o.deps.Store.KVSet(checkpointKey, string(blob)); err != nil {
		if !errors.Is(err, store.ErrOutcomeUnknown) {
			return
		}
		// Unknown means it may or may not be there. Either is survivable, so
		// try once more and then let the position be rediscovered.
		_ = o.deps.Store.KVSet(checkpointKey, string(blob))
	}
}

// resume is the position to read the legacy log from. The checkpoint is only a
// hint: what the destination actually holds is the truth, and if the two
// disagree the lower of them is the safe place to start.
func (o *Orchestrator) resume(snap *snapshot) (int64, error) {
	saved, err := o.readCheckpoint()
	if err != nil {
		return 0, err
	}
	if saved.Cursor < snap.maxGlobal {
		return saved.Cursor, nil
	}
	return snap.maxGlobal, nil
}
