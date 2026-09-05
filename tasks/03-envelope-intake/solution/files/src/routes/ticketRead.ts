import { Router } from 'express';

import { ticketView } from '../intake/serialize';
import * as store from '../intake/store';

/**
 * Reading a ticket back.
 *
 * Scoped to the tenant in the path, and scoped in the query rather than after
 * it: a ticket belonging to another desk is not found. Reporting it as
 * forbidden would confirm that it exists, which the caller is not entitled to
 * know.
 */
export function ticketReadRouter(): Router {
  const router = Router();

  router.get('/v1/tenants/:tenantId/tickets/:ticketId', async (req, res) => {
    const { tenantId, ticketId } = req.params;
    try {
      const ticket = await store.findTicket(tenantId, ticketId);
      if (ticket === undefined) {
        res.status(404).json({ error: 'ticket not found' });
        return;
      }
      res.status(200).json(await ticketView(ticket));
    } catch (error) {
      res.status(500).json({ error: 'ticket read failed', detail: String(error) });
    }
  });

  return router;
}
