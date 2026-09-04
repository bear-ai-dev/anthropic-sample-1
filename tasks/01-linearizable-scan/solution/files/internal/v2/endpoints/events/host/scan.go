package host

import (
	"context"
	"fmt"
	"net/http"
	"ExampleCo-core/internal/v2/lib"
	"ExampleCo-core/internal/v2/lib/testcoord"
	"ExampleCo-core/internal/v2/models"
	"ExampleCo-core/internal/v2/services/ably"
	"ExampleCo-core/internal/v2/services/gel/gelaudit"
	"ExampleCo-core/internal/v2/services/gel/gelevent"
	"ExampleCo-core/internal/v2/services/gel/gelreceiptitem"
	"ExampleCo-core/internal/v2/services/gel/gelscan"
	"ExampleCo-core/internal/v2/services/gel/geluser"
	"ExampleCo-core/internal/v2/services/svpass"
	"ExampleCo-core/internal/v2/services/svtickets"
	"time"

	"github.com/pkg/errors"

	"golang.org/x/exp/slices"

	"github.com/google/uuid"
	"gopkg.in/validator.v2"
)

type ScanTicketRequest struct {
	// EventId being scanned for
	EventId uuid.UUID `json:"eventId"`

	// Either value of qr code or user id
	QrCode *string `json:"qrCode"`
	UserId *string `json:"userId"`

	// TicketIds
	// In the event of multiple tickets, identify which tickets are to be scanned
	TicketIds []string `json:"ticketIds"`

	// Client duration in milliseconds (for UX tracking)
	ClientDurationMs *int `json:"clientDurationMs"`
}

func (i *ScanTicketRequest) Validate() error {

	// Run Independent Validation
	if err := validator.Validate(i); err != nil {
		return err
	}

	if i.UserId == nil && i.QrCode == nil {
		return errors.New("one of userid and qr code must be provided")
	}

	if i.UserId != nil && i.QrCode != nil {
		return errors.New("both of userid and qr code cannot be provided")
	}

	return nil
}

type ScanTicketResponse struct {
	// UserId
	User *models.User `json:"user"`
	// Confirmed indicates if the request was confirmed, or further action has to be taken
	Confirmed bool `json:"confirmed"`
	// Status
	ScanId     string     `json:"scanId"`
	ScanValid  ScanValid  `json:"scanValid"`
	ScanStatus ScanStatus `json:"scanStatus"`
	// Tickets
	Tickets []models.ExtendedTicket `json:"tickets"`
}

type ScanTicketResponseIndividual struct {
	Mapping      models.UserTicketMapping `json:"mapping"`
	LastScanDate *int                     `json:"lastScanDate"`
	Scannable    bool                     `json:"scannable"`
	ScanStatus   ScanStatus               `json:"scanStatus"`
}

type ScanValid string

const (
	ScanValidSuccess ScanValid = "success"
	ScanValidExpired ScanValid = "expired"
	ScanValidInvalid ScanValid = "invalid"
)

type ScanStatus string

const (
	ScanStatusSuccess  ScanStatus = "success"
	ScanStatusPending  ScanStatus = "pending"
	ScanStatusDebounce ScanStatus = "debounce"
	ScanStatusRepeat   ScanStatus = "repeat"
	ScanStatusMultiple ScanStatus = "multiple"
)

// ScanTicket godoc
// @Summary      Scan a ticket
// @Tags         event-host
// @Accept       json
// @Produce      json
// @Security     BearerAuth
// @Param        eventId query string true "Event ID"
// @Param        qrCode query string false "QR Code"
// @Param        userId query string false "User ID"
// @Param        ticketIds query []string false "Ticket IDs"
// @Success      200 {object} ScanTicketResponse
// @Failure      400 {object} lib.APIErrorOutput
// @Router       /events/hosts/scan [get]
func ScanTicket(w http.ResponseWriter, r *http.Request) {

	var request ScanTicketRequest
	var response ScanTicketResponse
	response.Tickets = []models.ExtendedTicket{}

	start := time.Now()
	last := start
	requestId := uuid.New().String()
	scannerId := lib.ExtractUID(r)
	passCode := r.Header.Get("PASS_CODE")
	idempotencyKey := r.Header.Get("Idempotency-Key")
	eventIdStr := ""
	path := ""
	thresholdMs := int64(300)
	logStep := func(step string) {
		stepMs := time.Since(last).Milliseconds()
		totalMs := time.Since(start).Milliseconds()
		fmt.Println("[scan]",
			"req", requestId,
			"event", eventIdStr,
			"scanner", scannerId,
			"path", path,
			"step", step,
			"ms_total", totalMs,
			"ms_step", stepMs,
			"slow_step", stepMs > thresholdMs,
		)
		last = time.Now()
	}
	logErr := func(where string, err error) {
		fmt.Println("[scan:error]",
			"req", requestId,
			"event", eventIdStr,
			"scanner", scannerId,
			"path", path,
			"where", where,
			"err", err,
			"ms_total", time.Since(start).Milliseconds(),
		)
	}

	// Read and validate body
	if err := lib.ParseRequestBody(r, &request); err != nil {
		logErr("parse_request_body", err)
		lib.HandleAPIError(w, http.StatusBadRequest, lib.LogAndReturnErrorObject(err, "", request))
		return
	}
	if err := request.Validate(); err != nil {
		logErr("validate_request", err)
		lib.HandleAPIError(w, http.StatusBadRequest, lib.LogAndReturnErrorObject(err, "", request))
		return
	}
	if request.QrCode != nil {
		path = "qr"
	} else if request.UserId != nil {
		path = "userId"
	}
	logStep("validated_input")

	// Load event (timeout)
	{
		ctx, cancel := context.WithTimeout(r.Context(), 3*time.Second)
		defer cancel()
		event, err := gelevent.GetEvent(ctx, gelevent.GetEventRequest{EventId: request.EventId.String()})
		if err != nil {
			logErr("get_event", err)
			lib.HandleAPIError(w, http.StatusInternalServerError, lib.LogAndReturnErrorObject(err, "", request))
			return
		}
		if !event.Exists {
			logErr("event_not_found", errors.New(models.ErrorCodeResourceNotFound))
			lib.HandleAPIError(w, http.StatusNotFound, lib.LogAndReturnErrorObject(errors.New(models.ErrorCodeResourceNotFound), "", request))
			return
		}
		eventIdStr = event.Event.Id
	}
	logStep("loaded_event")

	// Make sure host can access scanning
	{
		var hosting *gelevent.CheckEventHostingPrivilegeResponse
		var privilege *gelevent.GetUserEventPrivilegeResponse

		// Only check privileges if user is logged in
		if scannerId != "" {
			ctx, cancel := context.WithTimeout(r.Context(), 5*time.Second)
			defer cancel()
			var err error
			hosting, err = gelevent.CheckEventHostingPrivilege(ctx, gelevent.CheckEventHostingPrivilegeRequest{
				EventId: eventIdStr,
				UserId:  scannerId,
			})
			if err != nil {
				logErr("check_hosting_priv", err)
				lib.HandleAPIError(w, http.StatusBadRequest, lib.LogAndReturnErrorObject(err, "", request))
				return
			}
			logStep("checked_hosting_priv")

			ctx2, cancel2 := context.WithTimeout(r.Context(), 5*time.Second)
			defer cancel2()
			var err2 error
			privilege, err2 = gelevent.GetUserEventPrivilege(ctx2, gelevent.GetUserEventPrivilegeRequest{
				EventId: eventIdStr,
				UserId:  scannerId,
			})
			if err2 != nil {
				logErr("get_user_priv", err2)
				lib.HandleAPIError(w, http.StatusBadRequest, lib.LogAndReturnErrorObject(err2, "", request))
				return
			}
			logStep("loaded_user_priv")
		}

		// Check if user has host/bouncer privileges (bypasses scan code check)
		hasPrivilege := (hosting != nil && hosting.IsHost) || (privilege != nil && privilege.Privilege == models.EventPrivilegeBouncer)

		if !hasPrivilege {
			// User doesn't have host/bouncer privileges, check scan code header
			scanCodeHeader := passCode
			if scanCodeHeader == "" {
				logErr("missing_scan_code", errors.New("scan code required"))
				lib.HandleAPIError(w, http.StatusUnauthorized, &models.ErrorObject{
					Message: "unauthorized",
					Display: "Scan code required",
				})
				return
			}

			// Verify scan code matches event's scan code
			ctx3, cancel3 := context.WithTimeout(r.Context(), 3*time.Second)
			defer cancel3()
			scanCodeResp, scanCodeErr := gelevent.GetScanCode(ctx3, gelevent.GetScanCodeRequest{
				EventId: eventIdStr,
			})
			if scanCodeErr != nil || !scanCodeResp.Exists {
				logErr("get_scan_code", scanCodeErr)
				lib.HandleAPIError(w, http.StatusInternalServerError, lib.LogAndReturnErrorObject(errors.New("failed to verify scan code"), "", request))
				return
			}

			if scanCodeHeader != scanCodeResp.ScanCode {
				logErr("invalid_scan_code", errors.New("scan code mismatch"))
				lib.HandleAPIError(w, http.StatusUnauthorized, &models.ErrorObject{
					Message: "unauthorized",
					Display: "Invalid scan code",
				})
				return
			}
			logStep("verified_scan_code")
		}
	}

	// Get scan data
	if request.QrCode != nil {
		ctx, cancel := context.WithTimeout(r.Context(), 5*time.Second)
		defer cancel()
		userId, outOfDate, userIdErr := svpass.DecryptWithPrivateKey(ctx, svpass.DecryptRequest{
			Cipher: *request.QrCode,
		})
		if userIdErr != nil {
			response.ScanValid = ScanValidInvalid
			logErr("decrypt_qr", userIdErr)
			lib.HandleAPISuccess(w, http.StatusOK, response)
			return
		}
		if outOfDate {
			response.ScanValid = ScanValidExpired
			logStep("qr_out_of_date")
			lib.HandleAPISuccess(w, http.StatusOK, response)
			return
		}
		response.ScanValid = ScanValidSuccess
		request.UserId = &userId
		logStep("decrypted_qr")
	} else {
		response.ScanValid = ScanValidSuccess
	}

	// Check if user exists
	var targetUserId string
	if request.UserId != nil {
		targetUserId = *request.UserId
	}
	{
		ctx, cancel := context.WithTimeout(r.Context(), 5*time.Second)
		defer cancel()
		user, err := geluser.GetUserById(ctx, geluser.GetUserByIdRequest{UserId: targetUserId})
		if err != nil || !user.Exists {
			if err == nil {
				err = errors.New("bad user")
			}
			logErr("get_user", err)
			lib.HandleAPIError(w, http.StatusUnauthorized, lib.LogAndReturnErrorObject(err, "", request))
			return
		}
		response.User = user.User
	}
	logStep("loaded_user")

	// Get user ticket mapping groups
	var ticketsFound int
	{
		ctx, cancel := context.WithTimeout(r.Context(), 3*time.Second)
		defer cancel()
		ticketsResp, ticketErr := gelevent.GetUserTicketMappings(ctx, gelevent.GetUserTicketMappingsRequest{
			EventId: eventIdStr,
			UserId:  targetUserId,
		})
		if ticketErr != nil {
			logErr("get_user_ticket_mappings", ticketErr)
			lib.HandleAPIError(w, http.StatusBadRequest, lib.LogAndReturnErrorObject(ticketErr, "", request))
			return
		}
		logStep("loaded_ticket_mappings")

		ticketsFound = len(ticketsResp.Tickets)

		if len(ticketsResp.Tickets) == 0 {
			logErr("no_tickets_found", errors.New("no tickets found"))
			lib.HandleAPIError(w, http.StatusNoContent, lib.LogAndReturnErrorObject(errors.New("no tickets found"), "", request))
			return

		} else if len(ticketsResp.Tickets) == 1 {

			scanRes, scanErr := scanSingleItem(r.Context(), scanSingleItemRequest{
				ItemId:           ticketsResp.Tickets[0].Ticket.Id,
				ScannerId:        scannerId,
				ClientDurationMs: request.ClientDurationMs,
				EventId:          eventIdStr,
				ScanCode:         passCode,
				IdempotencyKey:   idempotencyKey,
			})
			if scanErr != nil {
				logErr("scan_single", scanErr)
				lib.HandleAPIError(w, http.StatusBadRequest, lib.LogAndReturnErrorObject(scanErr, "", request))
				return
			}
			logStep("single_scan_processed")

			ticket, err := svtickets.LoadExtendedTicket(r.Context(), svtickets.LoadExtendedTicketRequest{Utm: ticketsResp.Tickets[0]})
			if err != nil {
				logErr("load_extended_ticket_single", err)
				lib.HandleAPIError(w, http.StatusBadRequest, lib.LogAndReturnErrorObject(err, "", request))
				return
			}
			logStep("loaded_extended_ticket_single")

			response.Tickets = []models.ExtendedTicket{ticket}
			response.Confirmed = true
			response.ScanStatus = scanRes.ScanCode
			response.ScanId = scanRes.ScanId

			gelaudit.LogEventAction(r.Context(), scannerId, eventIdStr, models.ActionHostGuestListScan, r, map[string]interface{}{
				"scan_id":         response.ScanId,
				"target_user_id":  targetUserId,
				"tickets_scanned": 1,
				"scan_status":     string(response.ScanStatus),
				"message":         fmt.Sprintf("Scanned 1 ticket for user %s at event %s at %s", targetUserId, eventIdStr, time.Now().Format("2006-01-02 15:04:05 MST")),
			})

			// Send WebSocket notification for scan status update
			go SendScanStatusWebSocket(r.Context(), eventIdStr)

			fmt.Println("[scan] done",
				"req", requestId,
				"event", eventIdStr,
				"scanner", scannerId,
				"path", path,
				"tickets_found", ticketsFound,
				"selected", 1,
				"status", response.ScanStatus,
				"ms_total", time.Since(start).Milliseconds(),
			)
			lib.HandleAPISuccess(w, http.StatusOK, response)
			return

		} else if len(request.TicketIds) == 0 {

			for _, t := range ticketsResp.Tickets {
				ticket, err := svtickets.LoadExtendedTicket(r.Context(), svtickets.LoadExtendedTicketRequest{Utm: t})
				if err != nil {
					logErr("load_extended_ticket_multi_preview", err)
					lib.HandleAPIError(w, http.StatusBadRequest, lib.LogAndReturnErrorObject(err, "", request))
					return
				}
				response.Tickets = append(response.Tickets, ticket)
			}
			logStep("loaded_extended_tickets_multi_preview")
			response.Confirmed = false
			response.ScanStatus = ScanStatusMultiple
			fmt.Println("[scan] done",
				"req", requestId,
				"event", eventIdStr,
				"scanner", scannerId,
				"path", path,
				"tickets_found", ticketsFound,
				"selected", 0,
				"status", response.ScanStatus,
				"ms_total", time.Since(start).Milliseconds(),
			)
			lib.HandleAPISuccess(w, http.StatusMultiStatus, response)
			return

		} else {

			selected := 0
			itemIds := []string{}
			for _, t := range ticketsResp.Tickets {
				ticket, err := svtickets.LoadExtendedTicket(r.Context(), svtickets.LoadExtendedTicketRequest{Utm: t})
				if err != nil {
					logErr("load_extended_ticket_multi_selected", err)
					lib.HandleAPIError(w, http.StatusBadRequest, lib.LogAndReturnErrorObject(err, "", request))
					return
				}
				response.Tickets = append(response.Tickets, ticket)
				if slices.Contains(request.TicketIds, t.Ticket.Id) {
					itemIds = append(itemIds, t.Ticket.Id)
					selected++
				}
			}
			logStep("loaded_extended_tickets_multi_selected")

			// Scan multiple items
			scanRes, scanErr := scanMultipleItem(r.Context(), scanMultipleItemRequest{
				ItemIds:          itemIds,
				ScannerId:        scannerId,
				ClientDurationMs: request.ClientDurationMs,
				EventId:          eventIdStr,
				ScanCode:         passCode,
				IdempotencyKey:   idempotencyKey,
			})
			if scanErr != nil {
				logErr("scan_multi", scanErr)
				lib.HandleAPIError(w, http.StatusBadRequest, lib.LogAndReturnErrorObject(scanErr, "", request))
				return
			}
			logStep("multi_scan_processed")

			response.ScanId = scanRes.ScanId
			response.Confirmed = true
			response.ScanStatus = scanRes.ScanCode

			gelaudit.LogEventAction(r.Context(), scannerId, eventIdStr, models.ActionHostGuestListScan, r, map[string]interface{}{
				"scan_id":         response.ScanId,
				"target_user_id":  targetUserId,
				"tickets_scanned": selected,
				"scan_status":     string(response.ScanStatus),
				"message":         fmt.Sprintf("Scanned %d tickets for user %s at event %s at %s", selected, targetUserId, eventIdStr, time.Now().Format("2006-01-02 15:04:05 MST")),
			})

			// Send WebSocket notification for scan status update
			go SendScanStatusWebSocket(r.Context(), eventIdStr)

			fmt.Println("[scan] done",
				"req", requestId,
				"event", eventIdStr,
				"scanner", scannerId,
				"path", path,
				"tickets_found", ticketsFound,
				"selected", selected,
				"status", response.ScanStatus,
				"ms_total", time.Since(start).Milliseconds(),
			)
			lib.HandleAPISuccess(w, http.StatusOK, response)
			return
		}
	}
}

// SendScanStatusWebSocket sends a WebSocket notification with updated scan status
func SendScanStatusWebSocket(ctx context.Context, eventId string) {
	// Create a new context with timeout for the background operation
	bgCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	// Get current scan status
	statusResp, err := gelscan.GetTicketScanStatus(bgCtx, gelscan.GetTicketScanStatusRequest{
		EventId: eventId,
	})
	if err != nil {
		fmt.Println("[scan:websocket] failed to get scan status:", err)
		return
	}

	// Send WebSocket message
	_, err = ably.SendObjectAblyMessage(ably.SendObjectAblyMessageRequest{
		Type:   models.HostTicketScan,
		Action: models.UpdateAblyAction,
		Id:     eventId,
		ScanStatusData: &models.ScanStatusSocketData{
			NumScanned:   statusResp.NumScanned,
			TotalTickets: statusResp.TotalTickets,
		},
	})
	if err != nil {
		fmt.Println("[scan:websocket] failed to send ably message:", err)
		return
	}

	fmt.Println("[scan:websocket] sent scan status update for event", eventId, "numScanned", statusResp.NumScanned, "totalTickets", statusResp.TotalTickets)
}

type scanSingleItemRequest struct {
	ItemId           string `json:"itemId"`
	ScannerId        string `json:"scannerId"`
	ClientDurationMs *int   `json:"clientDurationMs"`

	// Carried down to the write so the decision is made against the state that
	// is current when the row changes, not the state seen on arrival.
	EventId        string `json:"eventId"`
	ScanCode       string `json:"scanCode"`
	IdempotencyKey string `json:"idempotencyKey"`
}

type scanSingleItemResponse struct {
	ScanCode     ScanStatus `json:"scanCode"`
	LastScanDate *int       `json:"lastScanDate"`
	ScanId       string     `json:"scanId"`
}

func scanSingleItem(ctx context.Context, request scanSingleItemRequest) (*scanSingleItemResponse, error) {

	stepStart := time.Now()
	last := stepStart
	dbg := func(s string) {
		fmt.Println("[scanSingle]", s, "item", request.ItemId, "scanner", request.ScannerId, "ms_total", time.Since(stepStart).Milliseconds(), "ms_step", time.Since(last).Milliseconds())
		last = time.Now()
	}
	// Get receipt item
	receiptItem, err := gelreceiptitem.GetByTicketId(ctx, gelreceiptitem.GetByTicketIdRequest{TicketId: request.ItemId})
	if err != nil {
		return nil, err
	}
	if !receiptItem.Exists {
		return nil, errors.New("receipt item not found")
	}
	dbg("loaded_receipt_item")

	if receiptItem.ReceiptItem.Scans == nil {
		receiptItem.ReceiptItem.Scans = []string{}
	}

	// Harness rendezvous; inert unless a test has armed it. Leave in place.
	testcoord.Checkpoint(ctx, testcoord.PreAdmit)

	res, err := admitSingleItem(ctx, receiptItem.ReceiptItem, request)

	// The other side of the write, before anything is reported back. Also
	// inert unless armed, and also test scaffolding: leave it in place.
	testcoord.Checkpoint(ctx, testcoord.PostAdmit)

	return res, err
}

// admitSingleItem decides the outcome for a single receipt item and persists
// it.
//
// The item passed in came from a read that is already stale by the time we get
// here, so it is used only to shape the reply. Whether the ticket is actually
// admitted is decided by the store, in the same statement that writes.
func admitSingleItem(ctx context.Context, item models.ReceiptItem, request scanSingleItemRequest) (*scanSingleItemResponse, error) {

	var response scanSingleItemResponse

	res, err := gelscan.Admit(ctx, gelscan.AdmitRequest{
		EventId:          request.EventId,
		ItemIds:          []string{item.Id},
		ScannerUserId:    request.ScannerId,
		ScanCode:         request.ScanCode,
		IdempotencyKey:   request.IdempotencyKey,
		ScanId:           uuid.New().String(),
		Now:              time.Now(),
		ClientDurationMs: request.ClientDurationMs,
	})
	if err != nil {
		return nil, err
	}

	switch res.Outcome {
	case gelscan.AdmitOutcomeAdmitted, gelscan.AdmitOutcomeReplayed:
		response.ScanCode = ScanStatusSuccess
		response.ScanId = res.ScanId
	case gelscan.AdmitOutcomePending:
		response.ScanCode = ScanStatusPending
	case gelscan.AdmitOutcomeAlreadyScanned:
		code, lastScanDate, classifyErr := classifyExistingScan(ctx, item.Id)
		if classifyErr != nil {
			return nil, classifyErr
		}
		response.ScanCode = code
		response.LastScanDate = lastScanDate
	case gelscan.AdmitOutcomeUnauthorized:
		return nil, errors.New("not authorized to scan at admission time")
	case gelscan.AdmitOutcomeNotFound:
		return nil, errors.New("receipt item not found")
	case gelscan.AdmitOutcomeKeyConflict:
		return nil, errors.New("idempotency key already belongs to a different scan")
	default:
		return nil, errors.Errorf("unexpected admission outcome %q", res.Outcome)
	}

	return &response, nil
}

// classifyExistingScan distinguishes a scanner double-tapping the same ticket
// from a genuine second presentation of it, by looking at when the ticket was
// last admitted. Neither case writes anything.
func classifyExistingScan(ctx context.Context, itemId string) (ScanStatus, *int, error) {
	current, err := gelreceiptitem.GetByTicketId(ctx, gelreceiptitem.GetByTicketIdRequest{TicketId: itemId})
	if err != nil {
		return "", nil, err
	}
	if !current.Exists || len(current.ReceiptItem.Scans) == 0 {
		return ScanStatusRepeat, nil, nil
	}

	scans := current.ReceiptItem.Scans
	lastScan, scanErr := gelscan.GetByScanId(ctx, gelscan.GetByScanIdRequest{ScanId: scans[len(scans)-1]})
	if scanErr != nil {
		return "", nil, scanErr
	}
	if !lastScan.Exists {
		return ScanStatusRepeat, nil, nil
	}

	if lastScan.Scan.DateCreated > int(time.Now().Add(-scanDebounceWindow).Unix()) {
		return ScanStatusDebounce, nil, nil
	}
	lastScanDate := lastScan.Scan.DateCreated
	return ScanStatusRepeat, &lastScanDate, nil
}

// scanDebounceWindow is how long after admitting a ticket a second read of the
// same ticket is treated as the scanner double-tapping rather than as a fresh
// presentation.
const scanDebounceWindow = 500 * time.Millisecond

type scanMultipleItemRequest struct {
	ItemIds          []string `json:"itemId"`
	ScannerId        string   `json:"scannerId"`
	ClientDurationMs *int     `json:"clientDurationMs"`

	EventId        string `json:"eventId"`
	ScanCode       string `json:"scanCode"`
	IdempotencyKey string `json:"idempotencyKey"`
}

type scanMultipleItemResponse struct {
	ScanCode     ScanStatus `json:"scanCode"`
	LastScanDate *int       `json:"lastScanDate"`
	ScanId       string     `json:"scanId"`
}

func scanMultipleItem(ctx context.Context, request scanMultipleItemRequest) (*scanMultipleItemResponse, error) {

	stepStart := time.Now()
	last := stepStart
	dbg := func(s string) {
		fmt.Println("[scanMultiple]", s, "items", len(request.ItemIds), "scanner", request.ScannerId, "ms_total", time.Since(stepStart).Milliseconds(), "ms_step", time.Since(last).Milliseconds())
		last = time.Now()
	}
	receiptItems := []models.ReceiptItem{}

	// Get receipt items
	for _, item := range request.ItemIds {
		receiptItem, err := gelreceiptitem.GetByTicketId(ctx, gelreceiptitem.GetByTicketIdRequest{TicketId: item})
		if err != nil {
			return nil, err
		}
		if !receiptItem.Exists {
			return nil, errors.New("receipt item not found")
		}

		if receiptItem.ReceiptItem.Scans == nil {
			receiptItem.ReceiptItem.Scans = []string{}
		}
		receiptItems = append(receiptItems, receiptItem.ReceiptItem)
	}
	dbg("loaded_receipt_items")

	// Harness rendezvous; inert unless a test has armed it. Leave in place.
	testcoord.Checkpoint(ctx, testcoord.PreAdmit)

	res, err := admitMultipleItems(ctx, receiptItems, request)

	// The other side of the write, before anything is reported back. Also
	// inert unless armed, and also test scaffolding: leave it in place.
	testcoord.Checkpoint(ctx, testcoord.PostAdmit)

	return res, err
}

// admitMultipleItems decides the outcome for a batch of receipt items and
// persists it.
//
// A batch is all or nothing. If any member is pending, already scanned, or
// taken by a competing batch that overlaps this one, the whole batch is
// refused and no member is touched.
func admitMultipleItems(ctx context.Context, items []models.ReceiptItem, request scanMultipleItemRequest) (*scanMultipleItemResponse, error) {

	var response scanMultipleItemResponse

	itemIds := make([]string, 0, len(items))
	for _, item := range items {
		itemIds = append(itemIds, item.Id)
	}

	res, err := gelscan.Admit(ctx, gelscan.AdmitRequest{
		EventId:          request.EventId,
		ItemIds:          itemIds,
		ScannerUserId:    request.ScannerId,
		ScanCode:         request.ScanCode,
		IdempotencyKey:   request.IdempotencyKey,
		ScanId:           uuid.New().String(),
		Now:              time.Now(),
		ClientDurationMs: request.ClientDurationMs,
	})
	if err != nil {
		return nil, err
	}

	switch res.Outcome {
	case gelscan.AdmitOutcomeAdmitted, gelscan.AdmitOutcomeReplayed:
		response.ScanCode = ScanStatusSuccess
		response.ScanId = res.ScanId
	case gelscan.AdmitOutcomePending:
		return nil, errors.New("attempted to scan pending ticket")
	case gelscan.AdmitOutcomeAlreadyScanned:
		return nil, errors.New("attempted to scan previously scanned ticket")
	case gelscan.AdmitOutcomeUnauthorized:
		return nil, errors.New("not authorized to scan at admission time")
	case gelscan.AdmitOutcomeNotFound:
		return nil, errors.New("receipt item not found")
	case gelscan.AdmitOutcomeKeyConflict:
		return nil, errors.New("idempotency key already belongs to a different scan")
	default:
		return nil, errors.Errorf("unexpected admission outcome %q", res.Outcome)
	}

	return &response, nil
}
