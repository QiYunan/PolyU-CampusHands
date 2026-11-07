## Change and reason

Describe the behavior changed and link the relevant milestone or acceptance scenario.

## Checks

- [ ] Backend full pytest (Mock/offline)
- [ ] Frontend test, lint and build
- [ ] Demo reset/preflight or browser rehearsal where relevant
- [ ] `python scripts/check_tracked_artifacts.py` and `git diff --check`
- [ ] Docs, acceptance scenarios and milestone scope checked

List any check not run and why.

## Demo and privacy review

- [ ] Demo data is fictional; no `.env`, key, database, log, model file or real student data is included
- [ ] Provider mode and any Mock result are clearly labelled
- [ ] Public UI/timeline contains no hidden reasoning, raw model output or tool arguments
- [ ] Request, Offer and completion state still come from the service
