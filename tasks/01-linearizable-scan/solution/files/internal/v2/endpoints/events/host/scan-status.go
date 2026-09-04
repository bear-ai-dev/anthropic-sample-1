package host

import (
	"context"
	"errors"
	"net/http"
	"ExampleCo-core/internal/v2/lib"
	"ExampleCo-core/internal/v2/models"
	"ExampleCo-core/internal/v2/services/gel/gelevent"
	"ExampleCo-core/internal/v2/services/gel/gelscan"
	"time"

	"github.com/google/uuid"
	"gopkg.in/validator.v2"
)

type GetScanStatusRequest struct {
	EventId uuid.UUID `json:"eventId" validate:"nonzero" query:"eventId"`
}

func (r *GetScanStatusRequest) Validate() error {
	if err := validator.Validate(r); err != nil {
		return err
	}
	return nil
}

type GetScanStatusResponse struct {
	NumScanned   int `json:"numScanned"`
	TotalTickets int `json:"totalTickets"`
}

// GetScanStatus godoc
// @Summary      Get scan status for an event
// @Description  Returns the number of scanned tickets and total tickets for an event
// @Tags         event-host
// @Accept       json
// @Produce      json
// @Security     BearerAuth
// @Param        eventId query string true "Event ID"
// @Param        PASS_CODE header string false "Scan code for non-host/bouncer users"
// @Success      200 {object} GetScanStatusResponse
// @Failure      400 {object} lib.APIErrorOutput
// @Failure      401 {object} lib.APIErrorOutput
// @Failure      404 {object} lib.APIErrorOutput
// @Router       /events/hosts/scanstatus [get]
func GetScanStatus(w http.ResponseWriter, r *http.Request) {
	var request GetScanStatusRequest
	uid := lib.ExtractUID(r)

	// Parse and validate request
	if err := lib.ParseRequestQueryParams(r, &request); err != nil {
		lib.HandleAPIError(w, http.StatusBadRequest, lib.LogAndReturnErrorObject(err, uid, request))
		return
	}
	if err := request.Validate(); err != nil {
		lib.HandleAPIError(w, http.StatusBadRequest, lib.LogAndReturnErrorObject(err, uid, request))
		return
	}

	eventIdStr := request.EventId.String()

	// Get event to verify it exists
	ctx, cancel := context.WithTimeout(r.Context(), 3*time.Second)
	defer cancel()
	event, err := gelevent.GetEvent(ctx, gelevent.GetEventRequest{EventId: eventIdStr})
	if err != nil {
		lib.HandleAPIError(w, http.StatusInternalServerError, lib.LogAndReturnErrorObject(err, uid, request))
		return
	}
	if !event.Exists {
		lib.HandleAPIError(w, http.StatusNotFound, lib.LogAndReturnErrorObject(errors.New(models.ErrorCodeResourceNotFound), "", request))
		return
	}

	// Check if userId has sufficient privilege
	var hosting *gelevent.CheckEventHostingPrivilegeResponse
	var privilege *gelevent.GetUserEventPrivilegeResponse

	// Only check privileges if the user is logged in
	if uid != "" {
		ctx2, cancel2 := context.WithTimeout(r.Context(), 5*time.Second)
		defer cancel2()
		var hostingErr error
		hosting, hostingErr = gelevent.CheckEventHostingPrivilege(ctx2, gelevent.CheckEventHostingPrivilegeRequest{
			EventId: eventIdStr,
			UserId:  uid,
		})
		if hostingErr != nil {
			lib.HandleAPIError(w, http.StatusBadRequest, lib.LogAndReturnErrorObject(hostingErr, uid, request))
			return
		}

		ctx3, cancel3 := context.WithTimeout(r.Context(), 5*time.Second)
		defer cancel3()
		var privErr error
		privilege, privErr = gelevent.GetUserEventPrivilege(ctx3, gelevent.GetUserEventPrivilegeRequest{
			EventId: eventIdStr,
			UserId:  uid,
		})
		if privErr != nil {
			lib.HandleAPIError(w, http.StatusBadRequest, lib.LogAndReturnErrorObject(privErr, uid, request))
			return
		}
	}

	// Check if user has host/bouncer privileges (bypasses scan code check)
	hasPrivilege := (hosting != nil && hosting.IsHost) || (privilege != nil && privilege.Privilege == models.EventPrivilegeBouncer)

	if !hasPrivilege {
		// User doesn't have host/bouncer privileges, check scan code header
		scanCodeHeader := r.Header.Get("PASS_CODE")
		if scanCodeHeader == "" {
			lib.HandleAPIError(w, http.StatusUnauthorized, &models.ErrorObject{
				Message: "unauthorized",
				Display: "Scan code required",
			})
			return
		}

		// Verify scan code matches event's scan code
		ctx4, cancel4 := context.WithTimeout(r.Context(), 3*time.Second)
		defer cancel4()
		scanCodeResp, scanCodeErr := gelevent.GetScanCode(ctx4, gelevent.GetScanCodeRequest{
			EventId: eventIdStr,
		})
		if scanCodeErr != nil || !scanCodeResp.Exists {
			lib.HandleAPIError(w, http.StatusInternalServerError, lib.LogAndReturnErrorObject(errors.New("failed to verify scan code"), "", request))
			return
		}

		if scanCodeHeader != scanCodeResp.ScanCode {
			lib.HandleAPIError(w, http.StatusUnauthorized, &models.ErrorObject{
				Message: "unauthorized",
				Display: "Invalid scan code",
			})
			return
		}
	}

	// Get ticket scan status
	ctx5, cancel5 := context.WithTimeout(r.Context(), 5*time.Second)
	defer cancel5()
	statusResp, err := gelscan.GetTicketScanStatus(ctx5, gelscan.GetTicketScanStatusRequest{
		EventId: eventIdStr,
	})
	if err != nil {
		lib.HandleAPIError(w, http.StatusInternalServerError, lib.LogAndReturnErrorObject(err, uid, request))
		return
	}

	response := GetScanStatusResponse{
		NumScanned:   statusResp.NumScanned,
		TotalTickets: statusResp.TotalTickets,
	}

	lib.HandleAPISuccess(w, http.StatusOK, response)
}
