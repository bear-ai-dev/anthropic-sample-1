/**
 * Operator surface for the projection rebuild.
 *
 * These are the endpoints an operator drives a cutover through. Their paths
 * and payloads are fixed.
 *
 * A stage that refuses is not an error in the service; it is the machine
 * declining to take an unsafe step, and the operator is told which one and why.
 */

import { Router, type Response } from 'express';
import {
  NotImplemented,
  StageRefused,
  abort,
  diagnostics,
  status,
  step,
} from '../rebuild/orchestrator.js';

export const adminRouter = Router();

function fail(res: Response, err: unknown) {
  if (err instanceof NotImplemented) return res.status(501).json({ error: err.message });
  if (err instanceof StageRefused) {
    return res.status(409).json({ error: err.message, stage: err.stage, refused: true });
  }
  return res.status(500).json({ error: String(err) });
}

adminRouter.post('/admin/projections/rebuild/step', async (_req, res) => {
  try {
    return res.json(await step());
  } catch (err) {
    return fail(res, err);
  }
});

adminRouter.post('/admin/projections/rebuild/abort', async (_req, res) => {
  try {
    return res.json(await abort());
  } catch (err) {
    return fail(res, err);
  }
});

adminRouter.get('/admin/projections/status', async (_req, res) => {
  try {
    return res.json({ ...(await status()), diagnostics: await diagnostics() });
  } catch (err) {
    return fail(res, err);
  }
});
