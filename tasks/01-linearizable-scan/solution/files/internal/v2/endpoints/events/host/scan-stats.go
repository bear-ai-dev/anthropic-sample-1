package host

import (
	"errors"
	"net/http"
	"ExampleCo-core/internal/v2/lib"
	"ExampleCo-core/internal/v2/models"
	"ExampleCo-core/internal/v2/services/cache"
	"ExampleCo-core/internal/v2/services/gel/gelevent"
	"ExampleCo-core/internal/v2/services/gel/gelscan"

	"github.com/google/uuid"
	"gopkg.in/validator.v2"
)

type ScanStatsRequest struct {
	EventId uuid.UUID `json:"eventId" validate:"nonzero" query:"eventId"`
}

func (r *ScanStatsRequest) Validate() error {
	if err := validator.Validate(r); err != nil {
		return err
	}
	return nil
}

type ScanStatsResponse struct {
	ScannedPeople     int     `json:"scannedPeople"`
	ExpectedAttendees int     `json:"expectedAttendees"`
	ScanRatePercent   float64 `json:"scanRatePercent"`
}

// ScanStats returns scanning statistics for an event
func ScanStats(w http.ResponseWriter, r *http.Request) {
	var request ScanStatsRequest
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

	// Get event to verify it exists
	event, err := gelevent.GetEvent(r.Context(), gelevent.GetEventRequest{EventId: request.EventId.String()})
	if err != nil {
		lib.HandleAPIError(w, http.StatusInternalServerError, lib.LogAndReturnErrorObject(err, uid, request))
		return
	}
	if !event.Exists {
		lib.HandleAPIError(w, http.StatusNotFound, lib.LogAndReturnErrorObject(errors.New(models.ErrorCodeResourceNotFound), "", request))
		return
	}

	// Check if userId has sufficient privilege
	hosting, err := gelevent.CheckEventHostingPrivilege(r.Context(), gelevent.CheckEventHostingPrivilegeRequest{
		EventId: event.Event.Id,
		UserId:  uid,
	})
	if err != nil {
		lib.HandleAPIError(w, http.StatusBadRequest, lib.LogAndReturnErrorObject(err, uid, request))
		return
	}
	if !hosting.IsHost {
		lib.HandleAPIError(w, http.StatusUnauthorized, lib.LogAndReturnErrorObject(errors.New("not eligible"), "", request))
		return
	}

	// Check cache first
	cacheKey := cache.HostScanStatsKey(request.EventId.String())
	if cached, ok := cache.Get[ScanStatsResponse](r.Context(), cacheKey); ok {
		lib.HandleAPISuccess(w, http.StatusOK, cached)
		return
	}

	// Get scan stats
	statsResp, err := gelscan.GetScanStats(r.Context(), gelscan.GetScanStatsRequest{
		EventId: request.EventId.String(),
	})
	if err != nil {
		lib.HandleAPIError(w, http.StatusInternalServerError, lib.LogAndReturnErrorObject(err, uid, request))
		return
	}

	response := ScanStatsResponse{
		ScannedPeople:     statsResp.ScannedPeople,
		ExpectedAttendees: statsResp.ExpectedAttendees,
		ScanRatePercent:   statsResp.ScanRatePercent,
	}

	// Cache the response
	cache.Set(r.Context(), cacheKey, response, cache.HostDashboardTTL)

	lib.HandleAPISuccess(w, http.StatusOK, response)
}
