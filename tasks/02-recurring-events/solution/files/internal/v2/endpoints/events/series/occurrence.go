package series

import (
	"errors"
	"net/http"
	"ExampleCo-core/internal/v2/lib"
	"ExampleCo-core/internal/v2/lib/testcoord"
	"ExampleCo-core/internal/v2/models"
	"ExampleCo-core/internal/v2/services/gel/geleventseries"
	"time"

	"github.com/go-chi/chi/v5"
)

type DeleteOccurrenceResponse struct {
	Success bool `json:"success"`
}

// DeleteOccurrence godoc
// @Summary      Remove an occurrence from a series
// @Tags         event-series
// @Accept       json
// @Produce      json
// @Security     BearerAuth
// @Param        seriesId path string true "Series ID"
// @Param        occurrenceId path string true "Occurrence ID"
// @Success      200 {object} lib.APISuccessOutput{data=DeleteOccurrenceResponse}
// @Failure      400 {object} lib.APIErrorOutput
// @Failure      404 {object} lib.APIErrorOutput
// @Router       /event-series/{seriesId}/occurrences/{occurrenceId} [delete]
func DeleteOccurrence(w http.ResponseWriter, r *http.Request) {
	var response DeleteOccurrenceResponse

	uid := lib.ExtractUID(r)
	_, err := lib.ApiPreCheck(r)
	if err != nil {
		lib.HandleAPIError(w, http.StatusBadRequest, lib.LogAndReturnErrorObject(err, uid, nil))
		return
	}

	// Get path parameters
	seriesId := chi.URLParam(r, "seriesId")
	occurrenceId := chi.URLParam(r, "occurrenceId")

	if seriesId == "" || occurrenceId == "" {
		lib.HandleAPIError(w, http.StatusBadRequest, &models.ErrorObject{
			Message: models.ErrorCodeInvalidData,
			Display: "Series ID and Occurrence ID are required",
		})
		return
	}

	// Get the series first to check permissions
	getResp, err := geleventseries.GetSeries(r.Context(), geleventseries.GetSeriesRequest{
		SeriesId: seriesId,
	})
	if err != nil {
		lib.HandleAPIError(w, http.StatusInternalServerError, lib.LogAndReturnErrorObject(err, uid, nil))
		return
	}

	if !getResp.Exists {
		lib.HandleAPIError(w, http.StatusNotFound, &models.ErrorObject{
			Message: models.ErrorCodeResourceNotFound,
			Display: "Event series not found",
		})
		return
	}

	// Check user permissions
	canManage, err := geleventseries.CheckUserCanManageSeries(r.Context(), uid, getResp.Series.OrganizationId)
	if err != nil {
		lib.HandleAPIError(w, http.StatusInternalServerError, lib.LogAndReturnErrorObject(err, uid, nil))
		return
	}
	if !canManage {
		lib.HandleAPIError(w, http.StatusForbidden, &models.ErrorObject{
			Message: models.ErrorCodeForbidden,
			Display: "You don't have permission to modify this event series",
		})
		return
	}

	// Test scaffolding: inert unless a test has armed it. Leave it where it is.
	testcoord.Checkpoint(r.Context(), testcoord.PreOccurrenceDelete)

	// Delete the occurrence. An occurrence whose published event has taken
	// money is not the host's to remove any more: somebody is holding a ticket
	// to it. That is a refusal of the request, not a fault in serving it, so it
	// answers 409 rather than 500 and the row is left exactly as it was.
	err = geleventseries.DeleteOccurrence(r.Context(), seriesId, occurrenceId)
	if errors.Is(err, geleventseries.ErrOccurrenceSold) {
		lib.HandleAPIError(w, http.StatusConflict, &models.ErrorObject{
			Message: models.ErrorCodeInvalidData,
			Display: "This occurrence has ticket sales and cannot be removed",
		})
		return
	}
	if err != nil {
		lib.HandleAPIError(w, http.StatusInternalServerError, lib.LogAndReturnErrorObject(err, uid, nil))
		return
	}

	response.Success = true
	lib.HandleAPISuccess(w, http.StatusOK, response)
}

type UpdateOccurrenceRequest struct {
	FormData *models.SerializableEventFormData `json:"formData"`
	Date     *int                              `json:"date"` // Unix timestamp
	// Scope selects how far the edit reaches. Absent or "thisEvent" edits the
	// one occurrence named in the path. "thisAndFollowing" edits that
	// occurrence and every later one in the series; see
	// geleventseries.UpdateOccurrence for what "later" means and for which
	// occurrences a scoped edit is not allowed to disturb.
	Scope *string `json:"scope"`
}

type UpdateOccurrenceResponse struct {
	Success bool `json:"success"`
}

// UpdateOccurrence godoc
// @Summary      Update an individual occurrence's form data
// @Tags         event-series
// @Accept       json
// @Produce      json
// @Security     BearerAuth
// @Param        seriesId path string true "Series ID"
// @Param        occurrenceId path string true "Occurrence ID"
// @Param        body body UpdateOccurrenceRequest true "Update request"
// @Success      200 {object} lib.APISuccessOutput{data=UpdateOccurrenceResponse}
// @Failure      400 {object} lib.APIErrorOutput
// @Failure      404 {object} lib.APIErrorOutput
// @Router       /event-series/{seriesId}/occurrences/{occurrenceId} [patch]
func UpdateOccurrence(w http.ResponseWriter, r *http.Request) {
	var request UpdateOccurrenceRequest
	var response UpdateOccurrenceResponse

	uid := lib.ExtractUID(r)
	_, err := lib.ApiPreCheck(r)
	if err != nil {
		lib.HandleAPIError(w, http.StatusBadRequest, lib.LogAndReturnErrorObject(err, uid, nil))
		return
	}

	// Get path parameters
	seriesId := chi.URLParam(r, "seriesId")
	occurrenceId := chi.URLParam(r, "occurrenceId")

	if seriesId == "" || occurrenceId == "" {
		lib.HandleAPIError(w, http.StatusBadRequest, &models.ErrorObject{
			Message: models.ErrorCodeInvalidData,
			Display: "Series ID and Occurrence ID are required",
		})
		return
	}

	if err = lib.ParseRequestBody(r, &request); err != nil {
		lib.HandleAPIError(w, http.StatusBadRequest, lib.LogAndReturnErrorObject(err, uid, request))
		return
	}

	// Must have at least one field to update
	if request.FormData == nil && request.Date == nil {
		lib.HandleAPIError(w, http.StatusBadRequest, &models.ErrorObject{
			Message: models.ErrorCodeInvalidData,
			Display: "At least one of formData or date is required",
		})
		return
	}

	scope := models.OccurrenceEditScopeThisEvent
	if request.Scope != nil && *request.Scope != "" {
		scope = models.OccurrenceEditScope(*request.Scope)
		if !scope.Valid() {
			lib.HandleAPIError(w, http.StatusBadRequest, &models.ErrorObject{
				Message: models.ErrorCodeInvalidData,
				Display: "scope must be thisEvent or thisAndFollowing",
			})
			return
		}
	}

	// date names one instant, so it can only answer for one occurrence. An edit
	// that reaches several has no use for it: the client sends the times it
	// wants the way the form has always carried them, and the request is
	// refused rather than guessed at if it tries to send both.
	if scope == models.OccurrenceEditScopeThisAndFollowing && request.Date != nil {
		lib.HandleAPIError(w, http.StatusBadRequest, &models.ErrorObject{
			Message: models.ErrorCodeInvalidData,
			Display: "date applies to a single occurrence; a thisAndFollowing edit carries its times in formData",
		})
		return
	}

	// Get the series first to check permissions
	getResp, err := geleventseries.GetSeries(r.Context(), geleventseries.GetSeriesRequest{
		SeriesId: seriesId,
	})
	if err != nil {
		lib.HandleAPIError(w, http.StatusInternalServerError, lib.LogAndReturnErrorObject(err, uid, request))
		return
	}

	if !getResp.Exists {
		lib.HandleAPIError(w, http.StatusNotFound, &models.ErrorObject{
			Message: models.ErrorCodeResourceNotFound,
			Display: "Event series not found",
		})
		return
	}

	// Check user permissions
	canManage, err := geleventseries.CheckUserCanManageSeries(r.Context(), uid, getResp.Series.OrganizationId)
	if err != nil {
		lib.HandleAPIError(w, http.StatusInternalServerError, lib.LogAndReturnErrorObject(err, uid, request))
		return
	}
	if !canManage {
		lib.HandleAPIError(w, http.StatusForbidden, &models.ErrorObject{
			Message: models.ErrorCodeForbidden,
			Display: "You don't have permission to modify this event series",
		})
		return
	}

	// Verify the occurrence exists
	occurrenceFound := false
	for _, occ := range getResp.Series.Occurrences {
		if occ.Id == occurrenceId {
			occurrenceFound = true
			break
		}
	}
	if !occurrenceFound {
		lib.HandleAPIError(w, http.StatusNotFound, &models.ErrorObject{
			Message: models.ErrorCodeResourceNotFound,
			Display: "Occurrence not found",
		})
		return
	}

	// Convert date if provided
	var dateTime *time.Time
	if request.Date != nil {
		t := time.Unix(int64(*request.Date), 0)
		dateTime = &t
	}

	// Test scaffolding: the harness uses this to interleave an occurrence edit
	// with a regenerate. Inert unless a test has armed it. Leave it where it is.
	testcoord.Checkpoint(r.Context(), testcoord.PreOccurrenceEdit)

	// Update the occurrence
	err = geleventseries.UpdateOccurrence(r.Context(), geleventseries.UpdateOccurrenceRequest{
		SeriesId:     seriesId,
		OccurrenceId: occurrenceId,
		FormData:     request.FormData,
		Date:         dateTime,
		Scope:        scope,
	})
	if err != nil {
		lib.HandleAPIError(w, http.StatusInternalServerError, lib.LogAndReturnErrorObject(err, uid, request))
		return
	}

	response.Success = true
	lib.HandleAPISuccess(w, http.StatusOK, response)
}

type PublishOccurrenceRequest struct {
	EventId string `json:"eventId" validate:"nonzero"`
}

type PublishOccurrenceResponse struct {
	Success bool `json:"success"`
}

// PublishOccurrence godoc
// @Summary      Mark an occurrence as published with an event ID
// @Tags         event-series
// @Accept       json
// @Produce      json
// @Security     BearerAuth
// @Param        seriesId path string true "Series ID"
// @Param        occurrenceId path string true "Occurrence ID"
// @Param        eventId body string true "Published Event ID"
// @Success      200 {object} lib.APISuccessOutput{data=PublishOccurrenceResponse}
// @Failure      400 {object} lib.APIErrorOutput
// @Failure      404 {object} lib.APIErrorOutput
// @Router       /event-series/{seriesId}/occurrences/{occurrenceId}/publish [post]
func PublishOccurrence(w http.ResponseWriter, r *http.Request) {
	var request PublishOccurrenceRequest
	var response PublishOccurrenceResponse

	uid := lib.ExtractUID(r)
	_, err := lib.ApiPreCheck(r)
	if err != nil {
		lib.HandleAPIError(w, http.StatusBadRequest, lib.LogAndReturnErrorObject(err, uid, nil))
		return
	}

	// Get path parameters
	seriesId := chi.URLParam(r, "seriesId")
	occurrenceId := chi.URLParam(r, "occurrenceId")

	if seriesId == "" || occurrenceId == "" {
		lib.HandleAPIError(w, http.StatusBadRequest, &models.ErrorObject{
			Message: models.ErrorCodeInvalidData,
			Display: "Series ID and Occurrence ID are required",
		})
		return
	}

	if err = lib.ParseRequestBody(r, &request); err != nil {
		lib.HandleAPIError(w, http.StatusBadRequest, lib.LogAndReturnErrorObject(err, uid, request))
		return
	}

	if request.EventId == "" {
		lib.HandleAPIError(w, http.StatusBadRequest, &models.ErrorObject{
			Message: models.ErrorCodeInvalidData,
			Display: "eventId is required",
		})
		return
	}

	// Get the series first to check permissions
	getResp, err := geleventseries.GetSeries(r.Context(), geleventseries.GetSeriesRequest{
		SeriesId: seriesId,
	})
	if err != nil {
		lib.HandleAPIError(w, http.StatusInternalServerError, lib.LogAndReturnErrorObject(err, uid, request))
		return
	}

	if !getResp.Exists {
		lib.HandleAPIError(w, http.StatusNotFound, &models.ErrorObject{
			Message: models.ErrorCodeResourceNotFound,
			Display: "Event series not found",
		})
		return
	}

	// Check user permissions
	canManage, err := geleventseries.CheckUserCanManageSeries(r.Context(), uid, getResp.Series.OrganizationId)
	if err != nil {
		lib.HandleAPIError(w, http.StatusInternalServerError, lib.LogAndReturnErrorObject(err, uid, request))
		return
	}
	if !canManage {
		lib.HandleAPIError(w, http.StatusForbidden, &models.ErrorObject{
			Message: models.ErrorCodeForbidden,
			Display: "You don't have permission to modify this event series",
		})
		return
	}

	// Verify the occurrence exists
	occurrenceFound := false
	for _, occ := range getResp.Series.Occurrences {
		if occ.Id == occurrenceId {
			occurrenceFound = true
			break
		}
	}
	if !occurrenceFound {
		lib.HandleAPIError(w, http.StatusNotFound, &models.ErrorObject{
			Message: models.ErrorCodeResourceNotFound,
			Display: "Occurrence not found",
		})
		return
	}

	// Test scaffolding: inert unless a test has armed it. Leave it where it is.
	testcoord.Checkpoint(r.Context(), testcoord.PreOccurrencePublish)

	// Mark the occurrence as published
	err = geleventseries.MarkOccurrencePublished(r.Context(), seriesId, occurrenceId, request.EventId)
	if err != nil {
		lib.HandleAPIError(w, http.StatusInternalServerError, lib.LogAndReturnErrorObject(err, uid, request))
		return
	}

	response.Success = true
	lib.HandleAPISuccess(w, http.StatusOK, response)
}

type RegenerateRequest struct {
	StartDate *time.Time `json:"startDate"`
}

type RegenerateResponse struct {
	Series models.EventSeries `json:"series"`
}

// Regenerate godoc
// @Summary      Regenerate occurrences from config
// @Tags         event-series
// @Accept       json
// @Produce      json
// @Security     BearerAuth
// @Param        seriesId path string true "Series ID"
// @Param        startDate body string false "Start Date (ISO8601)"
// @Success      200 {object} lib.APISuccessOutput{data=RegenerateResponse}
// @Failure      400 {object} lib.APIErrorOutput
// @Failure      404 {object} lib.APIErrorOutput
// @Router       /event-series/{seriesId}/regenerate [post]
func Regenerate(w http.ResponseWriter, r *http.Request) {
	var request RegenerateRequest
	var response RegenerateResponse

	uid := lib.ExtractUID(r)
	_, err := lib.ApiPreCheck(r)
	if err != nil {
		lib.HandleAPIError(w, http.StatusBadRequest, lib.LogAndReturnErrorObject(err, uid, nil))
		return
	}

	// Get series ID from path
	seriesId := chi.URLParam(r, "seriesId")
	if seriesId == "" {
		lib.HandleAPIError(w, http.StatusBadRequest, &models.ErrorObject{
			Message: models.ErrorCodeInvalidData,
			Display: "Series ID is required",
		})
		return
	}

	// Parse optional body
	_ = lib.ParseRequestBody(r, &request)

	// Get the series first to check permissions
	getResp, err := geleventseries.GetSeries(r.Context(), geleventseries.GetSeriesRequest{
		SeriesId: seriesId,
	})
	if err != nil {
		lib.HandleAPIError(w, http.StatusInternalServerError, lib.LogAndReturnErrorObject(err, uid, request))
		return
	}

	if !getResp.Exists {
		lib.HandleAPIError(w, http.StatusNotFound, &models.ErrorObject{
			Message: models.ErrorCodeResourceNotFound,
			Display: "Event series not found",
		})
		return
	}

	// Check user permissions
	canManage, err := geleventseries.CheckUserCanManageSeries(r.Context(), uid, getResp.Series.OrganizationId)
	if err != nil {
		lib.HandleAPIError(w, http.StatusInternalServerError, lib.LogAndReturnErrorObject(err, uid, request))
		return
	}
	if !canManage {
		lib.HandleAPIError(w, http.StatusForbidden, &models.ErrorObject{
			Message: models.ErrorCodeForbidden,
			Display: "You don't have permission to modify this event series",
		})
		return
	}

	// Determine start date
	startDate := lib.Now()
	if request.StartDate != nil {
		startDate = *request.StartDate
	}

	// Test scaffolding: the harness uses this to line up competing regenerate
	// requests. Inert unless a test has armed it. Leave it where it is.
	testcoord.Checkpoint(r.Context(), testcoord.PreRegenerate)

	// Regenerate occurrences
	err = geleventseries.RegenerateOccurrences(r.Context(), seriesId, startDate)
	if err != nil {
		lib.HandleAPIError(w, http.StatusInternalServerError, lib.LogAndReturnErrorObject(err, uid, request))
		return
	}

	// Get the updated series
	getResp, err = geleventseries.GetSeries(r.Context(), geleventseries.GetSeriesRequest{
		SeriesId: seriesId,
	})
	if err != nil {
		lib.HandleAPIError(w, http.StatusInternalServerError, lib.LogAndReturnErrorObject(err, uid, request))
		return
	}

	response.Series = *getResp.Series
	lib.HandleAPISuccess(w, http.StatusOK, response)
}

type ExtendRequest struct {
	AdditionalOccurrences int `json:"additionalOccurrences" validate:"min=1,max=100"`
}

type ExtendResponse struct {
	Series models.EventSeries `json:"series"`
}

// Extend godoc
// @Summary      Extend a series with additional occurrences
// @Tags         event-series
// @Accept       json
// @Produce      json
// @Security     BearerAuth
// @Param        seriesId path string true "Series ID"
// @Param        body body ExtendRequest true "Extend request"
// @Success      200 {object} lib.APISuccessOutput{data=ExtendResponse}
// @Failure      400 {object} lib.APIErrorOutput
// @Failure      404 {object} lib.APIErrorOutput
// @Router       /event-series/{seriesId}/extend [post]
func Extend(w http.ResponseWriter, r *http.Request) {
	var request ExtendRequest
	var response ExtendResponse

	uid := lib.ExtractUID(r)
	_, err := lib.ApiPreCheck(r)
	if err != nil {
		lib.HandleAPIError(w, http.StatusBadRequest, lib.LogAndReturnErrorObject(err, uid, nil))
		return
	}

	// Get series ID from path
	seriesId := chi.URLParam(r, "seriesId")
	if seriesId == "" {
		lib.HandleAPIError(w, http.StatusBadRequest, &models.ErrorObject{
			Message: models.ErrorCodeInvalidData,
			Display: "Series ID is required",
		})
		return
	}

	// Parse request body
	if err = lib.ParseRequestBody(r, &request); err != nil {
		lib.HandleAPIError(w, http.StatusBadRequest, lib.LogAndReturnErrorObject(err, uid, request))
		return
	}

	if request.AdditionalOccurrences <= 0 {
		lib.HandleAPIError(w, http.StatusBadRequest, &models.ErrorObject{
			Message: models.ErrorCodeInvalidData,
			Display: "additionalOccurrences must be greater than 0",
		})
		return
	}

	if request.AdditionalOccurrences > 100 {
		lib.HandleAPIError(w, http.StatusBadRequest, &models.ErrorObject{
			Message: models.ErrorCodeInvalidData,
			Display: "additionalOccurrences must not exceed 100",
		})
		return
	}

	// Get the series first to check permissions
	getResp, err := geleventseries.GetSeries(r.Context(), geleventseries.GetSeriesRequest{
		SeriesId: seriesId,
	})
	if err != nil {
		lib.HandleAPIError(w, http.StatusInternalServerError, lib.LogAndReturnErrorObject(err, uid, request))
		return
	}

	if !getResp.Exists {
		lib.HandleAPIError(w, http.StatusNotFound, &models.ErrorObject{
			Message: models.ErrorCodeResourceNotFound,
			Display: "Event series not found",
		})
		return
	}

	// Check user permissions
	canManage, err := geleventseries.CheckUserCanManageSeries(r.Context(), uid, getResp.Series.OrganizationId)
	if err != nil {
		lib.HandleAPIError(w, http.StatusInternalServerError, lib.LogAndReturnErrorObject(err, uid, request))
		return
	}
	if !canManage {
		lib.HandleAPIError(w, http.StatusForbidden, &models.ErrorObject{
			Message: models.ErrorCodeForbidden,
			Display: "You don't have permission to modify this event series",
		})
		return
	}

	// Test scaffolding: inert unless a test has armed it. Leave it where it is.
	testcoord.Checkpoint(r.Context(), testcoord.PreExtend)

	// Extend occurrences
	updatedSeries, err := geleventseries.ExtendOccurrences(r.Context(), seriesId, request.AdditionalOccurrences)
	if err != nil {
		lib.HandleAPIError(w, http.StatusInternalServerError, lib.LogAndReturnErrorObject(err, uid, request))
		return
	}

	response.Series = *updatedSeries
	lib.HandleAPISuccess(w, http.StatusOK, response)
}
