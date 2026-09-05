-- The desk's outbox: replies the console has composed, and where each one is.
--
-- Composing and sending are separated by this table. The console's call returns
-- when the reply is durable, not when it is on the wire; the dispatcher moves it
-- the rest of the way. `state` is the whole of the life:
--
--   queued    durable here and not on the wire. Either the transport has not
--             been offered it, or it was offered it and did not say what
--             happened, which is the same position to be in.
--   sent      on the wire, and recorded on its ticket in the same transaction
--             that wrote this.
--   refused   the transport will not carry it. Terminal, and nothing is
--             recorded on the ticket, because nothing went out.
--
-- `reply_id` is the primary key because it is the console's own key and the only
-- thing that says two arrivals are one reply.
--
-- `message_id` is what the wire and the gateway both use, so it is indexed: the
-- dispatcher looks a reply up by it to keep a second handoff from becoming a
-- second message, and intake looks it up to recognise the desk's own send coming
-- back over a gateway that reflects.
CREATE TABLE IF NOT EXISTS outbox (
    tenant_id       TEXT NOT NULL,
    reply_id        TEXT NOT NULL,
    ticket_id       TEXT NOT NULL,
    message_id      TEXT NOT NULL,
    from_address    TEXT NOT NULL,
    to_addresses    TEXT NOT NULL,
    in_reply_to     TEXT,
    references_json TEXT NOT NULL DEFAULT '[]',
    composed_at     TEXT NOT NULL,
    state           TEXT NOT NULL CHECK (state IN ('queued', 'sent', 'refused')),
    reason          TEXT,
    PRIMARY KEY (tenant_id, reply_id)
);

CREATE INDEX IF NOT EXISTS outbox_by_message
    ON outbox (tenant_id, message_id);

CREATE INDEX IF NOT EXISTS outbox_by_state
    ON outbox (tenant_id, state, composed_at, reply_id);

-- Replies the desk sent before there was an outbox to send them from.
--
-- A store with history in it has the desk's own messages on its tickets
-- already: they are the deliveries whose sender is one of the desk's own
-- addresses. Those messages are on the wire — they were sent, which is how they
-- came to be recorded — so they belong here as `sent`, and the dispatcher must
-- not offer them to the transport a second time on the first tick after the
-- upgrade.
--
-- Keyed off `message_id` rather than the row's own key, because the key a
-- console reply has is not one a historical delivery ever had: what stops this
-- inserting twice is the message already being accounted for, whichever side
-- accounted for it. That also makes it safe when the console has since composed
-- a reply for the same message, and safe to run again, which it is: `npm run
-- migrate` applies every file here every time it is run.
INSERT OR IGNORE INTO outbox
    (tenant_id, reply_id, ticket_id, message_id, from_address, to_addresses,
     in_reply_to, references_json, composed_at, state, reason)
SELECT e.tenant_id,
       e.transport_id,
       e.ticket_id,
       e.message_id,
       e.from_address,
       e.to_addresses,
       e.in_reply_to,
       e.references_json,
       e.received_at,
       'sent',
       NULL
  FROM envelopes e
  JOIN desk_addresses d
    ON d.tenant_id = e.tenant_id AND d.address = e.from_address
 WHERE e.ticket_id IS NOT NULL
   AND NOT EXISTS (
       SELECT 1 FROM outbox o
        WHERE o.tenant_id = e.tenant_id AND o.message_id = e.message_id
   );
