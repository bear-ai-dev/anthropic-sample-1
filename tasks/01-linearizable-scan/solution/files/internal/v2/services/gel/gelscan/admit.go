package gelscan

import (
	"context"
	"encoding/json"
	"fmt"
	"ExampleCo-core/internal/v2/services/gel/gelclient"
	"sort"
	"strings"
	"time"

	"github.com/geldata/gel-go/geltypes"
)

// AdmitOutcome describes what the store decided, independent of how the HTTP
// layer chooses to report it.
type AdmitOutcome string

const (
	// AdmitOutcomeAdmitted means every requested item went from unscanned to
	// scanned in this call, and the new Scan row belongs to this call.
	AdmitOutcomeAdmitted AdmitOutcome = "admitted"
	// AdmitOutcomeAlreadyScanned means at least one requested item already
	// carried a scan, so nothing was written.
	AdmitOutcomeAlreadyScanned AdmitOutcome = "already_scanned"
	// AdmitOutcomePending means at least one requested item is still pending.
	AdmitOutcomePending AdmitOutcome = "pending"
	// AdmitOutcomeUnauthorized means the caller could not be authorised
	// against the event at the moment the write was attempted.
	AdmitOutcomeUnauthorized AdmitOutcome = "unauthorized"
	// AdmitOutcomeNotFound means a requested item does not belong to the event.
	AdmitOutcomeNotFound AdmitOutcome = "not_found"
	// AdmitOutcomeReplayed means the idempotency key had already been used for
	// this very request, so this call re-reports the original result instead of
	// admitting again.
	AdmitOutcomeReplayed AdmitOutcome = "replayed"
	// AdmitOutcomeKeyConflict means the idempotency key has already been used
	// for a different request. A key identifies one call, so this is neither a
	// replay of it nor a new admission: nothing is written either way.
	AdmitOutcomeKeyConflict AdmitOutcome = "key_conflict"
)

// AdmitRequest is one attempt to admit a set of receipt items under a single
// scan.
type AdmitRequest struct {
	EventId          string
	ItemIds          []string
	ScannerUserId    string
	ScanCode         string
	IdempotencyKey   string
	ScanId           string
	Now              time.Time
	ClientDurationMs *int
}

// AdmitResponse reports the decision together with the counts it was based on,
// so the caller can map it onto the status vocabulary the API already uses.
type AdmitResponse struct {
	Outcome      AdmitOutcome
	ScanId       string
	Matched      int
	Eligible     int
	PendingCount int
	ScannedCount int
	Admitted     int
	Authorized   bool
}

// admitQuery does the whole admission as one statement, which is what makes it
// atomic: authorisation, eligibility, the idempotency claim, the Scan row and
// the append to every item either all happen or none of them do.
//
// Eligibility is re-evaluated here rather than trusted from an earlier read,
// and the append is filtered on the item still having no scans, so two callers
// racing for the same ticket cannot both pass.
//
// The idempotency record is written by this statement and not by a later one.
// A separate write would leave a window in which the tickets are admitted and
// the key is not yet recorded, and a retry arriving in that window admits
// nothing and has nothing to replay, so it can only report a failure for a call
// that in fact succeeded. That window cannot be made small enough to be
// acceptable, because the interesting retries are exactly the ones caused by
// the process dying inside it.
const admitQuery = `
	with
		ids := <array<str>>$ids,
		expected := <int64>$expected,
		scanId := <str>$scanId,
		key := <str>$key,
		hasKey := len(<str>$key) > 0,
		keyPayload := to_json(<str>$keyPayload),
		scanner := <str>$scanner,
		code := <str>$code,

		ev := (select Event filter .firestore_id = <str>$eventId and not .deleted limit 1),

		# Authorisation as of this statement, not as of request arrival.
		hostAuthed := (
			len(scanner) > 0 and exists (
				select PersonaEvent
				filter .event = ev
				  and .persona[is User].firestore_id = scanner
				  and .privilege in {
				      PersonaEventPrivilege.host,
				      PersonaEventPrivilege.bouncer,
				      PersonaEventPrivilege.cohost
				  }
			)
		),
		codeAuthed := (len(code) > 0 and (ev.scan_code ?? '') = code),
		authed := hostAuthed or codeAuthed,

		targets := (select ReceiptItem filter .event = ev and contains(ids, .firestore_id)),
		# A valid ticket is one that is not pending, not refunded and not
		# abandoned, which is the same population the scan-status projection
		# counts. Anything else must never come through the door.
		eligible := (
			select targets
			filter not .pending
			   and .refund_status != RefundStatus.refunded
			   and not .abandoned
			   and len(.scans ?? <array<str>>[]) = 0
		),
		invalidCount := count((select targets filter .refund_status = RefundStatus.refunded or .abandoned)),
		pendingCount := count((select targets filter .pending)),
		scannedCount := count((select targets filter len(.scans ?? <array<str>>[]) > 0)),

		wouldAdmit := authed and count(targets) = expected and count(eligible) = expected,

		# Claim the idempotency key in the same statement. On conflict the set
		# is empty, which means another call already owns this key. The claim is
		# only attempted for a call that is otherwise going to succeed: a
		# refused call has nothing to replay, so consuming the key on its way
		# out would burn a key its caller never got an answer from.
		claim := (
			for _ in (select {1} filter wouldAdmit and hasKey) union (
				insert IdempotencyRecord {
					key := key,
					scope := 'scan-admit',
					payload := keyPayload
				}
				unless conflict on .key
			)
		),

		ok := wouldAdmit and (not hasKey or exists claim),

		created := (
			for _ in (select {1} filter ok) union (
				insert Scan {
					scan_id := scanId,
					firestore_id := scanId,
					scan_type := ScanType.qr,
					date_created := <datetime>$now,
					purchased_ticket_ids := ids,
					client_duration_ms := <optional int32>$clientDurationMs,
					scanner_user := (select User filter .firestore_id = scanner limit 1)
				}
			)
		),

		appended := (
			for item in (select eligible filter ok) union (
				update item set { scans := (item.scans ?? <array<str>>[]) ++ [scanId] }
			)
		)

	select {
		matched := count(targets),
		eligible := count(eligible),
		pending_count := pendingCount,
		scanned_count := scannedCount,
		authorized := authed,
		invalid_count := invalidCount,
		claimed := count(claim),
		created := count(created),
		admitted := count(appended)
	}
`

type admitRow struct {
	Matched      int  `json:"matched"`
	Eligible     int  `json:"eligible"`
	PendingCount int  `json:"pending_count"`
	InvalidCount int  `json:"invalid_count"`
	ScannedCount int  `json:"scanned_count"`
	Authorized   bool `json:"authorized"`
	Claimed      int  `json:"claimed"`
	Created      int  `json:"created"`
	Admitted     int  `json:"admitted"`
}

// requestFingerprint identifies the call a key was taken for. Order is not part
// of the request's meaning, so the same tickets listed differently is the same
// call and must replay rather than conflict.
func requestFingerprint(itemIds []string) string {
	sorted := make([]string, len(itemIds))
	copy(sorted, itemIds)
	sort.Strings(sorted)
	return strings.Join(sorted, ",")
}

// Admit performs a linearizable admission of req.ItemIds.
//
// The whole set is admitted or none of it is. A caller that loses a race
// against another scanner is told so rather than silently overwriting.
func Admit(ctx context.Context, req AdmitRequest) (*AdmitResponse, error) {
	if req.EventId == "" {
		return nil, fmt.Errorf("event id must be provided")
	}
	if len(req.ItemIds) == 0 {
		return nil, fmt.Errorf("at least one receipt item id must be provided")
	}
	if req.ScanId == "" {
		return nil, fmt.Errorf("scan id must be provided")
	}

	fingerprint := requestFingerprint(req.ItemIds)

	// An idempotency key that has already been used never reaches the store
	// again. Which answer it gets depends on whether this is the same call
	// coming back or a different call reusing somebody else's key.
	if req.IdempotencyKey != "" {
		prior, err := lookupIdempotencyRecord(ctx, req.IdempotencyKey)
		if err != nil {
			return nil, err
		}
		if prior != nil {
			return prior.replayOrConflict(fingerprint), nil
		}
	}

	client := gelclient.GetClient()

	var clientDurationMs geltypes.OptionalInt32
	if req.ClientDurationMs != nil {
		clientDurationMs.Set(int32(*req.ClientDurationMs))
	}

	now := req.Now
	if now.IsZero() {
		now = time.Now()
	}

	keyPayload, err := json.Marshal(idempotencyRecord{ScanId: req.ScanId, Fingerprint: fingerprint})
	if err != nil {
		return nil, fmt.Errorf("failed to encode idempotency payload: %w", err)
	}

	params := map[string]any{
		"ids":              req.ItemIds,
		"expected":         int64(len(req.ItemIds)),
		"scanId":           req.ScanId,
		"key":              req.IdempotencyKey,
		"keyPayload":       string(keyPayload),
		"scanner":          req.ScannerUserId,
		"code":             req.ScanCode,
		"eventId":          req.EventId,
		"now":              now.UTC(),
		"clientDurationMs": clientDurationMs,
	}

	var output []byte
	if err := client.QueryJSON(ctx, admitQuery, &output, params); err != nil {
		return nil, fmt.Errorf("failed to admit tickets in gel: %w", err)
	}

	var rows []admitRow
	if err := json.Unmarshal(output, &rows); err != nil {
		return nil, fmt.Errorf("failed to unmarshal admit result: %w", err)
	}
	if len(rows) == 0 {
		return nil, fmt.Errorf("admit returned no result")
	}
	row := rows[0]

	resp := &AdmitResponse{
		ScanId:       req.ScanId,
		Matched:      row.Matched,
		Eligible:     row.Eligible,
		PendingCount: row.PendingCount,
		ScannedCount: row.ScannedCount,
		Admitted:     row.Admitted,
		Authorized:   row.Authorized,
	}

	switch {
	case row.Admitted == len(req.ItemIds) && row.Created == 1:
		resp.Outcome = AdmitOutcomeAdmitted
	case !row.Authorized:
		resp.Outcome = AdmitOutcomeUnauthorized
	case row.Matched != len(req.ItemIds) || row.InvalidCount > 0:
		resp.Outcome = AdmitOutcomeNotFound
	case row.PendingCount > 0:
		resp.Outcome = AdmitOutcomePending
	case row.ScannedCount > 0:
		resp.Outcome = AdmitOutcomeAlreadyScanned
	default:
		// Eligible on paper but nothing was written: the idempotency claim was
		// taken between the check above and this statement, by a call that was
		// in flight at the same time. Whose call it was decides the answer.
		if req.IdempotencyKey != "" {
			prior, err := lookupIdempotencyRecord(ctx, req.IdempotencyKey)
			if err != nil {
				return nil, err
			}
			if prior != nil {
				out := prior.replayOrConflict(fingerprint)
				out.Matched, out.Eligible = resp.Matched, resp.Eligible
				return out, nil
			}
		}
		resp.Outcome = AdmitOutcomeAlreadyScanned
	}

	if resp.Outcome != AdmitOutcomeAdmitted && resp.Outcome != AdmitOutcomeReplayed {
		resp.ScanId = ""
	}
	return resp, nil
}

// idempotencyRecord is what a used key remembers: the answer it gave, and the
// call it gave that answer to.
type idempotencyRecord struct {
	ScanId      string `json:"scanId"`
	Fingerprint string `json:"fingerprint"`
}

func (rec *idempotencyRecord) replayOrConflict(fingerprint string) *AdmitResponse {
	// A record written before fingerprints were recorded has nothing to
	// disagree with, so it replays; that is the safer of the two readings for a
	// key whose owning call cannot be identified.
	if rec.Fingerprint != "" && rec.Fingerprint != fingerprint {
		return &AdmitResponse{Outcome: AdmitOutcomeKeyConflict, Authorized: true}
	}
	return &AdmitResponse{Outcome: AdmitOutcomeReplayed, ScanId: rec.ScanId, Authorized: true}
}

// lookupIdempotencyRecord returns what was recorded against key, or nil if the
// key has not been used.
func lookupIdempotencyRecord(ctx context.Context, key string) (*idempotencyRecord, error) {
	client := gelclient.GetClient()

	query := `
		select IdempotencyRecord { payload }
		filter .key = <str>$key and .scope = 'scan-admit'
		limit 1
	`

	var output []byte
	if err := client.QueryJSON(ctx, query, &output, map[string]any{"key": key}); err != nil {
		return nil, fmt.Errorf("failed to read idempotency record: %w", err)
	}

	var rows []struct {
		Payload *json.RawMessage `json:"payload"`
	}
	if err := json.Unmarshal(output, &rows); err != nil {
		return nil, fmt.Errorf("failed to unmarshal idempotency record: %w", err)
	}
	if len(rows) == 0 || rows[0].Payload == nil {
		return nil, nil
	}

	var rec idempotencyRecord
	if err := json.Unmarshal(*rows[0].Payload, &rec); err != nil {
		// Older records held the bare scan id rather than an object.
		var bare string
		if json.Unmarshal(*rows[0].Payload, &bare) == nil {
			return &idempotencyRecord{ScanId: bare}, nil
		}
		return nil, fmt.Errorf("failed to unmarshal idempotency payload: %w", err)
	}
	return &rec, nil
}
