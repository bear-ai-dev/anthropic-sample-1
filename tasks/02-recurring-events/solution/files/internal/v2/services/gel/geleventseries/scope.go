package geleventseries

import (
	"context"
	"encoding/json"
	"fmt"
	"ExampleCo-core/internal/v2/models"
	"ExampleCo-core/internal/v2/models/recurrence"
	"ExampleCo-core/internal/v2/services/gel/gelclient"

	"github.com/geldata/gel-go/geltypes"
)

// rewriteOccurrenceQuery rewrites a batch of occurrence rows in one statement:
// each named row takes the instant and the form data the batch carries for it,
// and every one of them is stamped as individually edited.
//
// One statement rather than one per row, for the same reason the insert batch is
// one statement. A scoped edit that walks a loop can stop halfway, and what it
// leaves behind is a series where some occurrences moved and some did not, with
// nothing recording which -- indistinguishable from a scoped edit that was
// supposed to stop there.
//
// The stamp is not cosmetic. It is the mark a regenerate reads to decide that a
// row was edited by hand, so a scoped edit that moves rows without stamping them
// produces occurrences a later regenerate silently overwrites.
const rewriteOccurrencesQuery = `
	WITH
		series := (
			SELECT EventSeries
			FILTER .series_id = <str>$series_id AND NOT .deleted
			LIMIT 1
		)
	FOR row IN json_array_unpack(<json>$rows) UNION (
		UPDATE EventSeriesOccurrence
		FILTER .occurrence_id = <str>row['occurrenceId']
		   AND EventSeriesOccurrence IN series.occurrences
		SET {
			date := <datetime><str>row['date'],
			form_data := row['formData'],
			date_updated := datetime_current()
		}
	)
`

// rewritePayload is one row of the JSON array handed to the query above.
type rewritePayload struct {
	OccurrenceId string          `json:"occurrenceId"`
	Date         string          `json:"date"`
	FormData     json.RawMessage `json:"formData"`
}

// applyScopedEdit rewrites every row a scoped edit reaches.
func applyScopedEdit(ctx context.Context, ex geltypes.Executor, seriesId string,
	moves []recurrence.ScopedMove, formData json.RawMessage) error {
	if len(moves) == 0 {
		return nil
	}

	rows := make([]rewritePayload, 0, len(moves))
	for _, m := range moves {
		rows = append(rows, rewritePayload{
			OccurrenceId: m.Row.Id,
			Date:         storedInstant(m.Instant),
			FormData:     formData,
		})
	}

	encoded, err := json.Marshal(rows)
	if err != nil {
		return fmt.Errorf("failed to encode %d occurrence edits: %w", len(rows), err)
	}

	if err := ex.Execute(ctx, rewriteOccurrencesQuery, map[string]any{
		"series_id": seriesId,
		"rows":      encoded,
	}); err != nil {
		return fmt.Errorf("failed to apply a scoped edit to %d occurrences of series %s: %w",
			len(rows), seriesId, err)
	}
	return nil
}

// UpdateOccurrencesFrom applies one form-data edit to an occurrence and to every
// occurrence of the series that is not before it, leaving the paid ones alone.
//
// The whole operation runs in one transaction, and the read that decides which
// rows the scope reaches happens inside it. That is the same requirement the
// regenerate path has and for the same reason, but it is a requirement of *this*
// path independently: a scoped edit and a regenerate both rewrite the occurrence
// list, so a scoped edit that reads outside its transaction plans against a list
// a regenerate is about to replace, and the rows it then writes are rows that no
// longer belong to the series' pattern. Protecting only the regenerate leaves
// the pair unserialisable, because it takes two participants to serialise.
//
// The series row is touched as well as the occurrence rows. Two writers that
// only ever touch disjoint occurrences have no conflict for the store to detect,
// and a scoped edit that moves three rows while a regenerate deletes and
// replaces four of them can interleave into a series holding some of each plan.
// Writing the series itself makes the overlap visible, so the store aborts one
// of them and the driver retries it against what the winner left.
func UpdateOccurrencesFrom(ctx context.Context, req UpdateOccurrenceRequest) error {
	if req.FormData == nil {
		return fmt.Errorf("a scoped edit needs form data to apply")
	}

	formData, err := json.Marshal(req.FormData)
	if err != nil {
		return fmt.Errorf("failed to marshal form data: %w", err)
	}

	client := gelclient.GetClient()
	return client.Tx(ctx, func(ctx context.Context, tx geltypes.Tx) error {
		view, err := loadPlanningView(ctx, tx, req.SeriesId)
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

		plan, err := recurrence.PlanScopedEdit(cfg, view.rows(), req.OccurrenceId,
			req.FormData.StartTimeOffset)
		if err != nil {
			return fmt.Errorf("failed to plan a scoped edit of series %s: %w",
				req.SeriesId, err)
		}

		if err := applyScopedEdit(ctx, tx, req.SeriesId, plan.Move, formData); err != nil {
			return err
		}
		return touchSeries(ctx, tx, req.SeriesId)
	})
}

// touchSeries writes the series row itself, so that two requests rewriting
// different occurrences of the same series still conflict.
func touchSeries(ctx context.Context, ex geltypes.Executor, seriesId string) error {
	err := ex.Execute(ctx, `
		UPDATE EventSeries
		FILTER .series_id = <str>$series_id AND NOT .deleted
		SET { date_updated := datetime_current() }
	`, map[string]any{"series_id": seriesId})
	if err != nil {
		return fmt.Errorf("failed to touch series %s: %w", seriesId, err)
	}
	return nil
}

// scopeOf reads the scope off a request, defaulting to the single occurrence.
func scopeOf(req UpdateOccurrenceRequest) models.OccurrenceEditScope {
	if req.Scope == "" {
		return models.OccurrenceEditScopeThisEvent
	}
	return req.Scope
}
