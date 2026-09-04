import { Router } from 'express';

import { compose } from '../egress/compose';
import { parseReply } from '../egress/parseReply';
import type { OutboxRow } from '../egress/outbox';

/**
 * Taking a composed reply, and reading the desk's outbox back.
 *
 * The wire shape is `OutboxEntry` both times, so the console gets the same
 * answer to "I have composed this" and "where has it got to" and does not need
 * two readers.
 */
export function repliesRouter(): Router {
  const router = Router();

  router.post('/v1/tenants/:tenantId/tickets/:ticketId/replies', async (req, res) => {
    const { tenantId, ticketId } = req.params;
    const parsed = parseReply(tenantId, ticketId, req.body);
    if (!parsed.ok) {
      res.status(400).json({ error: 'reply did not validate', details: parsed.errors });
      return;
    }

    try {
      const result = await compose(parsed.reply);
      if (!result.ok) {
        res.status(404).json({ error: 'no such ticket under this tenant' });
        return;
      }
      res.status(200).json(entryView(result.entry));
    } catch (error) {
      res.status(500).json({ error: 'composing failed', detail: String(error) });
    }
  });

  return router;
}

export function entryView(row: OutboxRow): Record<string, unknown> {
  return {
    reply_id: row.reply_id,
    ticket_id: row.ticket_id,
    message_id: row.message_id,
    state: row.state,
  };
}
