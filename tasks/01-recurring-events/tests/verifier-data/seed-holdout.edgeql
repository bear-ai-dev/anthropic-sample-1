# The graded subjects. Applied by test.sh after the shipped fixture, from the
# tests tree the harness mounts only while grading, so none of it is in the
# image and none of these identifiers appears in the sandbox.
#
# What the sandbox keeps is the evidence: the read-only zone exemplars, and one
# series with published and paid occurrences on it. What lives here is the set
# of series the rules actually drive. A solver can therefore learn every
# convention from the box and still not be able to run a graded scenario, which
# is the distinction the round is built on -- a rule must be derivable, not
# rehearsable.
#
# The props are shared with the sandbox deliberately: receipt items cannot be
# created through the API, so a graded scenario that needs a paid occurrence has
# to publish onto one of the fixture's events. An event is a prop, not a
# scenario.

# hs-guard-a: Chicago, Mondays at 20:00, four from 2 March 2026. Two published.
insert EventSeries {
  series_id := 'hs-guard-a',
  organization := assert_single((select Organization filter .firestore_id = 'org-series-001')),
  name := 'Monday Nights',
  description := 'Monday nights',
  form_data := <json>'{"name":"Monday Nights","description":"weekly","startTimeOffset":72000,"visibility":{"showToPublic":true,"showToFriends":false},"eventType":"party","color":"blue","effect":"none","settings":{},"tickets":[],"location":{}}',
  repeat_config := (insert EventSeriesRepeatConfig {
    repeat_interval := 1,
    repeat_unit := EventSeriesRepeatUnit.week,
    selected_days := [1],
    timezone := 'America/Chicago',
    end_type := EventSeriesEndType.afterOccurrences,
    number_of_occurrences := 4
  })
};

# hs-hand-a: Denver, Tuesdays at 18:00, four from 3 March 2026.
insert EventSeries {
  series_id := 'hs-hand-a',
  organization := assert_single((select Organization filter .firestore_id = 'org-series-001')),
  name := 'Tuesday Nights',
  description := 'Tuesday nights',
  form_data := <json>'{"name":"Tuesday Nights","description":"weekly","startTimeOffset":64800,"visibility":{"showToPublic":true,"showToFriends":false},"eventType":"party","color":"green","effect":"none","settings":{},"tickets":[],"location":{}}',
  repeat_config := (insert EventSeriesRepeatConfig {
    repeat_interval := 1,
    repeat_unit := EventSeriesRepeatUnit.week,
    selected_days := [2],
    timezone := 'America/Denver',
    end_type := EventSeriesEndType.afterOccurrences,
    number_of_occurrences := 4
  })
};

# hs-anchor-a: New York, monthly from 31 January 2026 at 19:00, stopping after
# two.
insert EventSeries {
  series_id := 'hs-anchor-a',
  organization := assert_single((select Organization filter .firestore_id = 'org-series-001')),
  name := 'Month End Series',
  description := 'monthly, month end',
  form_data := <json>'{"name":"Month End Series","description":"monthly","startTimeOffset":68400,"visibility":{"showToPublic":true,"showToFriends":false},"eventType":"party","color":"red","effect":"none","settings":{},"tickets":[],"location":{}}',
  repeat_config := (insert EventSeriesRepeatConfig {
    repeat_interval := 1,
    repeat_unit := EventSeriesRepeatUnit.month,
    selected_days := <array<int32>>[],
    timezone := 'America/New_York',
    end_type := EventSeriesEndType.afterOccurrences,
    number_of_occurrences := 2
  })
};

# hs-vacant-a: New York, Fridays at 20:00, stopping after four, holding three.
insert EventSeries {
  series_id := 'hs-vacant-a',
  organization := assert_single((select Organization filter .firestore_id = 'org-series-001')),
  name := 'Friday Nights',
  description := 'Friday nights',
  form_data := <json>'{"name":"Friday Nights","description":"weekly","startTimeOffset":72000,"visibility":{"showToPublic":true,"showToFriends":false},"eventType":"party","color":"pink","effect":"none","settings":{},"tickets":[],"location":{}}',
  repeat_config := (insert EventSeriesRepeatConfig {
    repeat_interval := 1,
    repeat_unit := EventSeriesRepeatUnit.week,
    selected_days := [5],
    timezone := 'America/New_York',
    end_type := EventSeriesEndType.afterOccurrences,
    number_of_occurrences := 4
  })
};

# hs-reach-a: Chicago, Thursdays at 19:00, five from 2 April 2026, two of them
# published.
insert EventSeries {
  series_id := 'hs-reach-a',
  organization := assert_single((select Organization filter .firestore_id = 'org-series-001')),
  name := 'Thursday Nights',
  description := 'Thursday nights',
  form_data := <json>'{"name":"Thursday Nights","description":"weekly","startTimeOffset":68400,"visibility":{"showToPublic":true,"showToFriends":false},"eventType":"party","color":"yellow","effect":"none","settings":{},"tickets":[],"location":{}}',
  repeat_config := (insert EventSeriesRepeatConfig {
    repeat_interval := 1,
    repeat_unit := EventSeriesRepeatUnit.week,
    selected_days := [4],
    timezone := 'America/Chicago',
    end_type := EventSeriesEndType.afterOccurrences,
    number_of_occurrences := 5
  })
};

# hs-contend-a: Berlin, daily at 21:00, five from 2 March 2026.
insert EventSeries {
  series_id := 'hs-contend-a',
  organization := assert_single((select Organization filter .firestore_id = 'org-series-001')),
  name := 'Daily Berlin',
  description := 'daily',
  form_data := <json>'{"name":"Daily Berlin","description":"daily","startTimeOffset":75600,"visibility":{"showToPublic":true,"showToFriends":false},"eventType":"party","color":"purple","effect":"none","settings":{},"tickets":[],"location":{}}',
  repeat_config := (insert EventSeriesRepeatConfig {
    repeat_interval := 1,
    repeat_unit := EventSeriesRepeatUnit.day,
    selected_days := <array<int32>>[],
    timezone := 'Europe/Berlin',
    end_type := EventSeriesEndType.afterOccurrences,
    number_of_occurrences := 5
  })
};

# (series_id, occurrence_id, instant)
for o in {
  ('hs-guard-a', 'ho-guard-1', <datetime>'2026-03-03T02:00:00Z'),
  ('hs-guard-a', 'ho-guard-2', <datetime>'2026-03-10T01:00:00Z'),
  ('hs-guard-a', 'ho-guard-3', <datetime>'2026-03-17T01:00:00Z'),
  ('hs-guard-a', 'ho-guard-4', <datetime>'2026-03-24T01:00:00Z'),

  ('hs-hand-a', 'ho-hand-1', <datetime>'2026-03-04T01:00:00Z'),
  ('hs-hand-a', 'ho-hand-2', <datetime>'2026-03-11T00:00:00Z'),
  ('hs-hand-a', 'ho-hand-3', <datetime>'2026-03-18T00:00:00Z'),
  ('hs-hand-a', 'ho-hand-4', <datetime>'2026-03-25T00:00:00Z'),

  ('hs-anchor-a', 'ho-anchor-1', <datetime>'2026-02-01T00:00:00Z'),
  ('hs-anchor-a', 'ho-anchor-2', <datetime>'2026-03-01T00:00:00Z'),

  ('hs-vacant-a', 'ho-vacant-1', <datetime>'2026-05-02T00:00:00Z'),
  ('hs-vacant-a', 'ho-vacant-3', <datetime>'2026-05-16T00:00:00Z'),
  ('hs-vacant-a', 'ho-vacant-4', <datetime>'2026-05-23T00:00:00Z'),

  ('hs-reach-a', 'ho-reach-1', <datetime>'2026-04-03T00:00:00Z'),
  ('hs-reach-a', 'ho-reach-2', <datetime>'2026-04-10T00:00:00Z'),
  ('hs-reach-a', 'ho-reach-3', <datetime>'2026-04-17T00:00:00Z'),
  ('hs-reach-a', 'ho-reach-4', <datetime>'2026-04-24T00:00:00Z'),
  ('hs-reach-a', 'ho-reach-5', <datetime>'2026-05-01T00:00:00Z'),

  ('hs-contend-a', 'ho-contend-1', <datetime>'2026-03-02T20:00:00Z'),
  ('hs-contend-a', 'ho-contend-2', <datetime>'2026-03-03T20:00:00Z'),
  ('hs-contend-a', 'ho-contend-3', <datetime>'2026-03-04T20:00:00Z'),
  ('hs-contend-a', 'ho-contend-4', <datetime>'2026-03-05T20:00:00Z'),
  ('hs-contend-a', 'ho-contend-5', <datetime>'2026-03-06T20:00:00Z')
} union (
  update EventSeries filter .series_id = o.0
  set {
    occurrences += (insert EventSeriesOccurrence {
      occurrence_id := o.1,
      date := o.2,
      date_created := <datetime>'2026-02-01T12:00:00Z'
    })
  }
);

# Give every occurrence its own copy of its series' template.
for s in {
  ('hs-guard-a',   'ho-guard-'),
  ('hs-hand-a',    'ho-hand-'),
  ('hs-anchor-a',  'ho-anchor-'),
  ('hs-vacant-a',  'ho-vacant-'),
  ('hs-reach-a',   'ho-reach-'),
  ('hs-contend-a', 'ho-contend-')
} union (
  update EventSeriesOccurrence
  filter .occurrence_id like s.1 ++ '%'
  set {
    form_data := assert_single((
      select EventSeries { form_data } filter .series_id = s.0
    )).form_data
  }
);

# Publication. Publishing stamps date_updated, so these rows carry one.
# (occurrence, event)
for p in {
  ('ho-guard-1', 'evt-published-001'),
  ('ho-guard-2', 'evt-published-002'),
  ('ho-reach-3', 'evt-published-004'),
  # -002 is published and has taken nothing: three receipt items, one still
  # pending, one refunded, one abandoned. It is here so that the scope subject
  # holds a published occurrence the edit must still move, beside the one at
  # -004 that it must step over.
  ('ho-reach-4', 'evt-published-002')
} union (
  update EventSeriesOccurrence filter .occurrence_id = p.0
  set {
    published_event := assert_single((select Event filter .firestore_id = p.1)),
    date_updated := <datetime>'2026-03-02T12:00:00Z'
  }
);
