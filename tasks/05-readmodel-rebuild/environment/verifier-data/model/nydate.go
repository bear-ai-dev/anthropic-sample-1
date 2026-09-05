package main

// The New York calendar date of an instant, worked out from the rule rather
// than looked up.
//
// Since 2007 the United States moves to daylight time at 02:00 local standard
// time on the second Sunday in March, and back at 02:00 local daylight time on
// the first Sunday in November. In UTC terms that is 07:00 on the March Sunday
// and 06:00 on the November Sunday. Outside that window the offset is -05:00;
// inside it, -04:00.
//
// `selfCheck` compares this against the tzdata embedded in the binary over a
// dense grid of instants. Two implementations that agree is the point; if they
// ever stop agreeing the verifier refuses to grade rather than picking one.

import (
	"fmt"
	"time"
	_ "time/tzdata"
)

func nthWeekdayUTC(year int, month time.Month, weekday time.Weekday, n int, hourUTC int) time.Time {
	d := time.Date(year, month, 1, hourUTC, 0, 0, 0, time.UTC)
	offset := (int(weekday) - int(d.Weekday()) + 7) % 7
	return d.AddDate(0, 0, offset+7*(n-1))
}

func newYorkOffsetSeconds(t time.Time) int {
	t = t.UTC()
	year := t.Year()
	dstStart := nthWeekdayUTC(year, time.March, time.Sunday, 2, 7)
	dstEnd := nthWeekdayUTC(year, time.November, time.Sunday, 1, 6)
	if !t.Before(dstStart) && t.Before(dstEnd) {
		return -4 * 3600
	}
	return -5 * 3600
}

// NewYorkDate returns the YYYY-MM-DD New York local date of an instant.
func NewYorkDate(t time.Time) string {
	shifted := t.UTC().Add(time.Duration(newYorkOffsetSeconds(t)) * time.Second)
	return fmt.Sprintf("%04d-%02d-%02d", shifted.Year(), int(shifted.Month()), shifted.Day())
}

// UTCDate is generation v1's bucket, kept only so the verifier can tell the two
// apart when it needs to know which generation answered.
func UTCDate(t time.Time) string {
	u := t.UTC()
	return fmt.Sprintf("%04d-%02d-%02d", u.Year(), int(u.Month()), u.Day())
}

func selfCheck() error {
	loc, err := time.LoadLocation("America/New_York")
	if err != nil {
		return fmt.Errorf("tzdata unavailable: %w", err)
	}
	for year := 2024; year <= 2026; year++ {
		t := time.Date(year, 1, 1, 0, 0, 0, 0, time.UTC)
		end := time.Date(year+1, 1, 1, 0, 0, 0, 0, time.UTC)
		for t.Before(end) {
			mine := NewYorkDate(t)
			theirs := t.In(loc).Format("2006-01-02")
			if mine != theirs {
				return fmt.Errorf("day-bucket rule disagrees with tzdata at %s: rule=%s tzdata=%s",
					t.Format(time.RFC3339), mine, theirs)
			}
			t = t.Add(37 * time.Minute)
		}
	}
	return nil
}
