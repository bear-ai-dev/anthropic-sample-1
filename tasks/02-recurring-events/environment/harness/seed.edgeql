# Development fixture for the event-series API. Applied after reset.edgeql.
#
# Seven series across six zones, one of them with every occurrence published,
# and the receipt items behind those publications. Occurrences are stored as
# instants; which local date and time of day an instant corresponds to depends
# on that series' zone and on the form data stored against the row.

insert User {
  firestore_id := 'usr-series-mgr', name := 'Series Manager',
  description := 'organisation owner', display_name := 'Series Manager',
  bio := '', birthdate := <datetime>'1990-01-01T00:00:00Z',
  date_joined := <datetime>'2024-01-01T00:00:00Z'
};
insert User {
  firestore_id := 'usr-series-outsider', name := 'Outsider',
  description := 'no membership', display_name := 'Outsider',
  bio := '', birthdate := <datetime>'1991-01-01T00:00:00Z',
  date_joined := <datetime>'2024-01-01T00:00:00Z'
};

insert Organization {
  firestore_id := 'org-series-001',
  name := 'Series Test Organisation',
  description := 'owns every series in this fixture',
  approval_required := false,
  is_verified := true,
  deleted := false
};

insert UserOrganization {
  firestore_id := 'uorg-series-mgr',
  org_privilege := UserOrgPriv.owner,
  user := assert_single((select User filter .firestore_id = 'usr-series-mgr')),
  organization := assert_single((select Organization filter .firestore_id = 'org-series-001'))
};

insert EventTicket {
  firestore_id := 'tkt-series-general', capacity := 200,
  description := 'General admission', name := 'General', price := 2500,
  dateOpen := <datetime>'2024-01-01T00:00:00Z',
  dateExpire := <datetime>'2030-01-01T00:00:00Z',
  approvalRequired := false, transferable := true, hidden := false
};

# Published events. Alike in every respect except for the receipt items below.
for e in {
  ('evt-published-001', 'Series Event 01'),
  ('evt-published-002', 'Series Event 02'),
  ('evt-published-003', 'Series Event 03'),
  ('evt-published-004', 'Series Event 04'),
  ('evt-published-005', 'Series Event 05'),
  ('evt-published-006', 'Series Event 06'),
  ('evt-published-007', 'Series Event 07'),
  ('evt-published-008', 'Series Event 08'),
  ('evt-published-009', 'Series Event 09'),
  ('evt-published-010', 'Series Event 10')
} union (
  insert Event {
    firestore_id := e.0,
    name := e.1,
    description := 'published from a series occurrence',
    scan_code := 'SERIES1',
    start_time := <datetime>'2026-03-03T02:00:00Z',
    end_time := <datetime>'2026-03-03T08:00:00Z',
    date_end := <datetime>'2026-03-03T08:00:00Z',
    deleted := false,
    visibility := EventVisibility.Public,
    tickets := (select EventTicket filter .firestore_id = 'tkt-series-general')
  }
);

insert PersonaEvent {
  firestore_id := 'pe-series-mgr-001',
  privilege := PersonaEventPrivilege.host,
  event := assert_single((select Event filter .firestore_id = 'evt-published-001')),
  persona := assert_single((select User filter .firestore_id = 'usr-series-mgr'))
};

# Receipt items.
# (id, event, pending, refund status, abandoned)
for t in {
  ('ri-ser-0001', 'evt-published-001', false, 'none',      false),
  ('ri-ser-0002', 'evt-published-001', false, 'none',      false),
  ('ri-ser-0003', 'evt-published-002', true,  'none',      false),
  ('ri-ser-0004', 'evt-published-002', false, 'refunded',  false),
  ('ri-ser-0005', 'evt-published-002', false, 'none',      true),
  ('ri-ser-0006', 'evt-published-004', false, 'none',      false),
  ('ri-ser-0007', 'evt-published-005', true,  'none',      false),
  ('ri-ser-0008', 'evt-published-005', false, 'refunded',  false),
  ('ri-ser-0009', 'evt-published-007', false, 'none',      false),
  ('ri-ser-0010', 'evt-published-005', false, 'requested', false)
} union (
  insert ReceiptItem {
    firestore_id := t.0,
    receipt_item_id := t.0,
    transaction_id := 'txn-' ++ t.0,
    price := 2500,
    recipient_user_event_mapping_id := '',
    pending := t.2,
    abandoned := t.4,
    scans := <array<str>>[],
    refund_status := <RefundStatus>t.3,
    date_created := <datetime>'2026-02-01T18:00:00Z',
    event := assert_single((select Event filter .firestore_id = t.1)),
    ticket := assert_single((select EventTicket filter .firestore_id = 'tkt-series-general'))
  }
);

# ser-la-weekly: Los Angeles, Sundays and Wednesdays at 19:00, eight from
# 1 March 2026.
insert EventSeries {
  series_id := 'ser-la-weekly',
  organization := assert_single((select Organization filter .firestore_id = 'org-series-001')),
  name := 'Sunday and Wednesday Nights',
  description := 'weekly on two days',
  form_data := <json>'{"name":"Sunday and Wednesday Nights","description":"twice weekly","startTimeOffset":68400,"visibility":{"showToPublic":true,"showToFriends":false},"eventType":"party","color":"orange","effect":"none","settings":{},"tickets":[],"location":{}}',
  repeat_config := (insert EventSeriesRepeatConfig {
    repeat_interval := 1,
    repeat_unit := EventSeriesRepeatUnit.week,
    selected_days := [0, 3],
    timezone := 'America/Los_Angeles',
    end_type := EventSeriesEndType.afterOccurrences,
    number_of_occurrences := 8
  })
};

# ser-lhi-weekly: Lord Howe Island, Sundays at 01:45, five from 22 March 2026.
insert EventSeries {
  series_id := 'ser-lhi-weekly',
  organization := assert_single((select Organization filter .firestore_id = 'org-series-001')),
  name := 'Lord Howe Sundays',
  description := 'Sunday mornings',
  form_data := <json>'{"name":"Lord Howe Sundays","description":"weekly","startTimeOffset":6300,"visibility":{"showToPublic":true,"showToFriends":false},"eventType":"party","color":"blue","effect":"none","settings":{},"tickets":[],"location":{}}',
  repeat_config := (insert EventSeriesRepeatConfig {
    repeat_interval := 1,
    repeat_unit := EventSeriesRepeatUnit.week,
    selected_days := [0],
    timezone := 'Australia/Lord_Howe',
    end_type := EventSeriesEndType.afterOccurrences,
    number_of_occurrences := 5
  })
};

# ser-lis-monthly: Lisbon, monthly on the 29th at 01:05, five from
# 29 January 2026.
insert EventSeries {
  series_id := 'ser-lis-monthly',
  organization := assert_single((select Organization filter .firestore_id = 'org-series-001')),
  name := 'Lisbon Month Ends',
  description := 'monthly, month end',
  form_data := <json>'{"name":"Lisbon Month Ends","description":"monthly","startTimeOffset":3900,"visibility":{"showToPublic":true,"showToFriends":false},"eventType":"party","color":"green","effect":"none","settings":{},"tickets":[],"location":{}}',
  repeat_config := (insert EventSeriesRepeatConfig {
    repeat_interval := 1,
    repeat_unit := EventSeriesRepeatUnit.month,
    selected_days := <array<int32>>[],
    timezone := 'Europe/Lisbon',
    end_type := EventSeriesEndType.afterOccurrences,
    number_of_occurrences := 5
  })
};

# ser-race-001: Los Angeles, daily at 19:00, five from 1 June 2026, all
# published.
insert EventSeries {
  series_id := 'ser-race-001',
  organization := assert_single((select Organization filter .firestore_id = 'org-series-001')),
  name := 'Evenings',
  description := 'daily evenings',
  form_data := <json>'{"name":"Contested Evenings","description":"daily","startTimeOffset":68400,"visibility":{"showToPublic":true,"showToFriends":false},"eventType":"party","color":"red","effect":"none","settings":{},"tickets":[],"location":{}}',
  repeat_config := (insert EventSeriesRepeatConfig {
    repeat_interval := 1,
    repeat_unit := EventSeriesRepeatUnit.day,
    selected_days := <array<int32>>[],
    timezone := 'America/Los_Angeles',
    end_type := EventSeriesEndType.afterOccurrences,
    number_of_occurrences := 5
  })
};

# ser-utc-daily: UTC, every second day at noon, stopping on a date.
insert EventSeries {
  series_id := 'ser-utc-daily',
  organization := assert_single((select Organization filter .firestore_id = 'org-series-001')),
  name := 'Every Other Day',
  description := 'every other day',
  form_data := <json>'{"name":"Every Other Day","description":"every other day","startTimeOffset":43200,"visibility":{"showToPublic":true,"showToFriends":false},"eventType":"party","color":"blue","effect":"none","settings":{},"tickets":[],"location":{}}',
  repeat_config := (insert EventSeriesRepeatConfig {
    repeat_interval := 2,
    repeat_unit := EventSeriesRepeatUnit.day,
    selected_days := <array<int32>>[],
    timezone := 'UTC',
    end_type := EventSeriesEndType.onDate,
    end_date := <datetime>'2026-03-10T00:00:00Z'
  })
};

# ser-syd-scoped: Sydney, Thursdays at 19:00, six from 7 May 2026. A host has
# already run a "this and following" edit over it from the third night on.
insert EventSeries {
  series_id := 'ser-syd-scoped',
  organization := assert_single((select Organization filter .firestore_id = 'org-series-001')),
  name := 'Harbour Thursdays',
  description := 'weekly on Thursdays',
  form_data := <json>'{"name":"Harbour Thursdays","description":"weekly","startTimeOffset":68400,"visibility":{"showToPublic":true,"showToFriends":false},"eventType":"party","color":"purple","effect":"none","settings":{},"tickets":[],"location":{}}',
  repeat_config := (insert EventSeriesRepeatConfig {
    repeat_interval := 1,
    repeat_unit := EventSeriesRepeatUnit.week,
    selected_days := [4],
    timezone := 'Australia/Sydney',
    end_type := EventSeriesEndType.afterOccurrences,
    number_of_occurrences := 6
  })
};

# ser-ber-gap: Berlin, Tuesdays at 19:00, five from 2 June 2026. The host
# deleted the third night and later asked for two more.
insert EventSeries {
  series_id := 'ser-ber-gap',
  organization := assert_single((select Organization filter .firestore_id = 'org-series-001')),
  name := 'Kreuzberg Tuesdays',
  description := 'weekly on Tuesdays',
  form_data := <json>'{"name":"Kreuzberg Tuesdays","description":"weekly","startTimeOffset":68400,"visibility":{"showToPublic":true,"showToFriends":false},"eventType":"party","color":"yellow","effect":"none","settings":{},"tickets":[],"location":{}}',
  repeat_config := (insert EventSeriesRepeatConfig {
    repeat_interval := 1,
    repeat_unit := EventSeriesRepeatUnit.week,
    selected_days := [2],
    timezone := 'Europe/Berlin',
    end_type := EventSeriesEndType.afterOccurrences,
    number_of_occurrences := 5
  })
};

# ------------------------------------------------------------- occurrences
# (series_id, occurrence_id, instant)

for o in {

  # ser-la-weekly, Los Angeles 19:00 on Sundays and Wednesdays.
  ('ser-la-weekly', 'occ-la-1', <datetime>'2026-03-02T03:00:00Z'),
  ('ser-la-weekly', 'occ-la-2', <datetime>'2026-03-05T03:00:00Z'),
  ('ser-la-weekly', 'occ-la-3', <datetime>'2026-03-09T02:00:00Z'),
  ('ser-la-weekly', 'occ-la-4', <datetime>'2026-03-12T02:00:00Z'),
  ('ser-la-weekly', 'occ-la-5', <datetime>'2026-03-16T02:00:00Z'),
  ('ser-la-weekly', 'occ-la-6', <datetime>'2026-03-19T02:00:00Z'),
  ('ser-la-weekly', 'occ-la-7', <datetime>'2026-03-23T02:00:00Z'),
  ('ser-la-weekly', 'occ-la-8', <datetime>'2026-03-26T02:00:00Z'),

  # ser-lhi-weekly, Lord Howe Sundays 01:45.
  ('ser-lhi-weekly', 'occ-lhi-1', <datetime>'2026-03-21T14:45:00Z'),
  ('ser-lhi-weekly', 'occ-lhi-2', <datetime>'2026-03-28T14:45:00Z'),
  ('ser-lhi-weekly', 'occ-lhi-3', <datetime>'2026-04-04T14:45:00Z'),
  ('ser-lhi-weekly', 'occ-lhi-4', <datetime>'2026-04-11T15:15:00Z'),
  ('ser-lhi-weekly', 'occ-lhi-5', <datetime>'2026-04-18T15:15:00Z'),

  # ser-lis-monthly, Lisbon on the 29th at 01:05.
  ('ser-lis-monthly', 'occ-lis-1', <datetime>'2026-01-29T01:05:00Z'),
  ('ser-lis-monthly', 'occ-lis-2', <datetime>'2026-02-28T01:05:00Z'),
  ('ser-lis-monthly', 'occ-lis-3', <datetime>'2026-03-29T01:00:00Z'),
  ('ser-lis-monthly', 'occ-lis-4', <datetime>'2026-04-29T00:05:00Z'),
  ('ser-lis-monthly', 'occ-lis-5', <datetime>'2026-05-29T00:05:00Z'),

  # ser-race-001, Los Angeles daily 19:00.
  ('ser-race-001', 'occ-race-a', <datetime>'2026-06-02T02:00:00Z'),
  ('ser-race-001', 'occ-race-b', <datetime>'2026-06-03T02:00:00Z'),
  ('ser-race-001', 'occ-race-c', <datetime>'2026-06-04T02:00:00Z'),
  ('ser-race-001', 'occ-race-d', <datetime>'2026-06-05T02:00:00Z'),
  ('ser-race-001', 'occ-race-e', <datetime>'2026-06-06T02:00:00Z'),

  # ser-syd-scoped, Sydney Thursdays. The first two are still at the 19:00 the
  # series template carries; the rest were moved to 17:00 by a scoped edit and
  # kept the Thursdays they were already on.
  ('ser-syd-scoped', 'occ-syd-1', <datetime>'2026-05-07T09:00:00Z'),
  ('ser-syd-scoped', 'occ-syd-2', <datetime>'2026-05-14T09:00:00Z'),
  ('ser-syd-scoped', 'occ-syd-3', <datetime>'2026-05-21T07:00:00Z'),
  ('ser-syd-scoped', 'occ-syd-4', <datetime>'2026-05-28T07:00:00Z'),
  ('ser-syd-scoped', 'occ-syd-5', <datetime>'2026-06-04T07:00:00Z'),
  ('ser-syd-scoped', 'occ-syd-6', <datetime>'2026-06-11T07:00:00Z'),

  # ser-utc-daily, noon UTC every other day.
  ('ser-utc-daily', 'occ-utc-1', <datetime>'2026-03-02T12:00:00Z'),
  ('ser-utc-daily', 'occ-utc-2', <datetime>'2026-03-04T12:00:00Z'),
  ('ser-utc-daily', 'occ-utc-3', <datetime>'2026-03-06T12:00:00Z'),
  ('ser-utc-daily', 'occ-utc-4', <datetime>'2026-03-08T12:00:00Z'),
  ('ser-utc-daily', 'occ-utc-5', <datetime>'2026-03-10T12:00:00Z')
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

# ser-ber-gap's occurrences. Written in two batches, so each row carries its own
# creation stamp rather than the shared one used above.
#
# Four rows were written together on 1 February; occ-ber-3 is absent, because the
# host deleted that night. The remaining two were written together five weeks
# later, when the host asked for two more nights.
# (occurrence_id, instant, date_created)
for o in {
  ('occ-ber-1', <datetime>'2026-06-02T17:00:00Z', <datetime>'2026-02-01T12:00:00Z'),
  ('occ-ber-2', <datetime>'2026-06-09T17:00:00Z', <datetime>'2026-02-01T12:00:00Z'),
  ('occ-ber-4', <datetime>'2026-06-23T17:00:00Z', <datetime>'2026-02-01T12:00:00Z'),
  ('occ-ber-5', <datetime>'2026-06-30T17:00:00Z', <datetime>'2026-02-01T12:00:00Z'),
  ('occ-ber-6', <datetime>'2026-06-16T17:00:00Z', <datetime>'2026-03-10T09:30:00Z'),
  ('occ-ber-7', <datetime>'2026-07-07T17:00:00Z', <datetime>'2026-03-10T09:30:00Z')
} union (
  update EventSeries filter .series_id = 'ser-ber-gap'
  set {
    occurrences += (insert EventSeriesOccurrence {
      occurrence_id := o.0,
      date := o.1,
      date_created := o.2
    })
  }
);

# Give every occurrence its own copy of its series' template.
#
# Done per series rather than inside the loop above: a subquery that filters
# EventSeries on the loop variable is correlated with the row being updated, and
# Gel refuses it outright. Filtering on a literal series id is not correlated
# with anything, so each of these is an ordinary independent subquery.
for s in {
  ('ser-race-001',       'occ-race-'),
  ('ser-la-weekly',      'occ-la-'),
  ('ser-lhi-weekly',     'occ-lhi-'),
  ('ser-lis-monthly',    'occ-lis-'),
  ('ser-utc-daily',      'occ-utc-'),
  ('ser-syd-scoped',     'occ-syd-'),
  ('ser-ber-gap',        'occ-ber-')
} union (
  update EventSeriesOccurrence
  filter .occurrence_id like s.1 ++ '%'
  set {
    form_data := assert_single((
      select EventSeries { form_data } filter .series_id = s.0
    )).form_data
  }
);

# The scoped edit that has already run over ser-syd-scoped.
#
# It reached the third night and the ones after it. Each row it reached carries
# its own copy of the template the host submitted -- a whole form, not a patch
# -- and the series' own template is not among them: it still says 68400. The
# rows it did not reach still hold the copy the generation gave them.
#
# `date_updated` is set on exactly the rows it reached.
update EventSeriesOccurrence
filter .occurrence_id in {'occ-syd-3', 'occ-syd-4', 'occ-syd-5', 'occ-syd-6'}
set {
  form_data := <json>'{"name":"Harbour Thursdays","description":"weekly","startTimeOffset":61200,"visibility":{"showToPublic":true,"showToFriends":false},"eventType":"party","color":"purple","effect":"none","settings":{},"tickets":[],"location":{}}',
  date_updated := <datetime>'2026-04-18T22:10:00Z'
};

# ser-race-001's occurrences, all published.
# (occurrence, event)
for p in {
  ('occ-race-a', 'evt-published-008'),
  ('occ-race-b', 'evt-published-006'),
  ('occ-race-c', 'evt-published-009'),
  ('occ-race-d', 'evt-published-007'),
  ('occ-race-e', 'evt-published-010')
} union (
  update EventSeriesOccurrence filter .occurrence_id = p.0
  set {
    published_event := assert_single((select Event filter .firestore_id = p.1)),
    date_updated := <datetime>'2026-05-02T12:00:00Z'
  }
);
