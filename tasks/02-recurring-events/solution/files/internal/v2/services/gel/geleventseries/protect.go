package geleventseries

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"ExampleCo-core/internal/v2/models"
	"ExampleCo-core/internal/v2/models/recurrence"
	"time"

	"github.com/geldata/gel-go/geltypes"
)

// planningView is the slice of a series that deciding a regenerate needs: the
// repeat configuration, the template's time of day, and for every stored
// occurrence its date, whether it has been published, whether it has been
// edited, and how much live money is attached to it.
//
// It is loaded in one query so that a regenerate sees one consistent picture.
// Reading the occurrences separately from the receipt items would let a sale
// land in between, and the sale is the thing being protected.
type planningView struct {
	SeriesId    string          `json:"series_id"`
	FormData    json.RawMessage `json:"form_data"`
	RepeatConfg *struct {
		RepeatInterval      int32      `json:"repeat_interval"`
		RepeatUnit          string     `json:"repeat_unit"`
		SelectedDays        []int32    `json:"selected_days"`
		Timezone            string     `json:"timezone"`
		EndType             string     `json:"end_type"`
		NumberOfOccurrences *int32     `json:"number_of_occurrences"`
		EndDate             *time.Time `json:"end_date"`
	} `json:"repeat_config"`
	Occurrences []struct {
		OccurrenceId   string     `json:"occurrence_id"`
		Date           time.Time  `json:"date"`
		DateUpdated    *time.Time `json:"date_updated"`
		LiveReceipts   int        `json:"live_receipts"`
		PublishedEvent *struct {
			FirestoreId string `json:"firestore_id"`
		} `json:"published_event"`
	} `json:"occurrences"`
}

// planningQuery reads a series' occurrences together with the count of receipt
// items on each one's published event that represent money actually taken.
//
// "Live" is the definition the protection rule turns on: an item that is still
// pending has not been paid for, a refunded one has been paid back, and an
// abandoned one was never completed. None of those is a reason to keep a slot
// alive. Anything else is.
const planningQuery = `
	SELECT EventSeries {
		series_id,
		form_data,
		repeat_config: {
			repeat_interval,
			repeat_unit,
			selected_days,
			timezone,
			end_type,
			number_of_occurrences,
			end_date
		},
		occurrences: {
			occurrence_id,
			date,
			date_updated,
			published_event: { firestore_id },
			live_receipts := count((
				SELECT .published_event.<event[is ReceiptItem]
				FILTER NOT .pending
				   AND .refund_status != RefundStatus.refunded
				   AND NOT .abandoned
			))
		} ORDER BY .date ASC
	}
	FILTER .series_id = <str>$series_id AND NOT .deleted
	LIMIT 1
`

// loadPlanningView reads the planning view through the given executor, which
// is a transaction for every caller that intends to write. Reading outside the
// transaction that writes is the whole of the concurrent-regenerate bug: two
// requests each read a state neither of them then writes against, and the
// store cannot tell that they conflicted.
func loadPlanningView(ctx context.Context, ex geltypes.Executor, seriesId string) (*planningView, error) {
	var raw []byte
	err := ex.QueryJSON(ctx, planningQuery, &raw,
		map[string]any{"series_id": seriesId})
	if err != nil {
		return nil, fmt.Errorf("failed to load series %s for planning: %w", seriesId, err)
	}

	var rows []planningView
	if err := json.Unmarshal(raw, &rows); err != nil {
		return nil, fmt.Errorf("failed to decode planning view for %s: %w", seriesId, err)
	}
	if len(rows) == 0 {
		return nil, nil
	}
	return &rows[0], nil
}

// config resolves the stored repeat configuration into the engine's form.
func (p *planningView) config() (recurrence.Config, error) {
	if p.RepeatConfg == nil {
		return recurrence.Config{}, fmt.Errorf("series %s has no repeat config", p.SeriesId)
	}

	loc, err := recurrence.LoadLocation(p.RepeatConfg.Timezone)
	if err != nil {
		return recurrence.Config{}, fmt.Errorf(
			"series %s: %w", p.SeriesId, err)
	}

	days := make([]int, 0, len(p.RepeatConfg.SelectedDays))
	for _, d := range p.RepeatConfg.SelectedDays {
		days = append(days, int(d))
	}

	cfg := recurrence.Config{
		Unit:         recurrence.Unit(p.RepeatConfg.RepeatUnit),
		Interval:     int(p.RepeatConfg.RepeatInterval),
		SelectedDays: days,
		Location:     loc,
		EndRule:      recurrence.EndRule(p.RepeatConfg.EndType),
	}
	if p.RepeatConfg.NumberOfOccurrences != nil {
		cfg.Count = int(*p.RepeatConfg.NumberOfOccurrences)
	}
	if p.RepeatConfg.EndDate != nil {
		cfg.EndDate = recurrence.DateIn(*p.RepeatConfg.EndDate, loc)
		cfg.HasEndDate = true
	}
	return cfg, cfg.Validate()
}

// template is the series form data every generated occurrence gets a copy of,
// and the source of the time of day every generated occurrence happens at.
//
// The decode is checked rather than ignored. startTimeOffset lives in here, and
// a silently failed decode reads as a series that runs at midnight -- which is a
// plausible-looking answer, so it would surface as wrong dates rather than as a
// broken read.
func (p *planningView) template() (models.SerializableEventFormData, json.RawMessage, error) {
	raw := unwrapJSON(p.FormData)
	if len(raw) == 0 {
		return models.SerializableEventFormData{}, json.RawMessage("{}"), nil
	}

	var form models.SerializableEventFormData
	if err := json.Unmarshal(raw, &form); err != nil {
		return form, raw, fmt.Errorf(
			"series %s: could not read the form template: %w", p.SeriesId, err)
	}
	return form, raw, nil
}

// unwrapJSON undoes the double encoding Gel applies to a json-typed property
// when a whole row is serialised with QueryJSON. The column's contents come back
// as a JSON *string* holding JSON rather than as a nested object, so decoding
// the row once leaves the template still encoded. Anything that is already an
// object is returned untouched, so this is safe whichever way the driver
// presents it.
func unwrapJSON(raw json.RawMessage) json.RawMessage {
	trimmed := bytes.TrimSpace(raw)
	if len(trimmed) == 0 || trimmed[0] != '"' {
		return raw
	}
	var inner string
	if err := json.Unmarshal(trimmed, &inner); err != nil {
		return raw
	}
	return json.RawMessage(inner)
}

// rows presents the stored occurrences to the recurrence engine.
func (p *planningView) rows() []recurrence.Existing {
	out := make([]recurrence.Existing, 0, len(p.Occurrences))
	for _, occ := range p.Occurrences {
		row := recurrence.Existing{
			Id:           occ.OccurrenceId,
			Instant:      occ.Date,
			Edited:       occ.DateUpdated != nil,
			LiveReceipts: occ.LiveReceipts,
		}
		if occ.PublishedEvent != nil {
			row.PublishedEvent = occ.PublishedEvent.FirestoreId
		}
		out = append(out, row)
	}
	return out
}

// soldOccurrence reports whether one occurrence's published event has taken
// money, which is what makes it undeletable.
func (p *planningView) soldOccurrence(occurrenceId string) bool {
	for _, row := range p.rows() {
		if row.Id == occurrenceId {
			return row.Sold()
		}
	}
	return false
}
