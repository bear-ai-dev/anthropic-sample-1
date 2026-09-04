// storesvc is the ledger's storage service. It owns the destination database
// (Gel) and the coordination keyspace (Redis) and exposes them over a local
// unix socket as a small set of typed operations.
//
// It is not part of the deliverable: it is installed root-owned in the image,
// stands in for a managed store, and is where write faults are produced. A
// client cannot tell a lost acknowledgement from a rollback, because both
// decisions are taken here and the connection is closed either way.
package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"log"
	"net"
	"os"
	"os/signal"
	"path/filepath"
	"sync"
	"syscall"
	"time"

	gel "github.com/geldata/gel-go"
	"github.com/geldata/gel-go/gelcfg"
	"github.com/redis/go-redis/v9"
	"golang.org/x/sys/unix"
)

type Server struct {
	mu      sync.Mutex
	gel     *gel.Client
	rdb     *redis.Client
	faults  *FaultTable
	oplog   *OpLog
	stalls  *StallGate
	dataDir string
}

func main() {
	var (
		sock     = flag.String("socket", "/run/ledger/store.sock", "client socket path")
		ctlSock  = flag.String("control-socket", "/run/ledger/store-control.sock", "control socket path (root only)")
		dsn      = flag.String("dsn", "gel://admin:dev@localhost:5656/main", "Gel DSN")
		redisURL = flag.String("redis", "redis://127.0.0.1:6379/0", "Redis URL")
		plan     = flag.String("plan", "", "held-out fault plan (JSON)")
		devSmoke = flag.String("dev-smoke", "", "toggle the fixed smoke faults by the presence of this file")
		oplog    = flag.String("oplog", "", "append every completed write here (JSONL)")
		waitSecs = flag.Int("wait", 300, "seconds to wait for the stores to answer")

		devReset  = flag.String("dev-reset", "", "watch for this file and put the box back to a fresh trial")
		devLegacy = flag.String("dev-legacy", "", "legacy ledger a dev reset restores")
		devSeed   = flag.String("dev-legacy-seed", "", "pristine copy a dev reset restores from")
	)
	flag.Parse()

	log.SetFlags(log.Ltime | log.Lmicroseconds)
	log.SetPrefix("storesvc ")

	if err := os.MkdirAll(filepath.Dir(*sock), 0o755); err != nil {
		log.Fatalf("socket directory: %v", err)
	}

	srv := &Server{
		faults: NewFaultTable(),
		oplog:  NewOpLog(*oplog),
		stalls: NewStallGate(),
	}

	// A plan handed over by the operator wins, and once it is in force nothing
	// on the box can take it away. Failing that, the development box offers a
	// fixed set of smoke faults, toggled by a file: enough to show a submission
	// meets each mechanic, and not the schedule a graded run uses.
	switch {
	case *plan != "":
		if err := srv.faults.LoadFile(*plan); err != nil {
			log.Printf("fault plan %s not loaded: %v", *plan, err)
		} else {
			log.Printf("fault plan loaded from %s (%d rules)", *plan, srv.faults.Len())
		}
	case *devSmoke != "":
		go srv.watchSmoke(*devSmoke)
	}

	client, err := gel.CreateClientDSN(*dsn, gelcfg.Options{
		TLSOptions: gelcfg.TLSOptions{SecurityMode: "insecure"},
	})
	if err != nil {
		log.Fatalf("gel client: %v", err)
	}
	srv.gel = client

	opts, err := redis.ParseURL(*redisURL)
	if err != nil {
		log.Fatalf("redis url: %v", err)
	}
	srv.rdb = redis.NewClient(opts)

	deadline := time.Now().Add(time.Duration(*waitSecs) * time.Second)
	for {
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		gelErr := srv.gel.EnsureConnected(ctx)
		redisErr := srv.rdb.Ping(ctx).Err()
		cancel()
		if gelErr == nil && redisErr == nil {
			break
		}
		if time.Now().After(deadline) {
			log.Fatalf("stores never answered: gel=%v redis=%v", gelErr, redisErr)
		}
		time.Sleep(500 * time.Millisecond)
	}
	log.Printf("stores ready")

	if err := srv.ensureMeta(context.Background()); err != nil {
		log.Fatalf("meta row: %v", err)
	}

	stop := make(chan os.Signal, 2)
	signal.Notify(stop, syscall.SIGINT, syscall.SIGTERM)

	clients := srv.listen(*sock, 0o777, srv.serveClient)
	control := srv.listen(*ctlSock, 0o700, srv.serveControl)
	defer clients.Close()
	defer control.Close()

	if *devReset != "" {
		go srv.watchReset(*devReset, *devLegacy, *devSeed, *devSmoke)
	}

	if err := os.WriteFile(filepath.Join(filepath.Dir(*sock), "store.ready"), []byte("ok\n"), 0o644); err != nil {
		log.Printf("ready marker: %v", err)
	}
	log.Printf("listening on %s", *sock)
	<-stop
	log.Printf("shutting down")
}

func (s *Server) listen(path string, mode os.FileMode, handler func(net.Conn)) net.Listener {
	_ = os.Remove(path)
	ln, err := net.Listen("unix", path)
	if err != nil {
		log.Fatalf("listen %s: %v", path, err)
	}
	if err := os.Chmod(path, mode); err != nil {
		log.Fatalf("chmod %s: %v", path, err)
	}
	go func() {
		for {
			conn, err := ln.Accept()
			if err != nil {
				return
			}
			go handler(conn)
		}
	}()
	return ln
}

// peerPID identifies the calling process from the kernel rather than from
// anything the caller says about itself.
func peerPID(conn net.Conn) int {
	unixConn, ok := conn.(*net.UnixConn)
	if !ok {
		return 0
	}
	raw, err := unixConn.SyscallConn()
	if err != nil {
		return 0
	}
	pid := 0
	_ = raw.Control(func(fd uintptr) {
		cred, err := unix.GetsockoptUcred(int(fd), unix.SOL_SOCKET, unix.SO_PEERCRED)
		if err == nil {
			pid = int(cred.Pid)
		}
	})
	return pid
}

type request struct {
	Op      string          `json:"op"`
	Payload json.RawMessage `json:"-"`
	raw     map[string]json.RawMessage
}

func (s *Server) serveClient(conn net.Conn) {
	defer conn.Close()
	pid := peerPID(conn)
	dec := json.NewDecoder(conn)
	enc := json.NewEncoder(conn)
	for {
		var raw map[string]json.RawMessage
		if err := dec.Decode(&raw); err != nil {
			if !errors.Is(err, io.EOF) {
				log.Printf("pid=%d decode: %v", pid, err)
			}
			return
		}
		op := ""
		if v, ok := raw["op"]; ok {
			_ = json.Unmarshal(v, &op)
		}
		resp, closeNow := s.dispatch(context.Background(), pid, op, raw)
		if closeNow {
			// A lost acknowledgement: the outcome of the write is already
			// decided, and the caller is told nothing at all about it.
			return
		}
		if err := enc.Encode(resp); err != nil {
			return
		}
	}
}

func fail(format string, args ...any) map[string]any {
	return map[string]any{"ok": false, "error": fmt.Sprintf(format, args...)}
}

// dispatch takes no lock of its own: a stalled write has to be able to sit
// there without any other caller noticing, so serialisation happens around the
// store access itself and not around the wait.
func (s *Server) dispatch(ctx context.Context, pid int, op string, raw map[string]json.RawMessage) (map[string]any, bool) {
	switch op {
	case "ping":
		return map[string]any{"ok": true}, false
	case "member_get":
		return s.memberGet(ctx, raw)
	case "member_list":
		return s.memberList(ctx)
	case "entry_list":
		return s.entryList(ctx, raw)
	case "entry_for_member":
		return s.entryForMember(ctx, raw)
	case "entry_keys":
		return s.entryKeys(ctx)
	case "entry_count":
		return s.entryCount(ctx)
	case "meta_get":
		return s.metaGet(ctx)
	case "kv_get":
		return s.kvGet(ctx, raw)
	case "kv_keys":
		return s.kvKeys(ctx, raw)
	case "member_put", "entry_add", "entry_remove", "meta_put", "kv_set", "kv_cas", "kv_del":
		return s.write(ctx, pid, op, raw)
	default:
		return fail("unknown op %q", op), false
	}
}

func decode[T any](raw map[string]json.RawMessage, key string) (T, error) {
	var out T
	v, ok := raw[key]
	if !ok {
		return out, fmt.Errorf("missing field %q", key)
	}
	if err := json.Unmarshal(v, &out); err != nil {
		return out, fmt.Errorf("field %q: %w", key, err)
	}
	return out, nil
}
