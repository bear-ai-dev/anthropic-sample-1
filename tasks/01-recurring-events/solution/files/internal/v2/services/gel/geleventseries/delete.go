package geleventseries

import (
	"context"
	"errors"
	"fmt"
	"ExampleCo-core/internal/v2/services/gel/gelclient"

	"github.com/geldata/gel-go/geltypes"
)

// DeleteSeries soft-deletes an event series
func DeleteSeries(ctx context.Context, seriesId string) error {
	client := gelclient.GetClient()

	query := `
		UPDATE EventSeries
		FILTER .series_id = <str>$series_id AND NOT .deleted
		SET {
			deleted := true,
			deleted_at := datetime_current()
		}
	`

	params := map[string]any{
		"series_id": seriesId,
	}

	err := client.Execute(ctx, query, params)
	if err != nil {
		return fmt.Errorf("failed to delete event series in gel: %w", err)
	}

	return nil
}

// ErrOccurrenceSold reports a refusal to remove an occurrence whose published
// event has taken money. It is a distinct error rather than a generic failure
// so that the endpoint can answer with a refusal instead of a fault.
var ErrOccurrenceSold = errors.New("occurrence has a published event with live sales")

// DeleteOccurrence removes an occurrence from a series, unless its published
// event has taken money.
//
// The check and the delete share a transaction. A sale that lands between a
// separate check and a separate delete would be destroyed by a request that had
// already established there was nothing to destroy, which is the narrow race
// the protection exists to close.
func DeleteOccurrence(ctx context.Context, seriesId, occurrenceId string) error {
	client := gelclient.GetClient()

	return client.Tx(ctx, func(ctx context.Context, tx geltypes.Tx) error {
		view, err := loadPlanningView(ctx, tx, seriesId)
		if err != nil {
			return err
		}
		if view == nil {
			return fmt.Errorf("series not found")
		}
		if view.soldOccurrence(occurrenceId) {
			return ErrOccurrenceSold
		}
		return deleteOccurrenceRow(ctx, tx, seriesId, occurrenceId)
	})
}

// deleteOccurrenceRow unlinks one occurrence and deletes it.
func deleteOccurrenceRow(ctx context.Context, ex geltypes.Executor, seriesId, occurrenceId string) error {
	// First unlink the occurrence from the series, then delete it.
	// This is required because the multi-link has a default "Restrict" deletion policy
	// that prevents deleting objects that are still linked.
	query := `
		WITH
			series := (SELECT EventSeries FILTER .series_id = <str>$series_id AND NOT .deleted LIMIT 1),
			occurrence := (
				SELECT EventSeriesOccurrence
				FILTER .occurrence_id = <str>$occurrence_id
				   AND EventSeriesOccurrence IN series.occurrences
				LIMIT 1
			)
		SELECT {
			unlinked := (
				UPDATE series
				SET {
					occurrences -= occurrence
				}
			),
			deleted := (DELETE occurrence)
		}
	`

	params := map[string]any{
		"series_id":     seriesId,
		"occurrence_id": occurrenceId,
	}

	err := ex.Execute(ctx, query, params)
	if err != nil {
		return fmt.Errorf("failed to delete occurrence in gel: %w", err)
	}

	return nil
}
