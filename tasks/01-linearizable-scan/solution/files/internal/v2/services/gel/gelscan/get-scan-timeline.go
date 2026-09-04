package gelscan

import (
	"context"
	"encoding/json"
	"fmt"
	"ExampleCo-core/internal/v2/models"
	"ExampleCo-core/internal/v2/services/gel/gelclient"
	"ExampleCo-core/internal/v2/services/gel/gelevent"
	"time"
)

type GetScanTimelineRequest struct {
	EventId string
}

type GetScanTimelineResponse struct {
	Timeline          []models.ScanAnalyticsBucket `json:"timeline"`
	AverageScanTimeMs *int                         `json:"averageScanTimeMs"`
}

// GetScanTimeline retrieves scan timeline analytics with 15-minute buckets
// Returns unique attendees per bucket, cumulative totals, and average scan time
func GetScanTimeline(ctx context.Context, req GetScanTimelineRequest) (*GetScanTimelineResponse, error) {
	if req.EventId == "" {
		return nil, fmt.Errorf("event id must be provided")
	}

	client := gelclient.GetClient()

	// First, get event to determine timezone and time range
	eventResp, err := gelevent.GetEvent(ctx, gelevent.GetEventRequest{EventId: req.EventId})
	if err != nil {
		return nil, fmt.Errorf("failed to get event: %w", err)
	}
	if !eventResp.Exists {
		return nil, fmt.Errorf("event not found")
	}

	event := eventResp.Event
	eventStartTime := time.Unix(int64(event.DateStart), 0)
	eventEndTime := time.Unix(int64(event.DateEnd), 0)

	// Create 15-minute buckets from event start to end
	buckets := createFixedIntervalBuckets(eventStartTime, eventEndTime, 15*time.Minute)

	// Query ReceiptItems with scans to get scan and user information in one go
	// This is more efficient than querying scans and then joining
	query := `
		WITH
			event := (SELECT Event FILTER .firestore_id = <str>$event_id AND NOT .deleted LIMIT 1)
		SELECT ReceiptItem {
			scans,
			persona_event: {
				persona: {
					[is User].firestore_id
				}
			}
		}
		FILTER .event = event
		AND len(.scans) > 0
	`

	params := map[string]any{
		"event_id": req.EventId,
	}

	var output []byte
	if err := client.QueryJSON(ctx, query, &output, params); err != nil {
		return nil, fmt.Errorf("failed to query receipt items: %w", err)
	}

	type GelReceiptItem struct {
		Scans        []string `json:"scans"`
		PersonaEvent struct {
			Persona struct {
				FirestoreId *string `json:"firestore_id"`
			} `json:"persona"`
		} `json:"persona_event"`
	}

	var receiptItems []GelReceiptItem
	if err := json.Unmarshal(output, &receiptItems); err != nil {
		return nil, fmt.Errorf("failed to unmarshal receipt items: %w", err)
	}

	// Collect all scan IDs
	scanIds := make(map[string]bool)
	for _, ri := range receiptItems {
		for _, scanId := range ri.Scans {
			scanIds[scanId] = true
		}
	}

	// Query all scans at once
	scanIdsList := make([]string, 0, len(scanIds))
	for scanId := range scanIds {
		scanIdsList = append(scanIdsList, scanId)
	}

	if len(scanIdsList) == 0 {
		// No scans, return empty timeline
		timeline := make([]models.ScanAnalyticsBucket, len(buckets))
		for i, bucket := range buckets {
			timeline[i] = models.ScanAnalyticsBucket{
				StartTime:               int(bucket.Start.Unix()),
				EndTime:                 int(bucket.End.Unix()),
				Midpoint:                int(bucket.Midpoint.Unix()),
				PeopleScannedBucket:     0,
				PeopleScannedCumulative: 0,
			}
		}
		return &GetScanTimelineResponse{
			Timeline:          timeline,
			AverageScanTimeMs: nil,
		}, nil
	}

	scanQuery := `
		SELECT Scan {
			scan_id,
			date_created,
			client_duration_ms
		}
		FILTER .scan_id IN array_unpack(<array<str>>$scan_ids)
		ORDER BY .date_created ASC
	`

	scanParams := map[string]any{
		"scan_ids": scanIdsList,
	}

	var scanOutput []byte
	if err := client.QueryJSON(ctx, scanQuery, &scanOutput, scanParams); err != nil {
		return nil, fmt.Errorf("failed to query scans: %w", err)
	}

	type GelScan struct {
		ScanId           string    `json:"scan_id"`
		DateCreated      time.Time `json:"date_created"`
		ClientDurationMs *int32    `json:"client_duration_ms"`
	}

	var scans []GelScan
	if err := json.Unmarshal(scanOutput, &scans); err != nil {
		return nil, fmt.Errorf("failed to unmarshal scans: %w", err)
	}

	// Create map of scan ID -> scan data
	scanMap := make(map[string]GelScan)
	for _, scan := range scans {
		scanMap[scan.ScanId] = scan
	}

	// Create map of scan ID -> user IDs (from ReceiptItems)
	scanToUsers := make(map[string]map[string]bool)
	for _, ri := range receiptItems {
		userId := ""
		if ri.PersonaEvent.Persona.FirestoreId != nil {
			userId = *ri.PersonaEvent.Persona.FirestoreId
		}
		if userId == "" {
			continue
		}

		for _, scanId := range ri.Scans {
			if _, ok := scanMap[scanId]; ok {
				// Only process scans that exist
				if scanToUsers[scanId] == nil {
					scanToUsers[scanId] = make(map[string]bool)
				}
				scanToUsers[scanId][userId] = true
			}
		}
	}

	// Process scans and bucket by time
	bucketData := make(map[int]map[string]bool) // bucket index -> set of user IDs
	var totalDurationMs int64
	var durationCount int

	for _, scan := range scans {
		scanTimeLocal := scan.DateCreated

		// Find which bucket this scan belongs to
		bucketIdx := -1
		for i, bucket := range buckets {
			if !scanTimeLocal.Before(bucket.Start) && (scanTimeLocal.Before(bucket.End) || scanTimeLocal.Equal(bucket.End)) {
				bucketIdx = i
				break
			}
		}

		// Skip if scan is outside event time range
		if bucketIdx == -1 {
			continue
		}

		// Get unique users for this scan
		if users, ok := scanToUsers[scan.ScanId]; ok {
			// Initialize bucket if needed
			if bucketData[bucketIdx] == nil {
				bucketData[bucketIdx] = make(map[string]bool)
			}
			// Add unique users to this bucket
			for userId := range users {
				if userId != "" {
					bucketData[bucketIdx][userId] = true
				}
			}
		}

		// Track duration for average calculation
		if scan.ClientDurationMs != nil {
			totalDurationMs += int64(*scan.ClientDurationMs)
			durationCount++
		}
	}

	// Build response buckets
	timeline := make([]models.ScanAnalyticsBucket, len(buckets))
	cumulativeCount := 0

	for i, bucket := range buckets {
		uniqueUsers := 0
		if userSet, ok := bucketData[i]; ok {
			uniqueUsers = len(userSet)
		}
		cumulativeCount += uniqueUsers

		timeline[i] = models.ScanAnalyticsBucket{
			StartTime:               int(bucket.Start.Unix()),
			EndTime:                 int(bucket.End.Unix()),
			Midpoint:                int(bucket.Midpoint.Unix()),
			PeopleScannedBucket:     uniqueUsers,
			PeopleScannedCumulative: cumulativeCount,
		}
	}

	// Calculate average scan time
	var avgScanTimeMs *int
	if durationCount > 0 {
		avg := int(totalDurationMs / int64(durationCount))
		avgScanTimeMs = &avg
	}

	return &GetScanTimelineResponse{
		Timeline:          timeline,
		AverageScanTimeMs: avgScanTimeMs,
	}, nil
}

// createFixedIntervalBuckets creates time buckets with fixed intervals (e.g., 15 minutes)
func createFixedIntervalBuckets(start, end time.Time, interval time.Duration) []timeBucket {
	if end.Before(start) {
		return []timeBucket{}
	}

	var buckets []timeBucket
	current := start

	for current.Before(end) {
		bucketEnd := current.Add(interval)
		if bucketEnd.After(end) {
			bucketEnd = end
		}

		midpoint := current.Add(bucketEnd.Sub(current) / 2)

		buckets = append(buckets, timeBucket{
			Start:    current,
			End:      bucketEnd,
			Midpoint: midpoint,
		})

		current = bucketEnd
	}

	return buckets
}

type timeBucket struct {
	Start    time.Time
	End      time.Time
	Midpoint time.Time
}
