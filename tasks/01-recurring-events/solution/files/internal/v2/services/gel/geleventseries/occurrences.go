package geleventseries

import (
	"context"
	"encoding/json"
	"fmt"
	"ExampleCo-core/internal/v2/models/recurrence"
	"time"

	"github.com/geldata/gel-go/geltypes"
	"github.com/google/uuid"
)

// insertOccurrencesQuery links a whole batch of new occurrences to a series in
// one statement.
//
// One statement rather than one per slot, and not only for speed. A regenerate
// that inserts in a loop is a regenerate that can stop halfway, leaving a
// series holding part of a pattern with no record of which part; and inside a
// transaction each extra round trip is another chance to collide with a
// competing writer and be retried. The slots arrive as a JSON array so that the
// count of them does not change the shape of the query.
const insertOccurrencesQuery = `
	WITH
		series := (
			SELECT EventSeries
			FILTER .series_id = <str>$series_id AND NOT .deleted
			LIMIT 1
		),
		created := (
			FOR slot IN json_array_unpack(<json>$slots) UNION (
				INSERT EventSeriesOccurrence {
					occurrence_id := <str>slot['occurrenceId'],
					date := <datetime><str>slot['date'],
					form_data := slot['formData']
				}
			)
		)
	UPDATE series SET { occurrences += created }
`

// dropOccurrencesQuery unlinks a batch of occurrences from their series and
// deletes them, in that order.
//
// The order is forced: the occurrences link carries the default Restrict
// deletion policy, so a delete that has not been unlinked first is refused
// rather than cascaded. Doing both in one statement means a regenerate cannot
// leave a series pointing at rows that no longer exist.
const dropOccurrencesQuery = `
	WITH
		series := (
			SELECT EventSeries
			FILTER .series_id = <str>$series_id AND NOT .deleted
			LIMIT 1
		),
		doomed := (
			SELECT EventSeriesOccurrence
			FILTER EventSeriesOccurrence IN series.occurrences
			   AND .occurrence_id IN array_unpack(<array<str>>$occurrence_ids)
		)
	SELECT {
		unlinked := (UPDATE series SET { occurrences -= doomed }),
		deleted := (DELETE doomed)
	}
`

// slotPayload is one row of the JSON array handed to insertOccurrencesQuery.
type slotPayload struct {
	OccurrenceId string          `json:"occurrenceId"`
	Date         string          `json:"date"`
	FormData     json.RawMessage `json:"formData"`
}

// storedInstant renders an instant the way the date column takes it. The
// instant is the whole of what a row stores; the zone lives on the repeat
// configuration, because it describes the series rather than any one
// occurrence.
func storedInstant(t time.Time) string {
	return t.UTC().Format("2006-01-02T15:04:05Z")
}

// insertPayload links a prepared batch of occurrence rows to a series.
func insertPayload(ctx context.Context, ex geltypes.Executor, seriesId string,
	payload []slotPayload) error {
	if len(payload) == 0 {
		return nil
	}

	encoded, err := json.Marshal(payload)
	if err != nil {
		return fmt.Errorf("failed to encode %d occurrence rows: %w", len(payload), err)
	}

	err = ex.Execute(ctx, insertOccurrencesQuery, map[string]any{
		"series_id": seriesId,
		"slots":     encoded,
	})
	if err != nil {
		return fmt.Errorf("failed to insert %d occurrences for series %s: %w",
			len(payload), seriesId, err)
	}
	return nil
}

// insertSlots creates a row for every generated slot and links them all to the
// series. Each row gets a fresh identifier: these are new slots, and reusing an
// identifier from a slot that was just deleted would make a published event's
// link to it resolve to something else.
func insertSlots(ctx context.Context, ex geltypes.Executor, seriesId string,
	slots []recurrence.Slot, formData json.RawMessage) error {
	payload := make([]slotPayload, 0, len(slots))
	for _, slot := range slots {
		payload = append(payload, slotPayload{
			OccurrenceId: uuid.New().String(),
			Date:         storedInstant(slot.Instant),
			FormData:     formData,
		})
	}
	return insertPayload(ctx, ex, seriesId, payload)
}

// dropOccurrences removes the rows a plan decided against.
func dropOccurrences(ctx context.Context, ex geltypes.Executor, seriesId string,
	ids []string) error {
	if len(ids) == 0 {
		return nil
	}
	err := ex.Execute(ctx, dropOccurrencesQuery, map[string]any{
		"series_id":      seriesId,
		"occurrence_ids": ids,
	})
	if err != nil {
		return fmt.Errorf("failed to drop %d occurrences from series %s: %w",
			len(ids), seriesId, err)
	}
	return nil
}

// droppedIds lists the identifiers a plan means to remove.
func droppedIds(decisions []recurrence.Decision) []string {
	out := make([]string, 0, len(decisions))
	for _, d := range decisions {
		out = append(out, d.Row.Id)
	}
	return out
}
