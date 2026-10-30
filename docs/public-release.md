# Public v0.1.2 lineage

This repository starts a clean public history from the audited local v0.1.2 source baseline `8389dc96e61e840934b6a6a3b427c107494db9a3`. That private baseline commit and its earlier tags are not published Git objects here. The public commit therefore has a different identity; the public `v0.1.2` tag identifies this repository's sanitized release.

Every byte in `copier.yml` and `template/` is preserved from the audited baseline. The sorted relative-path/content SHA-256 is `016aa8fade38b48418b2ab18ff11da931d72aa048782189d91932414c91e2fe2` (for each file, hash UTF-8 relative path, NUL, then bytes; sort paths first).

Publication changes are limited to documentation privacy and repository bootstrapping:

- Remove historical machine-specific verification files and private pilot records; retain a concise verification scope and reusable evaluation design.
- Document the public repository URL and stable local/public Copier source alternatives.
- Start real-release upgrade tests at the first public tag, v0.1.2, because private v0.1.0/v0.1.1 commits and tags are not imported. The candidate fixture allows identical template content at the first release while still creating and verifying a distinct revision and updated lineage. Synthetic version/update fixtures retain the checks for changed content, user edits, deletions and conflicts.
- Fetch full Git history/tags in the foundation workflow so those upgrade tests run in GitHub Actions. Create the ignored artifact parent before invoking pytest with a nested base directory; a fresh-checkout run exposed this missing setup step.
- Use the owner's GitHub noreply commit identity; no personal email, environment, cache, runtime artifact or credential is imported.

The audited local repository remains unchanged. Future public releases should preserve public tags and use ordinary reviewed Copier updates. Existing projects pointing at another template source require a separate migration; do not hand-edit their answers file.

No project license has been added or changed. Legitimate dependency license metadata is preserved.
