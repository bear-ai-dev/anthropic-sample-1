import { Router } from 'express';

import { dispatchTick } from '../egress/dispatcher';
import { listOutbox, type OutboxState } from '../egress/outbox';
import { entryView } from './replies';

const STATES = new Set(['queued', 'sent', 'refused']);

/**
 * The dispatch tick and the outbox read.
 *
 * The tick answers with a tally and nothing that has to be believed: where a
 * reply is, is read from the outbox. That matters because a tick can overlap
 * another tick, and the second one's tally is honestly zero for work the first
 * one is in the middle of.
 */
export function egressRouter(): Router {
  const router = Router();

  router.post('/v1/egress/dispatch', async (req, res) => {
    const body = (req.body ?? {}) as Record<string, unknown>;
    const tenantId = typeof body.tenant_id === 'string' ? body.tenant_id : undefined;
    try {
      const report = await dispatchTick(tenantId);
      res.status(200).json(report);
    } catch (error) {
      res.status(500).json({ error: 'dispatch failed', detail: String(error) });
    }
  });

  router.get('/v1/tenants/:tenantId/outbox', async (req, res) => {
    const asked = req.query.state;
    if (typeof asked === 'string' && !STATES.has(asked)) {
      res.status(400).json({ error: 'state must be queued, sent or refused' });
      return;
    }
    const state = typeof asked === 'string' ? (asked as OutboxState) : null;
    try {
      const rows = await listOutbox(req.params.tenantId, state);
      res.status(200).json({ replies: rows.map(entryView) });
    } catch (error) {
      res.status(500).json({ error: 'outbox read failed', detail: String(error) });
    }
  });

  return router;
}
