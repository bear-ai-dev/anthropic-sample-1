import { Router } from 'express';

import { dispatch } from '../intake/dispatch';
import { parseEnvelope } from '../intake/parseEnvelope';

/**
 * The intake route.
 *
 * Validates against the catalog, then hands the delivery to the dispatcher and
 * answers with where it went. A delivery that does not validate is the caller's
 * mistake and is refused; a delivery that validates is always accepted, even
 * when it cannot be placed yet.
 */
export function intakeRouter(): Router {
  const router = Router();

  router.post('/v1/intake/envelope', async (req, res) => {
    const parsed = parseEnvelope(req.body);
    if (!parsed.ok) {
      res.status(400).json({ error: 'envelope did not validate', details: parsed.errors });
      return;
    }

    try {
      const outcome = await dispatch(parsed.parsed);
      res.status(200).json(outcome);
    } catch (error) {
      // Nothing was committed: the decision runs in one transaction that has
      // already rolled back. The gateway may present the delivery again and it
      // will be treated as the first sight of it.
      res.status(500).json({ error: 'intake failed', detail: String(error) });
    }
  });

  return router;
}
