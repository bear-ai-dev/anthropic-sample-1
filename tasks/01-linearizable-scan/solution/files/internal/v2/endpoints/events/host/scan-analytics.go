package host

import (
	"errors"
	"net/http"
	"ExampleCo-core/internal/v2/lib"
	"ExampleCo-core/internal/v2/models"
	"ExampleCo-core/internal/v2/services/gel/gelevent"
	"ExampleCo-core/internal/v2/services/gel/gelscan"

	"github.com/google/uuid"
	"gopkg.in/validator.v2"
)

type ScanAnalyticsRequest struct {
	EventId uuid.UUID `json:"eventId" validate:"nonzero" query:"eventId"`
}

func (r *ScanAnalyticsRequest) Validate() error {
	if err := validator.Validate(r); err != nil {
		return err
	}
	return nil
}

type ScanAnalyticsResponse struct {
	Timeline          []models.ScanAnalyticsBucket `json:"timeline"`
	AverageScanTimeMs *int                         `json:"averageScanTimeMs"`
}

// ScanAnalytics returns scan timeline analytics with 15-minute buckets
func ScanAnalytics(w http.ResponseWriter, r *http.Request) {
	var request ScanAnalyticsRequest
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

	// Get scan timeline
	timelineResp, err := gelscan.GetScanTimeline(r.Context(), gelscan.GetScanTimelineRequest{
		EventId: request.EventId.String(),
	})
	if err != nil {
		lib.HandleAPIError(w, http.StatusInternalServerError, lib.LogAndReturnErrorObject(err, uid, request))
		return
	}

	response := ScanAnalyticsResponse{
		Timeline:          timelineResp.Timeline,
		AverageScanTimeMs: timelineResp.AverageScanTimeMs,
	}

	lib.HandleAPISuccess(w, http.StatusOK, response)
}
