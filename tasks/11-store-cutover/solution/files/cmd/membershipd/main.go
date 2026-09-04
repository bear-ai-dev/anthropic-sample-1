// membershipd serves the membership ledger.
package main

import (
	"context"
	"errors"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"membershipledger/internal/api"
	"membershipledger/internal/clock"
	"membershipledger/internal/config"
	"membershipledger/internal/ledger"
	"membershipledger/internal/legacy"
	"membershipledger/internal/migration"
	"membershipledger/internal/store"
)

func main() {
	log.SetFlags(log.Ltime | log.Lmicroseconds)
	log.SetPrefix("membershipd ")

	cfg, err := config.Load()
	if err != nil {
		log.Fatalf("config: %v", err)
	}

	legacyStore, err := legacy.Open(cfg.LegacyPath)
	if err != nil {
		log.Fatalf("legacy store %s: %v", cfg.LegacyPath, err)
	}
	defer legacyStore.Close()

	storeClient := store.New(cfg.StoreSocket)
	defer storeClient.Close()

	deadline := time.Now().Add(120 * time.Second)
	for {
		if err := storeClient.Ping(); err == nil {
			break
		} else if time.Now().After(deadline) {
			log.Fatalf("store service on %s never answered: %v", cfg.StoreSocket, err)
		}
		time.Sleep(250 * time.Millisecond)
	}

	serviceClock := clock.New(cfg.ClockFile)
	deps := migration.Deps{
		Cfg:    cfg,
		Legacy: legacyStore,
		Store:  storeClient,
		Clock:  serviceClock,
	}
	orchestrator := migration.New(deps)

	// Reads and writes go through a view of the ledger. Where the migration has
	// got to decides which store answers, so the migration owns the view and
	// keeps the legacy one underneath it.
	legacyView := ledger.LegacyView{Store: legacyStore, Clock: serviceClock}
	var view ledger.View = migration.NewView(deps, legacyView)

	server := &http.Server{
		Addr:              cfg.Listen,
		Handler:           api.New(view, orchestrator).Routes(),
		ReadHeaderTimeout: 10 * time.Second,
	}

	stop := make(chan os.Signal, 2)
	signal.Notify(stop, syscall.SIGINT, syscall.SIGTERM)
	go func() {
		log.Printf("listening on %s (holder %s)", cfg.Listen, cfg.LeaseHolder)
		if err := server.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			log.Fatalf("serve: %v", err)
		}
	}()

	<-stop
	shutdownCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	_ = server.Shutdown(shutdownCtx)
}
