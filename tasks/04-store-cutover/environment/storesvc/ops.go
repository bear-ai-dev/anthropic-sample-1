package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"strconv"
	"strings"
	"syscall"

	"github.com/geldata/gel-go/geltypes"
	"github.com/redis/go-redis/v9"
)

const metaSlot = "singleton"

var errRollback = errors.New("storesvc: rollback")

type entryIn struct {
	EntryID    string `json:"entry_id"`
	MemberID   string `json:"member_id"`
	Seq        int64  `json:"seq"`
	GlobalSeq  int64  `json:"global_seq"`
	DeltaCents int64  `json:"delta_cents"`
	Reason     string `json:"reason"`
	WrittenAt  string `json:"written_at"`
}

// entryKeyIn identifies a ledger movement for removal. It names the movement,
// not a row: every row carrying it goes.
type entryKeyIn struct {
	MemberID string `json:"member_id"`
	Seq      int64  `json:"seq"`
}

type memberIn struct {
	MemberID     string `json:"member_id"`
	Tier         string `json:"tier"`
	BalanceCents int64  `json:"balance_cents"`
	Version      int64  `json:"version"`
	Deleted      bool   `json:"deleted"`
	UpdatedAt    string `json:"updated_at"`
}

type metaIn struct {
	Phase      string `json:"phase"`
	Authority  string `json:"authority"`
	Fence      int64  `json:"fence"`
	Cursor     int64  `json:"cursor"`
	Divergence int64  `json:"divergence"`
}

// ---------------------------------------------------------------- reads

func (s *Server) queryJSON(ctx context.Context, query string, args ...any) (json.RawMessage, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	var out []byte
	if err := s.gel.QueryJSON(ctx, query, &out, args...); err != nil {
		return nil, err
	}
	return json.RawMessage(out), nil
}

func (s *Server) memberGet(ctx context.Context, raw map[string]json.RawMessage) (map[string]any, bool) {
	id, err := decode[string](raw, "member_id")
	if err != nil {
		return fail("%v", err), false
	}
	rows, err := s.queryJSON(ctx, `
		select Member { member_id, tier, balance_cents, version, deleted, updated_at }
		filter .member_id = <str>$0`, id)
	if err != nil {
		return fail("member_get: %v", err), false
	}
	var list []json.RawMessage
	_ = json.Unmarshal(rows, &list)
	if len(list) == 0 {
		return map[string]any{"ok": true, "member": nil}, false
	}
	return map[string]any{"ok": true, "member": list[0]}, false
}

func (s *Server) memberList(ctx context.Context) (map[string]any, bool) {
	rows, err := s.queryJSON(ctx, `
		select Member { member_id, tier, balance_cents, version, deleted, updated_at }
		order by .member_id`)
	if err != nil {
		return fail("member_list: %v", err), false
	}
	return map[string]any{"ok": true, "members": rows}, false
}

func (s *Server) entryList(ctx context.Context, raw map[string]json.RawMessage) (map[string]any, bool) {
	after, _ := decode[int64](raw, "after_global_seq")
	limit, err := decode[int64](raw, "limit")
	if err != nil || limit <= 0 {
		limit = 5000
	}
	rows, err := s.queryJSON(ctx, `
		select LedgerEntry {
			entry_id, member_id, seq, global_seq, delta_cents, reason, written_at
		}
		filter .global_seq > <int64>$0
		order by .global_seq
		limit <int64>$1`, after, limit)
	if err != nil {
		return fail("entry_list: %v", err), false
	}
	return map[string]any{"ok": true, "entries": rows}, false
}

func (s *Server) entryForMember(ctx context.Context, raw map[string]json.RawMessage) (map[string]any, bool) {
	id, err := decode[string](raw, "member_id")
	if err != nil {
		return fail("%v", err), false
	}
	rows, err := s.queryJSON(ctx, `
		select LedgerEntry {
			entry_id, member_id, seq, global_seq, delta_cents, reason, written_at
		}
		filter .member_id = <str>$0
		order by .seq`, id)
	if err != nil {
		return fail("entry_for_member: %v", err), false
	}
	return map[string]any{"ok": true, "entries": rows}, false
}

func (s *Server) entryKeys(ctx context.Context) (map[string]any, bool) {
	rows, err := s.queryJSON(ctx, `
		select LedgerEntry { member_id, seq, global_seq } order by .global_seq`)
	if err != nil {
		return fail("entry_keys: %v", err), false
	}
	return map[string]any{"ok": true, "keys": rows}, false
}

func (s *Server) entryCount(ctx context.Context) (map[string]any, bool) {
	rows, err := s.queryJSON(ctx, `select count(LedgerEntry)`)
	if err != nil {
		return fail("entry_count: %v", err), false
	}
	var counts []int64
	_ = json.Unmarshal(rows, &counts)
	n := int64(0)
	if len(counts) > 0 {
		n = counts[0]
	}
	return map[string]any{"ok": true, "count": n}, false
}

func (s *Server) metaGet(ctx context.Context) (map[string]any, bool) {
	rows, err := s.queryJSON(ctx, `
		select MigrationMeta { phase, authority, fence, cursor, divergence }
		filter .slot = <str>$0`, metaSlot)
	if err != nil {
		return fail("meta_get: %v", err), false
	}
	var list []json.RawMessage
	_ = json.Unmarshal(rows, &list)
	if len(list) == 0 {
		return fail("meta_get: no meta row"), false
	}
	return map[string]any{"ok": true, "meta": list[0]}, false
}

func (s *Server) kvGet(ctx context.Context, raw map[string]json.RawMessage) (map[string]any, bool) {
	key, err := decode[string](raw, "key")
	if err != nil {
		return fail("%v", err), false
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	val, err := s.rdb.Get(ctx, key).Result()
	if errors.Is(err, redis.Nil) {
		return map[string]any{"ok": true, "value": nil}, false
	}
	if err != nil {
		return fail("kv_get: %v", err), false
	}
	return map[string]any{"ok": true, "value": val}, false
}

func (s *Server) kvKeys(ctx context.Context, raw map[string]json.RawMessage) (map[string]any, bool) {
	prefix, _ := decode[string](raw, "prefix")
	s.mu.Lock()
	defer s.mu.Unlock()
	keys, err := s.rdb.Keys(ctx, prefix+"*").Result()
	if err != nil {
		return fail("kv_keys: %v", err), false
	}
	return map[string]any{"ok": true, "keys": keys}, false
}

// ---------------------------------------------------------------- writes

// write is the whole fault surface. It works out what the write contains, asks
// the fault table what should happen to it, performs it, and then reports back
// to the caller — or does not, when the acknowledgement is the thing being
// lost.
func (s *Server) write(ctx context.Context, pid int, op string, raw map[string]json.RawMessage) (map[string]any, bool) {
	facts, err := writeFactsFor(op, pid, raw)
	if err != nil {
		return fail("%v", err), false
	}

	action, ruleID := s.faults.Match(facts.writeFacts)
	if action == ActionStall {
		s.stalls.Park(pid, op, facts.Value, true)
		action = ActionProceed
	} else {
		s.stalls.Park(pid, op, facts.Value, false)
	}

	rollback := action == ActionUnknownRollback
	resp, applied, err := s.apply(ctx, op, raw, rollback)

	record := map[string]any{
		"op":      op,
		"pid":     pid,
		"applied": applied,
		"action":  action,
	}
	if ruleID != "" {
		record["rule"] = ruleID
	}
	if err != nil {
		record["error"] = err.Error()
	}
	for k, v := range facts.summary {
		record[k] = v
	}
	if extra, ok := resp["_log"]; ok {
		record["detail"] = extra
		delete(resp, "_log")
	}
	s.oplog.Append(record)

	if err != nil && action == ActionProceed {
		return fail("%s: %v", op, err), false
	}

	switch action {
	case ActionKillAfterCommit:
		// The durable write has landed and the process dies before it can
		// learn anything at all about it, let alone record a checkpoint.
		log.Printf("rule %s kills pid=%d after commit of %s", ruleID, pid, op)
		if pid > 1 {
			if err := syscall.Kill(pid, syscall.SIGKILL); err != nil {
				log.Printf("kill %d: %v", pid, err)
			}
		}
		return nil, true
	case ActionUnknownCommit, ActionUnknownRollback:
		return nil, true
	}
	return resp, false
}

func (s *Server) apply(ctx context.Context, op string, raw map[string]json.RawMessage, rollback bool) (map[string]any, bool, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	switch op {
	case "kv_set", "kv_cas", "kv_del":
		return s.applyKV(ctx, op, raw, rollback)
	}

	resp := map[string]any{"ok": true}
	err := s.gel.Tx(ctx, func(ctx context.Context, tx geltypes.Tx) error {
		clear(resp)
		resp["ok"] = true
		switch op {
		case "member_put":
			members, err := decode[[]memberIn](raw, "members")
			if err != nil {
				return err
			}
			blob, _ := json.Marshal(members)
			if err := tx.Execute(ctx, memberUpsertQuery, string(blob)); err != nil {
				return err
			}
			resp["written"] = len(members)
		case "entry_add":
			entries, err := decode[[]entryIn](raw, "entries")
			if err != nil {
				return err
			}
			if len(entries) > 0 {
				blob, _ := json.Marshal(entries)
				if err := tx.Execute(ctx, entryInsertQuery, string(blob)); err != nil {
					return err
				}
			}
			resp["inserted"] = len(entries)
		case "entry_remove":
			keys, err := decode[[]entryKeyIn](raw, "keys")
			if err != nil {
				return err
			}
			if len(keys) > 0 {
				blob, _ := json.Marshal(keys)
				if err := tx.Execute(ctx, entryDeleteQuery, string(blob)); err != nil {
					return err
				}
			}
			resp["removed"] = len(keys)
		case "meta_put":
			return s.applyMeta(ctx, tx, raw, resp)
		default:
			return fmt.Errorf("unknown write %q", op)
		}
		if rollback {
			return errRollback
		}
		return nil
	})
	if errors.Is(err, errRollback) {
		return resp, false, nil
	}
	if err != nil {
		return map[string]any{}, false, err
	}
	return resp, true, nil
}

// applyMeta is a compare-and-set on the migration record. The expected value
// is optional; supplying it is how a writer refuses to overwrite a record that
// has moved on since it read it.
func (s *Server) applyMeta(ctx context.Context, tx geltypes.Tx, raw map[string]json.RawMessage, resp map[string]any) error {
	want, err := decode[metaIn](raw, "meta")
	if err != nil {
		return err
	}
	var current []metaIn
	var blob []byte
	if err := tx.QueryJSON(ctx, `
		select MigrationMeta { phase, authority, fence, cursor, divergence }
		filter .slot = <str>$0`, &blob, metaSlot); err != nil {
		return err
	}
	if err := json.Unmarshal(blob, &current); err != nil {
		return err
	}
	if len(current) == 0 {
		return errors.New("no meta row")
	}
	if expectRaw, ok := raw["expect"]; ok && string(expectRaw) != "null" {
		var expect metaIn
		if err := json.Unmarshal(expectRaw, &expect); err != nil {
			return err
		}
		if expect != current[0] {
			resp["ok"] = false
			resp["error"] = "conflict"
			resp["meta"] = current[0]
			resp["_log"] = map[string]any{"conflict": true, "have": current[0], "expect": expect}
			return errRollback
		}
	}
	payload, _ := json.Marshal(want)
	if err := tx.Execute(ctx, `
		with raw := to_json(<str>$0)
		update MigrationMeta filter .slot = <str>$1 set {
			phase := <str>raw['phase'],
			authority := <str>raw['authority'],
			fence := <int64>raw['fence'],
			cursor := <int64>raw['cursor'],
			divergence := <int64>raw['divergence']
		}`, string(payload), metaSlot); err != nil {
		return err
	}
	resp["meta"] = want
	resp["_log"] = map[string]any{"meta": want, "before": current[0]}
	return nil
}

func (s *Server) applyKV(ctx context.Context, op string, raw map[string]json.RawMessage, rollback bool) (map[string]any, bool, error) {
	key, err := decode[string](raw, "key")
	if err != nil {
		return nil, false, err
	}
	if rollback {
		// Nothing reaches Redis, and the caller is told nothing either.
		return map[string]any{"ok": true}, false, nil
	}
	switch op {
	case "kv_set":
		value, err := decode[string](raw, "value")
		if err != nil {
			return nil, false, err
		}
		if err := s.rdb.Set(ctx, key, value, 0).Err(); err != nil {
			return nil, false, err
		}
		return map[string]any{"ok": true, "_log": map[string]any{"key": key, "value": value}}, true, nil
	case "kv_del":
		if err := s.rdb.Del(ctx, key).Err(); err != nil {
			return nil, false, err
		}
		return map[string]any{"ok": true, "_log": map[string]any{"key": key}}, true, nil
	case "kv_cas":
		value, err := decode[string](raw, "value")
		if err != nil {
			return nil, false, err
		}
		var expect *string
		if rawExpect, ok := raw["expect"]; ok && string(rawExpect) != "null" {
			var got string
			if err := json.Unmarshal(rawExpect, &got); err != nil {
				return nil, false, err
			}
			expect = &got
		}
		have, err := s.rdb.Get(ctx, key).Result()
		missing := errors.Is(err, redis.Nil)
		if err != nil && !missing {
			return nil, false, err
		}
		ok := (expect == nil && missing) || (expect != nil && !missing && *expect == have)
		if !ok {
			return map[string]any{
				"ok": true, "swapped": false, "value": currentOrNil(missing, have),
				"_log": map[string]any{"key": key, "swapped": false},
			}, true, nil
		}
		if err := s.rdb.Set(ctx, key, value, 0).Err(); err != nil {
			return nil, false, err
		}
		return map[string]any{
			"ok": true, "swapped": true, "value": value,
			"_log": map[string]any{"key": key, "swapped": true, "value": value},
		}, true, nil
	}
	return nil, false, fmt.Errorf("unknown kv op %q", op)
}

func currentOrNil(missing bool, have string) any {
	if missing {
		return nil
	}
	return have
}

// ---------------------------------------------------------------- facts

type factsWithSummary struct {
	writeFacts
	summary map[string]any
}

func writeFactsFor(op string, pid int, raw map[string]json.RawMessage) (factsWithSummary, error) {
	out := factsWithSummary{
		writeFacts: writeFacts{Op: op, Pid: pid},
		summary:    map[string]any{},
	}
	switch op {
	case "entry_add":
		entries, err := decode[[]entryIn](raw, "entries")
		if err != nil {
			return out, err
		}
		keys := make([]string, 0, len(entries))
		for _, e := range entries {
			out.GlobalSeqs = append(out.GlobalSeqs, e.GlobalSeq)
			keys = append(keys, e.MemberID+"#"+strconv.FormatInt(e.Seq, 10))
		}
		out.summary["count"] = len(entries)
		out.summary["global_seqs"] = out.GlobalSeqs
		out.summary["keys"] = keys
	case "entry_remove":
		keys, err := decode[[]entryKeyIn](raw, "keys")
		if err != nil {
			return out, err
		}
		named := make([]string, 0, len(keys))
		for _, k := range keys {
			named = append(named, k.MemberID+"#"+strconv.FormatInt(k.Seq, 10))
		}
		out.summary["count"] = len(keys)
		out.summary["keys"] = named
		out.Value = strings.Join(named, ",")
	case "member_put":
		members, err := decode[[]memberIn](raw, "members")
		if err != nil {
			return out, err
		}
		ids := make([]string, 0, len(members))
		for _, m := range members {
			ids = append(ids, m.MemberID)
		}
		out.summary["count"] = len(members)
		out.Value = strings.Join(ids, ",")
	case "meta_put":
		meta, err := decode[metaIn](raw, "meta")
		if err != nil {
			return out, err
		}
		out.Key = "meta"
		out.Value = meta.Phase + "/" + meta.Authority
		out.summary["want"] = meta
	case "kv_set", "kv_cas", "kv_del":
		key, err := decode[string](raw, "key")
		if err != nil {
			return out, err
		}
		out.Key = key
		if v, ok := raw["value"]; ok {
			var s string
			_ = json.Unmarshal(v, &s)
			out.Value = s
		}
		out.summary["key"] = key
		if out.Value != "" {
			out.summary["value"] = out.Value
		}
	}
	return out, nil
}

func (s *Server) ensureMeta(ctx context.Context) error {
	return s.gel.Execute(ctx, `
		insert MigrationMeta {
			slot := <str>$0, phase := 'INIT', authority := 'legacy',
			fence := 0, cursor := 0, divergence := 0
		} unless conflict on .slot`, metaSlot)
}

const memberUpsertQuery = `
with raw := to_json(<str>$0)
for x in json_array_unpack(raw) union (
	insert Member {
		member_id := <str>x['member_id'],
		tier := <str>x['tier'],
		balance_cents := <int64>x['balance_cents'],
		version := <int64>x['version'],
		deleted := <bool>x['deleted'],
		updated_at := <str>x['updated_at']
	} unless conflict on .member_id else (
		update Member set {
			tier := <str>x['tier'],
			balance_cents := <int64>x['balance_cents'],
			version := <int64>x['version'],
			deleted := <bool>x['deleted'],
			updated_at := <str>x['updated_at']
		}
	)
)`

const entryDeleteQuery = `
with raw := to_json(<str>$0)
for x in json_array_unpack(raw) union (
	delete LedgerEntry
	filter .member_id = <str>x['member_id'] and .seq = <int64>x['seq']
)`

const entryInsertQuery = `
with raw := to_json(<str>$0)
for x in json_array_unpack(raw) union (
	insert LedgerEntry {
		entry_id := <str>x['entry_id'],
		member_id := <str>x['member_id'],
		seq := <int64>x['seq'],
		global_seq := <int64>x['global_seq'],
		delta_cents := <int64>x['delta_cents'],
		reason := <str>x['reason'],
		written_at := <str>x['written_at']
	}
)`
