-- What routing has to remember and the shipped store does not hold.
--
-- Three things: which conversation a message identifier belongs to, the
-- relationships a ticket has beyond its own state, and deliveries that could not
-- be placed when they arrived.

-- A conversation is a set of message identifiers. This is that set, inverted, so
-- the question routing actually asks -- "what conversation is this identifier
-- in?" -- is one primary-key lookup. An identifier appears here as soon as any
-- delivery names it, whether or not a delivery carrying it has arrived.
--
-- A merge is an update to this table: every identifier of the absorbed
-- conversation is pointed at the survivor. That is why the mapping is stored
-- identifier-first rather than as a chain of parent links -- there is nothing to
-- walk and nothing to recompute, and no delivery ever has to be re-threaded.
CREATE TABLE IF NOT EXISTS identifier_conversation (
    tenant_id       TEXT NOT NULL,
    identifier      TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    PRIMARY KEY (tenant_id, identifier)
);

-- A ticket's place in its conversation.
--
-- `sequence` is the order tickets were opened in on this desk. `created_at` is
-- the arrival of the delivery that opened the ticket and can go backwards when
-- the gateway delivers out of order, so it cannot stand in for creation order.
CREATE TABLE IF NOT EXISTS ticket_thread (
    tenant_id             TEXT NOT NULL,
    ticket_id             TEXT NOT NULL,
    conversation_id       TEXT NOT NULL,
    -- The ticket this one continues, when the conversation outlived one.
    prior_ticket_id       TEXT,
    -- Set once this ticket has been merged into another. A ticket with this set
    -- is closed and holds none of its own deliveries.
    merged_into_ticket_id TEXT,
    sequence              INTEGER NOT NULL,
    PRIMARY KEY (tenant_id, ticket_id)
);

-- Deliveries waiting on a message that has not arrived.
CREATE TABLE IF NOT EXISTS held_deliveries (
    tenant_id    TEXT NOT NULL,
    transport_id TEXT NOT NULL,
    awaiting     TEXT NOT NULL,
    payload      TEXT NOT NULL,
    received_at  TEXT NOT NULL,
    PRIMARY KEY (tenant_id, transport_id)
);

CREATE INDEX IF NOT EXISTS idx_identifier_conversation
    ON identifier_conversation (tenant_id, conversation_id);

CREATE INDEX IF NOT EXISTS idx_ticket_thread_conversation
    ON ticket_thread (tenant_id, conversation_id);

CREATE INDEX IF NOT EXISTS idx_envelopes_message
    ON envelopes (tenant_id, message_id);

CREATE INDEX IF NOT EXISTS idx_envelopes_ticket
    ON envelopes (ticket_id);

CREATE INDEX IF NOT EXISTS idx_held_awaiting
    ON held_deliveries (tenant_id, awaiting);
