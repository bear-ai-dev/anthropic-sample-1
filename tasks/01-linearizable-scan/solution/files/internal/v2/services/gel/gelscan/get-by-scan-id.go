package gelscan

import (
	"context"
	"encoding/json"
	"fmt"
	"ExampleCo-core/internal/v2/models"
	"ExampleCo-core/internal/v2/services/gel/gelclient"
	"time"
)

type GetByScanIdRequest struct {
	ScanId string `json:"scanId"`
}

type GetByScanIdResponse struct {
	Scan   models.Scan `json:"scan"`
	Exists bool        `json:"exists"`
}

func GetByScanId(ctx context.Context, req GetByScanIdRequest) (*GetByScanIdResponse, error) {
	var response GetByScanIdResponse
	if req.ScanId == "" {
		return nil, fmt.Errorf("scan id must be provided")
	}
	client := gelclient.GetClient()

	query := `
        SELECT Scan {
            scan_id,
            date_created,
            scan_type,
            scanner_user: { firestore_id },
            purchased_ticket_ids,
            firestore_id
        }
        FILTER .scan_id = <str>$scanId
        LIMIT 1
    `

	params := map[string]any{
		"scanId": req.ScanId,
	}

	var output []byte
	if err := client.QueryJSON(ctx, query, &output, params); err != nil {
		return nil, fmt.Errorf("failed to query scan from gel: %w", err)
	}

	type GelScan struct {
		ScanId      string    `json:"scan_id"`
		DateCreated time.Time `json:"date_created"`
		ScanType    string    `json:"scan_type"`
		ScannerUser struct {
			FirestoreId string `json:"firestore_id"`
		} `json:"scanner_user"`
		PurchasedTicketIds []string `json:"purchased_ticket_ids"`
		FirestoreId        string   `json:"firestore_id"`
	}

	var scans []GelScan
	if err := json.Unmarshal(output, &scans); err != nil {
		return nil, fmt.Errorf("failed to unmarshal gel scan: %w", err)
	}

	if len(scans) == 0 {
		return &response, nil
	}

	s := scans[0]
	scanType := models.ScanTypeManual
	if s.ScanType == "qr" {
		scanType = models.ScanTypeQR
	}

	response.Scan = models.Scan{
		Id:                 s.ScanId,
		DateCreated:        int(s.DateCreated.Unix()),
		Type:               scanType,
		ScannerUserId:      s.ScannerUser.FirestoreId,
		PurchasedTicketIds: s.PurchasedTicketIds,
	}
	response.Exists = true
	return &response, nil
}
