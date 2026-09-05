package geleventseries

import (
	"context"
	"encoding/json"
	"fmt"
	"ExampleCo-core/internal/v2/models"
	"ExampleCo-core/internal/v2/models/recurrence"
	"ExampleCo-core/internal/v2/services/gel/gelclient"
	"time"

	"github.com/geldata/gel-go/geltypes"
)

type UpdateSeriesRequest struct {
	SeriesId     string
	Name         *string
	Description  *string
	FormData     *models.SerializableEventFormData
	FlyerURL     *string
	RepeatConfig *models.EventSeriesRepeatConfig
}

// UpdateSeries updates an existing event series
func UpdateSeries(ctx context.Context, req UpdateSeriesRequest) error {
	client := gelclient.GetClient()

	// Build SET clauses dynamically
	setClauses := []string{"date_updated := datetime_current()"}
	params := map[string]any{
		"series_id": req.SeriesId,
	}

	if req.Name != nil {
		setClauses = append(setClauses, "name := <str>$name")
		params["name"] = *req.Name
	}

	if req.Description != nil {
		setClauses = append(setClauses, "description := <str>$description")
		params["description"] = *req.Description
	}

	if req.FormData != nil {
		formDataJSON, err := json.Marshal(req.FormData)
		if err != nil {
			return fmt.Errorf("failed to marshal form data: %w", err)
		}
		setClauses = append(setClauses, "form_data := <json>$form_data")
		params["form_data"] = formDataJSON
	}

	if req.FlyerURL != nil {
		setClauses = append(setClauses, "flyer_url := <str>$flyer_url")
		params["flyer_url"] = *req.FlyerURL
	}

	// Build the update query
	setClauseStr := ""
	for i, clause := range setClauses {
		if i > 0 {
			setClauseStr += ", "
		}
		setClauseStr += clause
	}

	query := fmt.Sprintf(`
		UPDATE EventSeries
		FILTER .series_id = <str>$series_id AND NOT .deleted
		SET {
			%s
		}
	`, setClauseStr)

	err := client.Execute(ctx, query, params)
	if err != nil {
		return fmt.Errorf("failed to update event series in gel: %w", err)
	}

	// If repeat config is updated, we need to update it separately
	if req.RepeatConfig != nil {
		err = updateRepeatConfig(ctx, req.SeriesId, req.RepeatConfig)
		if err != nil {
			return err
		}
	}

	return nil
}

func updateRepeatConfig(ctx context.Context, seriesId string, config *models.EventSeriesRepeatConfig) error {
	client := gelclient.GetClient()

	// Convert selected days
	selectedDays := make([]int32, len(config.SelectedDays))
	for i, day := range config.SelectedDays {
		selectedDays[i] = int32(day)
	}

	// Build optional fields
	numOccurrencesField := ""
	endDateField := ""
	if config.NumberOfOccurrences != nil {
		numOccurrencesField = "number_of_occurrences := <int32>$number_of_occurrences,"
	}
	if config.EndDate != nil {
		endDateField = "end_date := <datetime>$end_date,"
	}

	query := fmt.Sprintf(`
		WITH
			series := (SELECT EventSeries FILTER .series_id = <str>$series_id AND NOT .deleted LIMIT 1),
			new_config := (
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
		UPDATE series
		SET {
			repeat_config := new_config
		}
	`, numOccurrencesField, endDateField)

	params := map[string]any{
		"series_id":       seriesId,
		"repeat_interval": int32(config.RepeatInterval),
		"repeat_unit":     string(config.RepeatUnit),
		"selected_days":   selectedDays,
		"timezone":        timezoneOrUTC(config.Timezone),
		"end_type":        string(config.EndType),
	}

	if config.NumberOfOccurrences != nil {
		params["number_of_occurrences"] = int32(*config.NumberOfOccurrences)
	}
	if config.EndDate != nil {
		params["end_date"] = time.Unix(int64(*config.EndDate), 0)
	}

	err := client.Execute(ctx, query, params)
	if err != nil {
		return fmt.Errorf("failed to update repeat config in gel: %w", err)
	}

	return nil
}

// MarkOccurrencePublished marks an occurrence as published with the given event ID
func MarkOccurrencePublished(ctx context.Context, seriesId, occurrenceId, eventId string) error {
	client := gelclient.GetClient()

	query := `
		UPDATE EventSeriesOccurrence
		FILTER .occurrence_id = <str>$occurrence_id
		   AND EventSeriesOccurrence IN (SELECT EventSeries FILTER .series_id = <str>$series_id AND NOT .deleted).occurrences
		SET {
			published_event := (SELECT Event FILTER .firestore_id = <str>$event_id LIMIT 1),
			date_updated := datetime_current()
		}
	`

	params := map[string]any{
		"series_id":     seriesId,
		"occurrence_id": occurrenceId,
		"event_id":      eventId,
	}

	err := client.Execute(ctx, query, params)
	if err != nil {
		return fmt.Errorf("failed to mark occurrence as published in gel: %w", err)
	}

	return nil
}

// UpdateOccurrenceRequest is the request for updating an individual occurrence
type UpdateOccurrenceRequest struct {
	SeriesId     string
	OccurrenceId string
	FormData     *models.SerializableEventFormData
	Date         *time.Time
	// Scope is models.OccurrenceEditScopeThisEvent unless the caller asked for
	// more. The endpoint has already rejected anything that is not one of the
	// two scopes, so this is never anything else.
	Scope models.OccurrenceEditScope
}

// UpdateOccurrence updates an individual occurrence's form data and/or date, or
// hands the request on to the scoped path.
//
// The single-occurrence case is left exactly as it was, deliberately. It writes
// one row and derives nothing from the rest of the series, so there is nothing
// for a competing writer to invalidate and no transaction to hold; wrapping it
// in one would cost every ordinary edit a conflict it cannot have.
func UpdateOccurrence(ctx context.Context, req UpdateOccurrenceRequest) error {
	if scopeOf(req) == models.OccurrenceEditScopeThisAndFollowing {
		return UpdateOccurrencesFrom(ctx, req)
	}

	client := gelclient.GetClient()

	// Build SET clauses dynamically
	setClauses := []string{"date_updated := datetime_current()"}
	params := map[string]any{
		"series_id":     req.SeriesId,
		"occurrence_id": req.OccurrenceId,
	}

	if req.FormData != nil {
		formDataJSON, err := json.Marshal(req.FormData)
		if err != nil {
			return fmt.Errorf("failed to marshal form data: %w", err)
		}
		setClauses = append(setClauses, "form_data := <json>$form_data")
		params["form_data"] = formDataJSON
	}

	if req.Date != nil {
		setClauses = append(setClauses, "date := <datetime>$date")
		params["date"] = *req.Date
	}

	// Build the update query
	setClauseStr := ""
	for i, clause := range setClauses {
		if i > 0 {
			setClauseStr += ", "
		}
		setClauseStr += clause
	}

	query := fmt.Sprintf(`
		UPDATE EventSeriesOccurrence
		FILTER .occurrence_id = <str>$occurrence_id
		   AND EventSeriesOccurrence IN (SELECT EventSeries FILTER .series_id = <str>$series_id AND NOT .deleted).occurrences
		SET {
			%s
		}
	`, setClauseStr)

	err := client.Execute(ctx, query, params)
	if err != nil {
		return fmt.Errorf("failed to update occurrence in gel: %w", err)
	}

	return nil
}

// RegenerateOccurrences rebuilds a series' occurrence list from its repeat
// configuration, preserving the slots that must not be disturbed.
//
// The whole operation runs in one transaction, and the read that decides what
// to preserve happens inside it. That is not tidiness: it is the only thing
// that makes two simultaneous regenerates safe. Reading first and then writing
// leaves both requests planning against a store neither of them ends up
// writing to, and the two plans interleave into a series holding two copies of
// every slot. Reading inside the transaction makes the conflict visible to the
// store, which fails one of them; the driver then reruns that one against the
// state the winner left, and the result is what a single regenerate would have
// produced.
func RegenerateOccurrences(ctx context.Context, seriesId string, startDate time.Time) error {
	client := gelclient.GetClient()

	return client.Tx(ctx, func(ctx context.Context, tx geltypes.Tx) error {
		view, err := loadPlanningView(ctx, tx, seriesId)
		if err != nil {
			return err
		}
		if view == nil {
			return fmt.Errorf("series not found")
		}

		cfg, err := view.config()
		if err != nil {
			return err
		}
		form, formRaw, err := view.template()
		if err != nil {
			return err
		}

		plan, err := recurrence.PlanRegenerate(cfg, view.rows(),
			recurrence.DateIn(startDate, cfg.Location), form.StartTimeOffset)
		if err != nil {
			return fmt.Errorf("failed to plan regenerate for series %s: %w", seriesId, err)
		}

		if err := dropOccurrences(ctx, tx, seriesId, droppedIds(plan.Drop)); err != nil {
			return err
		}
		if err := insertSlots(ctx, tx, seriesId, plan.Insert, formRaw); err != nil {
			return err
		}
		// Touched unconditionally. A regenerate that finds the store already
		// correct writes no occurrence rows at all, and then has nothing for a
		// competing scoped edit to conflict with -- so the edit would be allowed
		// to plan against a list this request has already re-read and approved.
		return touchSeries(ctx, tx, seriesId)
	})
}

// ExtendOccurrences appends further slots to a series, continuing its own
// lattice past the last date it holds.
//
// It shares the transactional shape of a regenerate for the same reason: the
// slots to append are derived from the slots already there, so the derivation
// and the write have to see the same store or two extends produce overlapping
// dates.
func ExtendOccurrences(ctx context.Context, seriesId string, additionalCount int) (*models.EventSeries, error) {
	client := gelclient.GetClient()

	err := client.Tx(ctx, func(ctx context.Context, tx geltypes.Tx) error {
		view, err := loadPlanningView(ctx, tx, seriesId)
		if err != nil {
			return err
		}
		if view == nil {
			return fmt.Errorf("series not found")
		}

		cfg, err := view.config()
		if err != nil {
			return err
		}
		form, formRaw, err := view.template()
		if err != nil {
			return err
		}

		slots, err := recurrence.PlanExtend(cfg, view.rows(), additionalCount,
			form.StartTimeOffset)
		if err != nil {
			return fmt.Errorf("failed to plan extend for series %s: %w", seriesId, err)
		}
		if err := insertSlots(ctx, tx, seriesId, slots, formRaw); err != nil {
			return err
		}
		return touchSeries(ctx, tx, seriesId)
	})
	if err != nil {
		return nil, err
	}

	// Read the series back rather than reporting what was intended, so the
	// caller's response describes the store.
	seriesResp, err := GetSeries(ctx, GetSeriesRequest{SeriesId: seriesId})
	if err != nil {
		return nil, err
	}
	if !seriesResp.Exists {
		return nil, fmt.Errorf("series not found")
	}
	return seriesResp.Series, nil
}

// OccurrenceIsSold reports whether an occurrence's published event has taken
// money that has not been given back: a receipt item that is neither pending,
// nor refunded, nor abandoned.
//
// Publication alone does not make a slot permanent -- an event published and
// then sold nothing to is still the host's to remove. A sale does, because
// somebody outside the system is holding a ticket to it.
func OccurrenceIsSold(ctx context.Context, seriesId, occurrenceId string) (bool, error) {
	client := gelclient.GetClient()

	view, err := loadPlanningView(ctx, client, seriesId)
	if err != nil {
		return false, err
	}
	if view == nil {
		return false, fmt.Errorf("series not found")
	}
	return view.soldOccurrence(occurrenceId), nil
}
