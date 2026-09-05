package models

import (
	"encoding/json"
	"fmt"
	"ExampleCo-core/internal/v2/models/recurrence"
	"strconv"
	"time"

	"github.com/google/uuid"
)

// EventSeriesRepeatUnit defines the repeat interval unit
type EventSeriesRepeatUnit string

const (
	EventSeriesRepeatUnitDay   EventSeriesRepeatUnit = "day"
	EventSeriesRepeatUnitWeek  EventSeriesRepeatUnit = "week"
	EventSeriesRepeatUnitMonth EventSeriesRepeatUnit = "month"
)

// EventSeriesEndType defines how a series should end
type EventSeriesEndType string

const (
	EventSeriesEndTypeAfterOccurrences EventSeriesEndType = "afterOccurrences"
	EventSeriesEndTypeOnDate           EventSeriesEndType = "onDate"
)

// OccurrenceEditScope names how far an edit to one occurrence reaches.
type OccurrenceEditScope string

const (
	// OccurrenceEditScopeThisEvent edits only the occurrence named in the
	// request. This is the default when a request carries no scope.
	OccurrenceEditScopeThisEvent OccurrenceEditScope = "thisEvent"
	// OccurrenceEditScopeThisAndFollowing edits that occurrence and every
	// occurrence of the series that is not before it.
	OccurrenceEditScopeThisAndFollowing OccurrenceEditScope = "thisAndFollowing"
)

// Valid reports whether the scope is one the API accepts.
func (s OccurrenceEditScope) Valid() bool {
	switch s {
	case OccurrenceEditScopeThisEvent, OccurrenceEditScopeThisAndFollowing:
		return true
	}
	return false
}

// EventSeriesRepeatConfig defines the repeat configuration for a series
type EventSeriesRepeatConfig struct {
	RepeatInterval      int                   `json:"repeatInterval" firestore:"repeatInterval"`           // e.g., 1 for every day/week/month
	RepeatUnit          EventSeriesRepeatUnit `json:"repeatUnit" firestore:"repeatUnit"`                   // day, week, month
	SelectedDays        []int                 `json:"selectedDays" firestore:"selectedDays"`               // 0-6 for days of week (Sunday=0)
	Timezone            string                `json:"timezone" firestore:"timezone"`                       // IANA zone name the recurrence is expressed in
	EndType             EventSeriesEndType    `json:"endType" firestore:"endType"`                         // afterOccurrences or onDate
	NumberOfOccurrences *int                  `json:"numberOfOccurrences" firestore:"numberOfOccurrences"` // used if endType is afterOccurrences
	EndDate             *int                  `json:"endDate" firestore:"endDate"`                         // used if endType is onDate (Unix timestamp)
}

// Location resolves the series timezone. A config with no zone name is read as
// UTC, which is what the database column defaults to.
func (c EventSeriesRepeatConfig) Location() (*time.Location, error) {
	name := c.Timezone
	if name == "" {
		name = "UTC"
	}
	return time.LoadLocation(name)
}

// EventSeriesOccurrence represents a single occurrence in a series
type EventSeriesOccurrence struct {
	Id               string                     `json:"id" firestore:"id"`
	Date             int                        `json:"date" firestore:"date"`                         // Unix timestamp
	PublishedEventId *string                    `json:"publishedEventId" firestore:"publishedEventId"` // nil if not yet published
	FormData         *SerializableEventFormData `json:"formData" firestore:"formData"`                 // individual occurrence form data
	DateCreated      int                        `json:"dateCreated" firestore:"dateCreated"`           // Unix timestamp
	DateUpdated      *int                       `json:"dateUpdated" firestore:"dateUpdated"`           // Unix timestamp
}

// SerializableEventFormData contains the event form data that can be reused across occurrences
// This is stored as JSON and contains the event creation form data
type SerializableEventFormData struct {
	Name        string           `json:"name"`
	Description string           `json:"description"`
	PublicLink  *string          `json:"publicLink,omitempty"`
	VideoUrl    *string          `json:"videoUrl,omitempty"`
	Gallery     []StorageItem    `json:"gallery,omitempty"`
	Visibility  EventVisibility  `json:"visibility"`
	Location    Location         `json:"location"`
	MusicTrack  *EventMusicTrack `json:"musicTrack,omitempty"`
	EventType   EventType        `json:"eventType"`
	Color       Color            `json:"color"`
	Effect      EventEffect      `json:"effect"`
	Settings    EventSettings    `json:"settings"`
	Tickets     []Ticket         `json:"tickets"`
	// Time fields - relative to occurrence date
	StartTimeOffset int  `json:"startTimeOffset"` // Seconds from midnight on the occurrence date
	EndTimeOffset   *int `json:"endTimeOffset"`   // Seconds from midnight on the occurrence date
}

// UnmarshalJSON implements custom JSON unmarshaling for SerializableEventFormData.
// It handles the iOS client's flat format and converts it to the expected nested format.
func (s *SerializableEventFormData) UnmarshalJSON(data []byte) error {
	// First, try standard unmarshaling (for correctly formatted requests)
	type SerializableEventFormDataAlias SerializableEventFormData
	alias := (*SerializableEventFormDataAlias)(s)

	// Try to unmarshal directly first
	if err := json.Unmarshal(data, alias); err == nil {
		return nil
	}

	// If that fails, parse as raw map to handle client's flat format
	var raw map[string]json.RawMessage
	if err := json.Unmarshal(data, &raw); err != nil {
		return err
	}

	// Parse simple string/pointer fields
	if v, ok := raw["name"]; ok {
		json.Unmarshal(v, &s.Name)
	}
	if v, ok := raw["description"]; ok {
		json.Unmarshal(v, &s.Description)
	}
	if v, ok := raw["publicLink"]; ok {
		json.Unmarshal(v, &s.PublicLink)
	}
	if v, ok := raw["addVideo"]; ok {
		json.Unmarshal(v, &s.VideoUrl)
	}
	if v, ok := raw["videoUrl"]; ok {
		json.Unmarshal(v, &s.VideoUrl)
	}
	if v, ok := raw["location"]; ok {
		json.Unmarshal(v, &s.Location)
	}
	if v, ok := raw["musicTrack"]; ok {
		json.Unmarshal(v, &s.MusicTrack)
	}
	if v, ok := raw["gallery"]; ok {
		json.Unmarshal(v, &s.Gallery)
	}
	if v, ok := raw["eventType"]; ok {
		json.Unmarshal(v, &s.EventType)
	}
	if v, ok := raw["type"]; ok {
		json.Unmarshal(v, &s.EventType)
	}
	if v, ok := raw["color"]; ok {
		json.Unmarshal(v, &s.Color)
	}
	if v, ok := raw["accentColor"]; ok {
		json.Unmarshal(v, &s.Color)
	}
	if v, ok := raw["effect"]; ok {
		json.Unmarshal(v, &s.Effect)
	}
	if v, ok := raw["startTimeOffset"]; ok {
		json.Unmarshal(v, &s.StartTimeOffset)
	}
	if v, ok := raw["endTimeOffset"]; ok {
		json.Unmarshal(v, &s.EndTimeOffset)
	}

	// Handle visibility - can be string or object
	if v, ok := raw["visibility"]; ok {
		// Try as object first
		var visObj EventVisibility
		if err := json.Unmarshal(v, &visObj); err == nil {
			s.Visibility = visObj
		} else {
			// Try as string
			var visStr string
			if err := json.Unmarshal(v, &visStr); err == nil {
				s.Visibility = EventVisibility{
					ShowToPublic:  visStr == "public",
					ShowToFriends: false,
					ShowToCampus:  nil,
				}
			}
		}
	}
	// Override with explicit fields if present
	if v, ok := raw["showToFriends"]; ok {
		json.Unmarshal(v, &s.Visibility.ShowToFriends)
	}
	if v, ok := raw["showToCampus"]; ok {
		// Can be bool or string
		var boolVal bool
		if err := json.Unmarshal(v, &boolVal); err == nil {
			if boolVal {
				campus := "true"
				s.Visibility.ShowToCampus = &campus
			}
		} else {
			var strVal string
			if err := json.Unmarshal(v, &strVal); err == nil && strVal != "" {
				s.Visibility.ShowToCampus = &strVal
			}
		}
	}

	// Handle settings - can be nested object or flat fields
	if v, ok := raw["settings"]; ok {
		json.Unmarshal(v, &s.Settings)
	}
	// Override with flat fields if present
	if v, ok := raw["legalAge"]; ok {
		json.Unmarshal(v, &s.Settings.LegalAge)
	}
	if v, ok := raw["validIdRequired"]; ok {
		json.Unmarshal(v, &s.Settings.RequireValidId)
	}
	if v, ok := raw["studentIdRequired"]; ok {
		json.Unmarshal(v, &s.Settings.RequireStudentId)
	}
	if v, ok := raw["hostCoversFee"]; ok {
		json.Unmarshal(v, &s.Settings.HostCoversFee)
	}
	if v, ok := raw["allowSharing"]; ok {
		json.Unmarshal(v, &s.Settings.AllowSharing)
	}
	if v, ok := raw["restrictMultipleRsvpToOrganization"]; ok {
		json.Unmarshal(v, &s.Settings.RestrictMultipleRsvpToOrganization)
	}
	if v, ok := raw["eventChatOption"]; ok {
		var chatOpt string
		if json.Unmarshal(v, &chatOpt) == nil {
			s.Settings.ChatVisibility = EventChatVisibility(chatOpt)
		}
	}
	if v, ok := raw["showGuestList"]; ok {
		var guestListOpt string
		if json.Unmarshal(v, &guestListOpt) == nil {
			s.Settings.HideGuestListOption = HideGuestListOption(guestListOpt)
		}
	}
	if v, ok := raw["showGuestCount"]; ok {
		var showCount bool
		if json.Unmarshal(v, &showCount) == nil {
			s.Settings.HideGuestListCount = !showCount
		}
	}
	if v, ok := raw["numSpots"]; ok {
		// Can be string or int
		var intVal int
		if json.Unmarshal(v, &intVal) == nil && intVal > 0 {
			s.Settings.MaxTicketsPerUser = intVal
		} else {
			var strVal string
			if json.Unmarshal(v, &strVal) == nil && strVal != "" {
				if parsed, err := strconv.Atoi(strVal); err == nil {
					s.Settings.MaxTicketsPerUser = parsed
				}
			}
		}
	}

	// Handle tickets with custom parsing for price/capacity/maxPerUser as string
	if v, ok := raw["tickets"]; ok {
		s.Tickets = parseTicketsFromRaw(v)
	}

	return nil
}

// parseTicketsFromRaw parses tickets handling string values for numeric fields
func parseTicketsFromRaw(data json.RawMessage) []Ticket {
	var rawTickets []map[string]json.RawMessage
	if err := json.Unmarshal(data, &rawTickets); err != nil {
		return nil
	}

	tickets := make([]Ticket, 0, len(rawTickets))
	for _, raw := range rawTickets {
		var t Ticket

		if v, ok := raw["id"]; ok {
			json.Unmarshal(v, &t.Id)
		}
		if v, ok := raw["name"]; ok {
			json.Unmarshal(v, &t.Name)
		}
		if v, ok := raw["description"]; ok {
			json.Unmarshal(v, &t.Description)
		}
		if v, ok := raw["hide"]; ok {
			json.Unmarshal(v, &t.Hide)
		}
		if v, ok := raw["hidden"]; ok {
			json.Unmarshal(v, &t.Hidden)
		}
		if v, ok := raw["disabled"]; ok {
			json.Unmarshal(v, &t.Disabled)
		}
		if v, ok := raw["inPersonOnly"]; ok {
			json.Unmarshal(v, &t.InPersonOnly)
		}
		if v, ok := raw["order"]; ok {
			json.Unmarshal(v, &t.Order)
		}
		if v, ok := raw["sold"]; ok {
			json.Unmarshal(v, &t.Sold)
		}
		if v, ok := raw["dateOpen"]; ok {
			json.Unmarshal(v, &t.DateOpen)
		}
		if v, ok := raw["dateExpire"]; ok {
			json.Unmarshal(v, &t.DateExpire)
		}
		if v, ok := raw["groupRestriction"]; ok {
			json.Unmarshal(v, &t.GroupRestriction)
		}

		// Parse price - can be string or int
		if v, ok := raw["price"]; ok {
			t.Price = parseIntOrString(v)
		}

		// Parse capacity - can be string or int
		if v, ok := raw["capacity"]; ok {
			if cap := parseIntOrStringPtr(v); cap != nil {
				t.Capacity = cap
			}
		}

		// Parse maxPerUser - can be string or int
		if v, ok := raw["maxPerUser"]; ok {
			if maxPer := parseIntOrStringPtr(v); maxPer != nil {
				t.MaxPerUser = maxPer
			}
		}

		// Parse colors/style
		if v, ok := raw["colors"]; ok {
			json.Unmarshal(v, &t.Colors)
		}
		if v, ok := raw["style"]; ok {
			var styles []string
			if json.Unmarshal(v, &styles) == nil {
				t.Colors = make([]Color, len(styles))
				for i, s := range styles {
					t.Colors[i] = Color(s)
				}
			}
		}

		// Parse settings
		if v, ok := raw["settings"]; ok {
			json.Unmarshal(v, &t.Settings)
		}
		// Handle flat settings fields
		if v, ok := raw["requireGuestApproval"]; ok {
			json.Unmarshal(v, &t.Settings.ApprovalRequired)
		}
		if v, ok := raw["restrictedOrganizations"]; ok {
			json.Unmarshal(v, &t.Settings.OrganizationRestrictions)
		}
		if v, ok := raw["displayAsField"]; ok {
			var displayType string
			if json.Unmarshal(v, &displayType) == nil {
				t.Settings.SalesDisplayType = SalesDisplayType(displayType)
			}
		}
		if v, ok := raw["ticketSalesVisibility"]; ok {
			var visibility bool
			if json.Unmarshal(v, &visibility) == nil {
				t.Settings.SalesVisibility = &visibility
			}
		}

		tickets = append(tickets, t)
	}

	return tickets
}

// parseIntOrString parses a JSON value that can be either int or string
func parseIntOrString(data json.RawMessage) int {
	var intVal int
	if json.Unmarshal(data, &intVal) == nil {
		return intVal
	}
	var strVal string
	if json.Unmarshal(data, &strVal) == nil && strVal != "" {
		if parsed, err := strconv.Atoi(strVal); err == nil {
			return parsed
		}
	}
	return 0
}

// parseIntOrStringPtr parses a JSON value that can be either int or string, returns nil for empty/zero
func parseIntOrStringPtr(data json.RawMessage) *int {
	var intVal int
	if json.Unmarshal(data, &intVal) == nil {
		if intVal == 0 {
			return nil
		}
		return &intVal
	}
	var strVal string
	if json.Unmarshal(data, &strVal) == nil && strVal != "" {
		if parsed, err := strconv.Atoi(strVal); err == nil {
			if parsed == 0 {
				return nil
			}
			return &parsed
		}
	}
	return nil
}

// EventSeries represents a series of recurring events
type EventSeries struct {
	Id             string                    `json:"id" firestore:"id"`
	OrganizationId string                    `json:"organizationId" firestore:"organizationId"`
	Name           string                    `json:"name" firestore:"name"`
	Description    string                    `json:"description" firestore:"description"`
	DateCreated    int                       `json:"dateCreated" firestore:"dateCreated"` // Unix timestamp
	DateUpdated    *int                      `json:"dateUpdated" firestore:"dateUpdated"` // Unix timestamp
	FormData       SerializableEventFormData `json:"formData" firestore:"formData"`
	FlyerURL       *string                   `json:"flyerURL" firestore:"flyerURL"`
	RepeatConfig   EventSeriesRepeatConfig   `json:"repeatConfig" firestore:"repeatConfig"`
	Occurrences    []EventSeriesOccurrence   `json:"occurrences" firestore:"occurrences"`
}

// NewEventSeriesConfig is used when creating a new event series
type NewEventSeriesConfig struct {
	OrganizationId string
	Name           string
	Description    string
	FormData       SerializableEventFormData
	FlyerURL       *string
	RepeatConfig   EventSeriesRepeatConfig
}

// NewEventSeries creates a new EventSeries with generated ID and timestamps
func NewEventSeries(cfg NewEventSeriesConfig) EventSeries {
	return EventSeries{
		Id:             uuid.New().String(),
		OrganizationId: cfg.OrganizationId,
		Name:           cfg.Name,
		Description:    cfg.Description,
		DateCreated:    int(time.Now().Unix()),
		DateUpdated:    nil,
		FormData:       cfg.FormData,
		FlyerURL:       cfg.FlyerURL,
		RepeatConfig:   cfg.RepeatConfig,
		Occurrences:    []EventSeriesOccurrence{},
	}
}

// RecurrenceConfig resolves the stored repeat configuration into the form the
// recurrence engine works in: a loaded zone rather than a zone name, and a
// local calendar date rather than a timestamp for the end date.
//
// Resolving the end date here rather than inside the engine is deliberate.
// endDate is stored as an instant, but a series ends on a *day*, and which day
// an instant belongs to is a question about the series' zone. Answering it once,
// at the boundary, keeps the engine free of timestamps entirely.
func (s *EventSeries) RecurrenceConfig() (recurrence.Config, error) {
	loc, err := recurrence.LoadLocation(s.RepeatConfig.Timezone)
	if err != nil {
		return recurrence.Config{}, fmt.Errorf(
			"event series %s: %w", s.Id, err)
	}

	cfg := recurrence.Config{
		Unit:         recurrence.Unit(s.RepeatConfig.RepeatUnit),
		Interval:     s.RepeatConfig.RepeatInterval,
		SelectedDays: s.RepeatConfig.SelectedDays,
		Location:     loc,
		EndRule:      recurrence.EndRule(s.RepeatConfig.EndType),
	}
	if s.RepeatConfig.NumberOfOccurrences != nil {
		cfg.Count = *s.RepeatConfig.NumberOfOccurrences
	}
	if s.RepeatConfig.EndDate != nil {
		end := time.Unix(int64(*s.RepeatConfig.EndDate), 0)
		cfg.EndDate = recurrence.DateIn(end, loc)
		cfg.HasEndDate = true
	}
	return cfg, cfg.Validate()
}

// StartTimeOffset is the time of day every occurrence in the series happens
// at, as seconds after local midnight on the occurrence's own date. Reading it
// off the series template rather than off the start instant is what keeps the
// wall-clock time constant across an offset change: an occurrence is "seven in
// the evening, locally", not "an instant a fixed number of hours from the last
// one".
func (s *EventSeries) StartTimeOffset() int {
	return s.FormData.StartTimeOffset
}

// RecurrenceRows presents the stored occurrences to the recurrence engine.
// Publication and edit state travel with them; form data does not, because
// nothing about which slots survive depends on it.
func (s *EventSeries) RecurrenceRows() []recurrence.Existing {
	rows := make([]recurrence.Existing, 0, len(s.Occurrences))
	for _, occ := range s.Occurrences {
		row := recurrence.Existing{
			Id:      occ.Id,
			Instant: time.Unix(int64(occ.Date), 0),
			Edited:  occ.DateUpdated != nil,
		}
		if occ.PublishedEventId != nil {
			row.PublishedEvent = *occ.PublishedEventId
		}
		rows = append(rows, row)
	}
	return rows
}

// GenerateOccurrences replaces the series' occurrence list with the slots that
// its repeat config describes, taking startDate as the first candidate slot.
//
// startDate contributes only its calendar date in the series' zone. The time of
// day comes from the series template, so a series created at half past four in
// the afternoon still runs at seven in the evening.
func (s *EventSeries) GenerateOccurrences(startDate time.Time) {
	s.Occurrences = []EventSeriesOccurrence{}

	cfg, err := s.RecurrenceConfig()
	if err != nil {
		return
	}
	slots, err := recurrence.Slots(cfg, recurrence.DateIn(startDate, cfg.Location),
		s.StartTimeOffset())
	if err != nil {
		return
	}

	s.Occurrences = s.occurrencesFor(slots)
}

// ExtendOccurrences continues the series by additionalCount further slots,
// appending them to Occurrences and returning the ones it added.
//
// The continuation is measured from the series' own earliest occurrence, not
// from its latest one and not from today. Those give the same answer for a
// daily series and different answers for a monthly one that has been clamped
// into a short month. What it adds is the first additionalCount dates of that
// sequence the series does not already hold, so a gap left in the middle is
// filled before anything is appended past the end.
func (s *EventSeries) ExtendOccurrences(additionalCount int) []EventSeriesOccurrence {
	cfg, err := s.RecurrenceConfig()
	if err != nil {
		return nil
	}
	slots, err := recurrence.PlanExtend(cfg, s.RecurrenceRows(), additionalCount,
		s.StartTimeOffset())
	if err != nil {
		return nil
	}

	added := s.occurrencesFor(slots)
	s.Occurrences = append(s.Occurrences, added...)
	return added
}

// occurrencesFor turns generated slots into occurrence rows. Each one carries
// its own copy of the series template, which is what makes a later individual
// edit possible without disturbing the series or its siblings.
func (s *EventSeries) occurrencesFor(slots []recurrence.Slot) []EventSeriesOccurrence {
	now := int(time.Now().Unix())
	out := make([]EventSeriesOccurrence, 0, len(slots))
	for _, slot := range slots {
		formData := s.FormData
		out = append(out, EventSeriesOccurrence{
			Id:          uuid.New().String(),
			Date:        int(slot.Instant.Unix()),
			FormData:    &formData,
			DateCreated: now,
		})
	}
	return out
}

// RemoveOccurrence removes an occurrence by ID
func (s *EventSeries) RemoveOccurrence(occurrenceId string) bool {
	for i, occ := range s.Occurrences {
		if occ.Id == occurrenceId {
			s.Occurrences = append(s.Occurrences[:i], s.Occurrences[i+1:]...)
			return true
		}
	}
	return false
}

// MarkOccurrencePublished marks an occurrence as published with the given event ID
func (s *EventSeries) MarkOccurrencePublished(occurrenceId, eventId string) bool {
	for i, occ := range s.Occurrences {
		if occ.Id == occurrenceId {
			now := int(time.Now().Unix())
			s.Occurrences[i].PublishedEventId = &eventId
			s.Occurrences[i].DateUpdated = &now
			return true
		}
	}
	return false
}

// GetOccurrence returns an occurrence by ID
func (s *EventSeries) GetOccurrence(occurrenceId string) *EventSeriesOccurrence {
	for _, occ := range s.Occurrences {
		if occ.Id == occurrenceId {
			return &occ
		}
	}
	return nil
}

// EventBasic contains minimal event info for series display
type EventBasic struct {
	Id        string      `json:"id"`
	Name      string      `json:"name"`
	Flyer     StorageItem `json:"flyer"`
	DateStart int         `json:"dateStart"` // Unix timestamp
}

// EventSeriesInfo contains series information for event page extension
type EventSeriesInfo struct {
	Id          string       `json:"id"`
	Name        string       `json:"name"`
	Description string       `json:"description"`
	OtherEvents []EventBasic `json:"otherEvents"` // All other published events in series (past + future)
}
