# Contributing

## Current contribution scope

The project is defining a stable extension contract and governance model. Contributions should improve the schema, validator, documentation, test coverage, or a narrowly scoped reference implementation. Do not introduce an unrestricted plugin loader or broad secret access as an early shortcut.

## Before opening a pull request

1. Explain the user problem and the extension contract affected.
2. Keep the change focused; avoid unrelated restructuring.
3. Add or update schema examples and tests for contract changes.
4. Run the local checks:
   ```sh
   python -m pip install -r requirements-dev.txt
   python -m unittest discover --start-directory tests --verbose
   python scripts/validate_manifests.py
   ```
5. Document any new capability, permission, network destination, external dependency, or execution surface.
6. Identify licensing and provenance for reused code or dependencies.

## Security requirements

- A declared capability is a request, not a grant.
- Do not add raw tokens, credentials, private URLs, or user data to the repository.
- New network access must be justified and narrow.
- New executable extension types require a threat-model update and an explicit architecture decision.
- Actions in workflows must be pinned to verified full commit SHAs, or use an approved lockfile mechanism.
- Do not use pull-request content as shell code or interpolate it into commands unsafely.

## Compatibility

Keep the manifest schema version and host API version distinct. Prefer additive optional fields. Breaking contract changes require migration examples and a compatibility note.

## License

By submitting a contribution, you agree that the contribution is offered under the repository's MIT license unless an alternate license is explicitly documented for the contribution.
