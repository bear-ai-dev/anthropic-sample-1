package gelscan

import (
	"context"
	"encoding/json"
	"fmt"
	"ExampleCo-core/internal/v2/services/gel/gelclient"
)

type GetScanStatsRequest struct {
	EventId string
}

type GetScanStatsResponse struct {
	ScannedPeople     int     `json:"scannedPeople"`
	ExpectedAttendees int     `json:"expectedAttendees"`
	ScanRatePercent   float64 `json:"scanRatePercent"`
}

// GetScanStats calculates scanning statistics for an event
// scanned_people: unique attendees successfully scanned
// expected_attendees: valid tickets issued (sold + comp, excluding refunded/canceled)
// scan_rate_percent: scanned_people / expected_attendees * 100
func GetScanStats(ctx context.Context, req GetScanStatsRequest) (*GetScanStatsResponse, error) {
	if req.EventId == "" {
		return nil, fmt.Errorf("event id must be provided")
	}

	client := gelclient.GetClient()

	// Get unique scanned people: DISTINCT user_id from ReceiptItems that have scans
	scannedQuery := `
		WITH
			event := (SELECT Event FILTER .firestore_id = <str>$event_id AND NOT .deleted LIMIT 1)
		SELECT DISTINCT (
			(SELECT ReceiptItem
			 FILTER .event = event
			 AND NOT .pending
			 AND .refund_status != RefundStatus.refunded
			 AND NOT .abandoned
			 AND len(.scans) > 0
			).persona_event.persona[is User].firestore_id
		)
	`

	scannedParams := map[string]any{
		"event_id": req.EventId,
	}

	var scannedOutput []byte
	if err := client.QueryJSON(ctx, scannedQuery, &scannedOutput, scannedParams); err != nil {
		return nil, fmt.Errorf("failed to query scanned people: %w", err)
	}

	var scannedUserIds []string
	if err := json.Unmarshal(scannedOutput, &scannedUserIds); err != nil {
		return nil, fmt.Errorf("failed to unmarshal scanned user IDs: %w", err)
	}

	// Filter out empty strings
	scannedPeople := 0
	for _, userId := range scannedUserIds {
		if userId != "" {
			scannedPeople++
		}
	}

	// Get expected attendees: COUNT unique users with valid tickets
	// Query for unique users with valid tickets
	expectedQuery := `
		WITH
			event := (SELECT Event FILTER .firestore_id = <str>$event_id AND NOT .deleted LIMIT 1)
		SELECT DISTINCT (
			(SELECT ReceiptItem
			 FILTER .event = event
			 AND NOT .pending
			 AND .refund_status != RefundStatus.refunded
			 AND NOT .abandoned
			).persona_event.persona[is User].firestore_id
		)
	`

	/*
			{
			RESULT:
			{
		  "persona_event": {
		    "persona": {
		      "firestore_id": "sWekJH6JMiUSnWU7dB1wi6dYnFk2"
		    }
		  },

		    "persona_event": {
		    "persona": {
		      "firestore_id": "sWekJH6JMiUSnWdfdU7dB1wi6dYnFk2"
		    }
		  },
		}
	*/

	expectedParams := map[string]any{
		"event_id": req.EventId,
	}

	var expectedOutput []byte
	if err := client.QueryJSON(ctx, expectedQuery, &expectedOutput, expectedParams); err != nil {
		return nil, fmt.Errorf("failed to query expected attendees: %w", err)
	}

	var expectedUserIds []string
	if err := json.Unmarshal(expectedOutput, &expectedUserIds); err != nil {
		return nil, fmt.Errorf("failed to unmarshal expected user IDs: %w", err)
	}

	expectedAttendees := 0
	for _, userId := range expectedUserIds {
		if userId != "" {
			expectedAttendees++
		}
	}

	// Calculate scan rate
	scanRatePercent := 0.0
	if expectedAttendees > 0 {
		scanRatePercent = float64(scannedPeople) / float64(expectedAttendees) * 100.0
	}

	return &GetScanStatsResponse{
		ScannedPeople:     scannedPeople,
		ExpectedAttendees: expectedAttendees,
		ScanRatePercent:   scanRatePercent,
	}, nil
}
