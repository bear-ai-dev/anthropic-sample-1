package main

import (
	"fmt"
	"log"
	"os"
	"syscall"
	"time"
)

// watchReset gives whoever is working on the box a way back to a fresh trial:
// touch the request file and the destination store, the coordination keyspace
// and the legacy ledger all go back to how they started. It is wired up by the
// development entrypoint only. A graded run starts the service without these
// flags, so this loop does not exist while a submission is being marked.
func (s *Server) watchReset(request, legacy, seed, smokePath string) {
	log.Printf("dev reset: touch %s to start a fresh trial", request)
	done := request + ".done"
	for {
		if _, err := os.Stat(request); err != nil {
			time.Sleep(time.Second)
			continue
		}
		os.Remove(done)
		log.Printf("dev reset: requested")

		outcome := "ok"
		if reply := s.reset(); reply["ok"] != true {
			outcome = fmt.Sprintf("stores: %v", reply["error"])
		} else if err := restoreLegacy(legacy, seed); err != nil {
			outcome = fmt.Sprintf("legacy ledger: %v", err)
		}

		// The reset drops the fault rules with everything else, so put the smoke
		// faults back if they were asked for, rather than leaving the box quietly
		// fault-free and a second run looking better than the first for no
		// reason the person driving it can see.
		if smokePath != "" {
			if _, err := os.Stat(smokePath); err == nil {
				s.faults.Set(smokeRules())
				log.Printf("dev reset: smoke faults back on (%d rules)", s.faults.Len())
			}
		}

		os.Remove(request)
		if err := os.WriteFile(done, []byte(outcome+"\n"), 0o644); err != nil {
			log.Printf("dev reset: %v", err)
		}
		log.Printf("dev reset: %s", outcome)
	}
}

// restoreLegacy puts the pristine ledger back, keeping the ownership and mode
// the working copy had so that whoever was using it still can.
func restoreLegacy(path, seed string) error {
	if path == "" || seed == "" {
		return nil
	}
	var uid, gid = -1, -1
	mode := os.FileMode(0o644)
	if info, err := os.Stat(path); err == nil {
		mode = info.Mode().Perm()
		if st, ok := info.Sys().(*syscall.Stat_t); ok {
			uid, gid = int(st.Uid), int(st.Gid)
		}
	}

	blob, err := os.ReadFile(seed)
	if err != nil {
		return err
	}
	tmp := path + ".restoring"
	if err := os.WriteFile(tmp, blob, mode); err != nil {
		return err
	}
	if uid >= 0 {
		if err := os.Chown(tmp, uid, gid); err != nil {
			return err
		}
	}
	if err := os.Rename(tmp, path); err != nil {
		return err
	}
	// SQLite's sidecars describe the file that was just replaced.
	os.Remove(path + "-wal")
	os.Remove(path + "-shm")
	return nil
}
