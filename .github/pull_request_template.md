## Summary

-

## Validation

- [ ] `python -m unittest discover -s tests -v`
- [ ] `python scripts/check_fixture_sync.py`
- [ ] `python scripts/release_gate.py --skip-npm-install`
- [ ] `git diff --check`

## Safety

- [ ] No Keepa API key, `.env`, local cache, or unredacted cassette is committed.
- [ ] Live Keepa calls are not required for default CI.
- [ ] Agent/MCP JSON contracts and fixtures are updated when behavior changes.
