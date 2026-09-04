package gelscan

import (
	"context"
	"encoding/json"
	"fmt"
	"ExampleCo-core/internal/v2/services/gel/gelclient"
)

type GetTicketScanStatusRequest struct {
	EventId string
}

type GetTicketScanStatusResponse struct {
	NumScanned   int `json:"numScanned"`
	TotalTickets int `json:"totalTickets"`
}

// GetTicketScanStatus returns the number of scanned tickets and total tickets for an event
// numScanned: number of receipt items (tickets) that have been scanned (len(scans) > 0)
// totalTickets: total valid receipt items (not pending, not refunded, not abandoned)
func GetTicketScanStatus(ctx context.Context, req GetTicketScanStatusRequest) (*GetTicketScanStatusResponse, error) {
	if req.EventId == "" {
		return nil, fmt.Errorf("event id must be provided")
	}

	client := gelclient.GetClient()

	// Query for scanned tickets count and total tickets count
	query := `
		WITH
			event := (SELECT Event FILTER .firestore_id = <str>$event_id AND NOT .deleted LIMIT 1),
			valid_tickets := (SELECT ReceiptItem
				FILTER .event = event
				AND NOT .pending
				AND .refund_status != RefundStatus.refunded
				AND NOT .abandoned
			)
		SELECT {
			num_scanned := count((SELECT valid_tickets FILTER len(.scans) > 0)),
			total_tickets := count(valid_tickets)
		}
	`

	params := map[string]any{
		"event_id": req.EventId,
	}

	var output []byte
	if err := client.QueryJSON(ctx, query, &output, params); err != nil {
		return nil, fmt.Errorf("failed to query ticket scan status: %w", err)
	}

	var result []struct {
		NumScanned   int `json:"num_scanned"`
		TotalTickets int `json:"total_tickets"`
	}
	if err := json.Unmarshal(output, &result); err != nil {
		return nil, fmt.Errorf("failed to unmarshal ticket scan status: %w", err)
	}

	if len(result) == 0 {
		return &GetTicketScanStatusResponse{
			NumScanned:   0,
			TotalTickets: 0,
		}, nil
	}

	return &GetTicketScanStatusResponse{
		NumScanned:   result[0].NumScanned,
		TotalTickets: result[0].TotalTickets,
	}, nil
}
