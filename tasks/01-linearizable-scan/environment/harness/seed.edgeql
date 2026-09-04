# Development and grading fixture for the door. Applied after reset.edgeql.
#
# Identifiers here are deliberately uninformative: an implementation should not
# be able to tell from a receipt item id what is about to be done with it.

# Staff, then attendees. usr-a01..usr-a35 hold tickets at the event under test;
# usr-a36 holds tickets at a second event that exists so that "this event's
# tickets" and "this event's door code" are answerable questions.
insert User {
  firestore_id := 'usr-host-001', name := 'Host', description := 'organiser',
  display_name := 'Host', bio := '', birthdate := <datetime>'1990-01-01T00:00:00Z',
  date_joined := <datetime>'2024-01-01T00:00:00Z'
};
insert User {
  firestore_id := 'usr-door-1', name := 'Door 1', description := 'bouncer',
  display_name := 'Door 1', bio := '', birthdate := <datetime>'1990-01-01T00:00:00Z',
  date_joined := <datetime>'2024-01-01T00:00:00Z'
};
insert User {
  firestore_id := 'usr-door-2', name := 'Door 2', description := 'bouncer',
  display_name := 'Door 2', bio := '', birthdate := <datetime>'1990-01-01T00:00:00Z',
  date_joined := <datetime>'2024-01-01T00:00:00Z'
};
insert User {
  firestore_id := 'usr-door-3', name := 'Door 3', description := 'bouncer',
  display_name := 'Door 3', bio := '', birthdate := <datetime>'1990-01-01T00:00:00Z',
  date_joined := <datetime>'2024-01-01T00:00:00Z'
};
insert User {
  firestore_id := 'usr-host-002', name := 'Other Host', description := 'organiser',
  display_name := 'Other Host', bio := '', birthdate := <datetime>'1990-01-01T00:00:00Z',
  date_joined := <datetime>'2024-01-01T00:00:00Z'
};

for i in range_unpack(range(1, 37)) union (
  with gid := 'usr-a' ++ (('0' ++ to_str(i)) if i < 10 else to_str(i))
  insert User {
    firestore_id := gid, name := gid, description := 'attendee',
    display_name := gid, bio := '', birthdate := <datetime>'2000-01-01T00:00:00Z',
    date_joined := <datetime>'2024-01-01T00:00:00Z'
  }
);

insert EventTicket {
  firestore_id := 'tkt-general', capacity := 500, description := 'General admission',
  name := 'General', price := 1000, dateOpen := <datetime>'2024-01-01T00:00:00Z',
  dateExpire := <datetime>'2030-01-01T00:00:00Z', approvalRequired := false,
  transferable := true, hidden := false
};

insert Event {
  firestore_id := '11111111-1111-4111-8111-111111111111',
  name := 'Door Test Event',
  description := 'Scan fixture event',
  scan_code := 'DOOR42',
  # A door shift that contains the present moment, rather than an open-ended
  # range: the event window is what the host-facing reports are drawn against.
  start_time := datetime_of_statement() - <duration>'2 hours',
  end_time := datetime_of_statement() + <duration>'6 hours',
  # The schema carries a duplicated end timestamp for older queries, and the
  # analytics path reads that one rather than end_time. Populate both.
  date_end := datetime_of_statement() + <duration>'6 hours',
  deleted := false,
  visibility := EventVisibility.Public,
  tickets := (select EventTicket filter .firestore_id = 'tkt-general')
};

# A second door, running at the same time, with its own code and its own staff.
insert Event {
  firestore_id := '22222222-2222-4222-8222-222222222222',
  name := 'Other Door Event',
  description := 'A different door entirely',
  scan_code := 'DOOR99',
  start_time := datetime_of_statement() - <duration>'2 hours',
  end_time := datetime_of_statement() + <duration>'6 hours',
  date_end := datetime_of_statement() + <duration>'6 hours',
  deleted := false,
  visibility := EventVisibility.Public,
  tickets := (select EventTicket filter .firestore_id = 'tkt-general')
};

# Who is allowed to scan, and where.
for s in {('pe-host-001', 'usr-host-001', 'host'),
          ('pe-door-1', 'usr-door-1', 'bouncer'),
          ('pe-door-2', 'usr-door-2', 'bouncer'),
          ('pe-door-3', 'usr-door-3', 'bouncer')} union (
  insert PersonaEvent {
    firestore_id := s.0,
    privilege := (PersonaEventPrivilege.host if s.2 = 'host'
                  else PersonaEventPrivilege.bouncer),
    event := assert_single((select Event filter .firestore_id = '11111111-1111-4111-8111-111111111111')),
    persona := assert_single((select User filter .firestore_id = s.1))
  }
);
insert PersonaEvent {
  firestore_id := 'pe-host-002',
  privilege := PersonaEventPrivilege.host,
  event := assert_single((select Event filter .firestore_id = '22222222-2222-4222-8222-222222222222')),
  persona := assert_single((select User filter .firestore_id = 'usr-host-002'))
};

for i in range_unpack(range(1, 36)) union (
  with gid := 'usr-a' ++ (('0' ++ to_str(i)) if i < 10 else to_str(i))
  insert PersonaEvent {
    firestore_id := 'pe-' ++ gid,
    privilege := PersonaEventPrivilege.attendee,
    event := assert_single((select Event filter .firestore_id = '11111111-1111-4111-8111-111111111111')),
    persona := assert_single((select User filter .firestore_id = gid))
  }
);
insert PersonaEvent {
  firestore_id := 'pe-usr-a36',
  privilege := PersonaEventPrivilege.attendee,
  event := assert_single((select Event filter .firestore_id = '22222222-2222-4222-8222-222222222222')),
  persona := assert_single((select User filter .firestore_id = 'usr-a36'))
};

# Receipt items at the event under test: (id, owner, pending, refunded,
# abandoned). Some people hold one ticket and some hold several, as at a real
# door.
for t in {
  ('ri-0001', 'usr-a01', false, false, false),
  ('ri-0002', 'usr-a02', false, false, false),
  ('ri-0003', 'usr-a03', false, false, false),
  ('ri-0004', 'usr-a03', false, false, false),
  ('ri-0005', 'usr-a03', false, false, false),
  ('ri-0006', 'usr-a04', false, false, false),
  ('ri-0007', 'usr-a04', false, false, false),
  ('ri-0008', 'usr-a04', false, false, false),
  ('ri-0009', 'usr-a05', true,  false, false),
  ('ri-0010', 'usr-a06', false, false, false),
  ('ri-0011', 'usr-a07', false, false, false),
  ('ri-0012', 'usr-a08', false, false, false),
  ('ri-0013', 'usr-a09', false, false, false),
  ('ri-0014', 'usr-a10', false, false, false),
  ('ri-0015', 'usr-a11', false, false, false),
  ('ri-0016', 'usr-a11', false, false, false),
  ('ri-0017', 'usr-a12', false, true,  false),
  ('ri-0018', 'usr-a12', false, false, true),
  ('ri-0019', 'usr-a13', false, false, false),
  ('ri-0020', 'usr-a14', false, false, false),
  ('ri-0021', 'usr-a15', false, false, false),
  ('ri-0022', 'usr-a15', false, false, false),
  ('ri-0023', 'usr-a16', false, false, false),
  ('ri-0024', 'usr-a17', false, false, false),
  ('ri-0025', 'usr-a18', false, false, false),
  ('ri-0026', 'usr-a19', false, false, false),
  ('ri-0027', 'usr-a20', false, false, false),
  ('ri-0028', 'usr-a21', false, false, false),
  ('ri-0029', 'usr-a21', false, false, false),
  ('ri-0030', 'usr-a21', false, false, false),
  ('ri-0031', 'usr-a22', false, false, false),
  ('ri-0032', 'usr-a22', false, false, false),
  ('ri-0033', 'usr-a22', false, false, false),
  ('ri-0034', 'usr-a23', false, false, false),
  ('ri-0035', 'usr-a24', false, false, false),
  ('ri-0036', 'usr-a24', false, false, false),
  ('ri-0037', 'usr-a24', false, false, false),
  ('ri-0038', 'usr-a24', false, false, false),
  ('ri-0039', 'usr-a25', false, false, false),
  ('ri-0040', 'usr-a25', false, false, false),
  ('ri-0041', 'usr-a25', false, false, false),
  ('ri-0042', 'usr-a26', false, false, false),
  ('ri-0043', 'usr-a26', false, false, false),
  ('ri-0044', 'usr-a26', false, false, false),
  ('ri-0045', 'usr-a27', false, false, false),
  ('ri-0046', 'usr-a27', true,  false, false),
  ('ri-0047', 'usr-a27', false, false, false),
  ('ri-0048', 'usr-a28', false, false, false),
  ('ri-0049', 'usr-a29', false, false, false),
  ('ri-0050', 'usr-a29', false, true,  false),
  ('ri-0051', 'usr-a30', false, false, false),
  ('ri-0052', 'usr-a30', false, false, true),
  ('ri-0053', 'usr-a31', false, false, false),
  ('ri-0054', 'usr-a31', true,  false, false),
  ('ri-0055', 'usr-a32', false, false, false),
  ('ri-0056', 'usr-a32', false, false, false),
  ('ri-0057', 'usr-a33', false, false, false),
  ('ri-0058', 'usr-a34', false, false, false),
  ('ri-0059', 'usr-a35', false, false, false)
} union (
  insert ReceiptItem {
    firestore_id := t.0,
    receipt_item_id := t.0,
    transaction_id := 'txn-' ++ t.0,
    price := 1000,
    # The ticket-mapping query ORs on this property, and EdgeQL's `or`
    # propagates the empty set, so a row that leaves it unset is invisible to
    # the lookup. Migrated rows carry an empty string; match that.
    recipient_user_event_mapping_id := '',
    pending := t.2,
    abandoned := t.4,
    # Rows that came through the Firestore migration always carry an array
    # here, never an unset property. Match that: leaving it unset changes how
    # the coalescing idiom used elsewhere in the codebase behaves.
    scans := <array<str>>[],
    refund_status := (RefundStatus.refunded if t.3 else RefundStatus.none),
    date_created := <datetime>'2024-06-01T18:00:00Z',
    event := assert_single((select Event filter .firestore_id = '11111111-1111-4111-8111-111111111111')),
    ticket := assert_single((select EventTicket filter .firestore_id = 'tkt-general')),
    persona_event := assert_single((select PersonaEvent filter .firestore_id = 'pe-' ++ t.1))
  }
);

# And one ticket that belongs to the other door.
insert ReceiptItem {
  firestore_id := 'ri-0060',
  receipt_item_id := 'ri-0060',
  transaction_id := 'txn-ri-0060',
  price := 1000,
  recipient_user_event_mapping_id := '',
  pending := false,
  abandoned := false,
  scans := <array<str>>[],
  refund_status := RefundStatus.none,
  date_created := <datetime>'2024-06-01T18:00:00Z',
  event := assert_single((select Event filter .firestore_id = '22222222-2222-4222-8222-222222222222')),
  ticket := assert_single((select EventTicket filter .firestore_id = 'tkt-general')),
  persona_event := assert_single((select PersonaEvent filter .firestore_id = 'pe-usr-a36'))
};

# One ticket that came through the door an hour ago, so the fixture starts with
# some scan history rather than none.
insert Scan {
  scan_id := 'scn-0001',
  firestore_id := 'scn-0001',
  scan_type := ScanType.qr,
  date_created := datetime_of_statement() - <duration>'1 hour',
  purchased_ticket_ids := ['ri-0010'],
  scanner_user := assert_single((select User filter .firestore_id = 'usr-host-001'))
};
update ReceiptItem filter .firestore_id = 'ri-0010'
set { scans := ['scn-0001'] };
