package geleventseries

import (
	"context"
	"encoding/json"
	"fmt"
	"ExampleCo-core/internal/v2/models"
	"ExampleCo-core/internal/v2/services/gel/gelclient"
	"time"
)

type CreateSeriesRequest struct {
	SeriesId       string
	OrganizationId string
	Name           string
	Description    string
	FormData       models.SerializableEventFormData
	FlyerURL       *string
	RepeatConfig   models.EventSeriesRepeatConfig
}

type CreateSeriesResponse struct {
	Series *models.EventSeries
}

// CreateSeries creates a new event series in the gel database
func CreateSeries(ctx context.Context, req CreateSeriesRequest) (*CreateSeriesResponse, error) {
	client := gelclient.GetClient()

	// Marshal form data to JSON
	formDataJSON, err := json.Marshal(req.FormData)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal form data: %w", err)
	}

	// Map repeat unit to gel enum
	repeatUnit := string(req.RepeatConfig.RepeatUnit)
	endType := string(req.RepeatConfig.EndType)

	// Convert selected days to int32 slice for gel
	selectedDays := make([]int32, len(req.RepeatConfig.SelectedDays))
	for i, day := range req.RepeatConfig.SelectedDays {
		selectedDays[i] = int32(day)
	}

	// Build optional fields
	flyerField := ""
	if req.FlyerURL != nil && *req.FlyerURL != "" {
		flyerField = "flyer_url := <str>$flyer_url,"
	}

	numOccurrencesField := ""
	if req.RepeatConfig.NumberOfOccurrences != nil {
		numOccurrencesField = "number_of_occurrences := <int32>$number_of_occurrences,"
	}

	endDateField := ""
	if req.RepeatConfig.EndDate != nil {
		endDateField = "end_date := <datetime>$end_date,"
	}

	// Build optional description field
	descriptionField := ""
	if req.Description != "" {
		descriptionField = "description := <str>$description,"
	}

	query := fmt.Sprintf(`
		WITH
			repeat_config := (
				INSERT EventSeriesRepeatConfig {
					repeat_interval := <int32>$repeat_interval,
					repeat_unit := <EventSeriesRepeatUnit>$repeat_unit,
					selected_days := <array<int32>>$selected_days,
					timezone := <str>$timezone,
					end_type := <EventSeriesEndType>$end_type,
					%s
					%s
				}
			)
		INSERT EventSeries {
			series_id := <str>$series_id,
			organization := (SELECT Organization FILTER .firestore_id = <str>$organization_id AND NOT .deleted LIMIT 1),
			name := <str>$name,
			%s
			form_data := <json>$form_data,
			%s
			repeat_config := repeat_config
		}
	`, numOccurrencesField, endDateField, descriptionField, flyerField)

	params := map[string]any{
		"series_id":       req.SeriesId,
		"organization_id": req.OrganizationId,
		"name":            req.Name,
		"form_data":       formDataJSON,
		"repeat_interval": int32(req.RepeatConfig.RepeatInterval),
		"repeat_unit":     repeatUnit,
		"selected_days":   selectedDays,
		"timezone":        timezoneOrUTC(req.RepeatConfig.Timezone),
		"end_type":        endType,
	}

	if req.Description != "" {
		params["description"] = req.Description
	}
	if req.FlyerURL != nil && *req.FlyerURL != "" {
		params["flyer_url"] = *req.FlyerURL
	}
	if req.RepeatConfig.NumberOfOccurrences != nil {
		params["number_of_occurrences"] = int32(*req.RepeatConfig.NumberOfOccurrences)
	}
	if req.RepeatConfig.EndDate != nil {
		params["end_date"] = time.Unix(int64(*req.RepeatConfig.EndDate), 0)
	}

	var output []byte
	err = client.QueryJSON(ctx, query, &output, params)
	if err != nil {
		return nil, fmt.Errorf("failed to create event series in gel: %w", err)
	}

	// Build response
	series := &models.EventSeries{
		Id:             req.SeriesId,
		OrganizationId: req.OrganizationId,
		Name:           req.Name,
		Description:    req.Description,
		DateCreated:    int(time.Now().Unix()),
		FormData:       req.FormData,
		FlyerURL:       req.FlyerURL,
		RepeatConfig:   req.RepeatConfig,
		Occurrences:    []models.EventSeriesOccurrence{},
	}

	return &CreateSeriesResponse{Series: series}, nil
}

// timezoneOrUTC normalises a missing zone name to the column default.
func timezoneOrUTC(name string) string {
	if name == "" {
		return "UTC"
	}
	return name
}

// CreateOccurrence creates a new occurrence for a series
func CreateOccurrence(ctx context.Context, seriesId, occurrenceId string, date time.Time, formData *models.SerializableEventFormData) error {
	client := gelclient.GetClient()

	// Build form_data field if provided
	formDataField := ""
	params := map[string]any{
		"series_id":     seriesId,
		"occurrence_id": occurrenceId,
		"date":          date,
	}

	if formData != nil {
		formDataJSON, err := json.Marshal(formData)
		if err != nil {
			return fmt.Errorf("failed to marshal form data: %w", err)
		}
		formDataField = "form_data := <json>$form_data,"
		params["form_data"] = formDataJSON
	}

	query := fmt.Sprintf(`
		WITH
			series := (SELECT EventSeries FILTER .series_id = <str>$series_id AND NOT .deleted LIMIT 1),
			new_occurrence := (
				INSERT EventSeriesOccurrence {
					occurrence_id := <str>$occurrence_id,
					date := <datetime>$date,
					%s
				}
			)
		UPDATE series
		SET {
			occurrences += new_occurrence
		}
	`, formDataField)

	err := client.Execute(ctx, query, params)
	if err != nil {
		return fmt.Errorf("failed to create occurrence in gel: %w", err)
	}

	return nil
}

// CreateOccurrencesBatch links a whole set of occurrences to a series.
//
// The batch lands in one statement rather than one statement per occurrence.
// A loop leaves a partially generated series behind whenever it fails in the
// middle -- a set of slots that matches no repeat configuration, with nothing
// recording how far it got -- and there is no way for a caller to tell that
// apart from a series that was always meant to be short.
func CreateOccurrencesBatch(ctx context.Context, seriesId string, occurrences []models.EventSeriesOccurrence) error {
	payload := make([]slotPayload, 0, len(occurrences))
	for _, occ := range occurrences {
		row := slotPayload{
			OccurrenceId: occ.Id,
			Date:         storedInstant(time.Unix(int64(occ.Date), 0)),
			FormData:     json.RawMessage("{}"),
		}
		if occ.FormData != nil {
			encoded, err := json.Marshal(occ.FormData)
			if err != nil {
				return fmt.Errorf("failed to marshal form data for occurrence %s: %w", occ.Id, err)
			}
			row.FormData = encoded
		}
		payload = append(payload, row)
	}

	return insertPayload(ctx, gelclient.GetClient(), seriesId, payload)
}
