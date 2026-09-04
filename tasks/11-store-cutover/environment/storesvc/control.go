package main

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"log"
	"net"
	"os"
	"sync"
	"time"
)

// OpLog is the store's own record of what was written. It is the operator's
// view of the truth: it is produced by the store rather than by the caller, so
// a caller cannot leave a tidier trail than the writes it actually made.
type OpLog struct {
	mu   sync.Mutex
	path string
	file *os.File
	seq  int64
}

func NewOpLog(path string) *OpLog {
	l := &OpLog{}
	if path != "" {
		l.Rotate(path)
	}
	return l
}

func (l *OpLog) Rotate(path string) {
	l.mu.Lock()
	defer l.mu.Unlock()
	if l.file != nil {
		_ = l.file.Close()
		l.file = nil
	}
	l.path = path
	l.seq = 0
	if path == "" {
		return
	}
	file, err := os.OpenFile(path, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o600)
	if err != nil {
		log.Printf("oplog %s: %v", path, err)
		return
	}
	l.file = file
}

func (l *OpLog) Append(record map[string]any) {
	l.mu.Lock()
	defer l.mu.Unlock()
	if l.file == nil {
		return
	}
	l.seq++
	record["n"] = l.seq
	record["t"] = time.Now().UTC().Format(time.RFC3339Nano)
	line, err := json.Marshal(record)
	if err != nil {
		return
	}
	_, _ = l.file.Write(append(line, '\n'))
	_ = l.file.Sync()
}

func (s *Server) serveControl(conn net.Conn) {
	defer conn.Close()
	dec := json.NewDecoder(conn)
	enc := json.NewEncoder(conn)
	for {
		var raw map[string]json.RawMessage
		if err := dec.Decode(&raw); err != nil {
			if !errors.Is(err, io.EOF) {
				log.Printf("control decode: %v", err)
			}
			return
		}
		op := ""
		if v, ok := raw["op"]; ok {
			_ = json.Unmarshal(v, &op)
		}
		if err := enc.Encode(s.control(op, raw)); err != nil {
			return
		}
	}
}

func (s *Server) control(op string, raw map[string]json.RawMessage) map[string]any {
	switch op {
	case "ping":
		return map[string]any{"ok": true}
	case "plan":
		rules, err := decode[[]*Rule](raw, "rules")
		if err != nil {
			return fail("%v", err)
		}
		s.faults.Pin(rules)
		log.Printf("plan installed: %d rules", len(rules))
		return map[string]any{"ok": true, "rules": len(rules)}
	case "fired":
		return map[string]any{"ok": true, "fired": s.faults.Fired()}
	case "arm_stall":
		id, _ := decode[string](raw, "id")
		pid, _ := decode[int](raw, "pid")
		target, _ := decode[string](raw, "target_op")
		value, _ := decode[[]string](raw, "value_contains")
		s.stalls.Arm(id, pid, target, value)
		log.Printf("stall %q armed for pid=%d op=%q value=%v", id, pid, target, value)
		return map[string]any{"ok": true}
	case "stall_stats":
		out := s.stalls.Stats()
		out["ok"] = true
		return out
	case "release_stall":
		id, _ := decode[string](raw, "id")
		s.stalls.Release(id)
		log.Printf("stall %q released", id)
		return map[string]any{"ok": true}
	case "oplog":
		path, err := decode[string](raw, "path")
		if err != nil {
			return fail("%v", err)
		}
		s.oplog.Rotate(path)
		return map[string]any{"ok": true}
	case "reset":
		return s.reset()
	default:
		return fail("unknown control op %q", op)
	}
}

// reset returns both stores to the state a fresh trial starts from. Only the
// operator can ask for it.
func (s *Server) reset() map[string]any {
	s.mu.Lock()
	defer s.mu.Unlock()
	ctx, cancel := context.WithTimeout(context.Background(), 120*time.Second)
	defer cancel()

	for _, stmt := range []string{"delete LedgerEntry", "delete Member", "delete MigrationMeta"} {
		if err := s.gel.Execute(ctx, stmt); err != nil {
			return fail("reset %s: %v", stmt, err)
		}
	}
	if err := s.ensureMeta(ctx); err != nil {
		return fail("reset meta: %v", err)
	}
	if err := s.rdb.FlushDB(ctx).Err(); err != nil {
		return fail("reset redis: %v", err)
	}
	s.faults.Set(nil)
	s.stalls.Release("")
	return map[string]any{"ok": true}
}
