# Maritime deployment

The main branch is the deployment source. The Dockerfile downloads the pinned
official AIStudio2API Linux amd64 release, checks its SHA-256 and extracts the
binary from the version-named directory. The tracked legacy binary is not used.

## Automatic upstream updates

The Sync AIStudio2API upstream GitHub Actions workflow wakes hourly at minute
17 (UTC) and checks releases at least five hours after its last successful check,
matching daili's interval gate. Manual runs bypass the gate; redeploy=true
rebuilds and verifies main even when no new version exists.

The repository secret MARITIME_TOKEN must authorize agent
91a5b393-da23-430e-b333-8ed1b9d3408f. No key belongs in source control.
The workflow uses its built-in GITHUB_TOKEN to commit version/checksum changes
directly to main, then deploys in the same run (bot pushes do not trigger a
second workflow).

For a newer stable release, it validates the official asset URL and checksum,
builds and smoke-tests the image, commits the two version pins to main, then
deploys main. It waits for that deployment and verifies runtime version/readiness
plus real Flash and Argon /v1/responses requests containing 72 tools, including
the array without items that previously failed. Existing worker limits, timeouts,
auth path and API key fingerprint must remain unchanged.

On failure it reverts its own version commit and redeploys the previous version,
then performs the same inference checks. It will not overwrite a concurrently
changed main. An ambiguous deployment POST is not retried; rollback waits for
in-flight deployments first. A failed check is not cached as successful.

The updater fails closed if the release format/checksum changes or upstream
requires a different Camoufox version; update image compatibility manually before
retrying. GitHub schedule delivery may be delayed, and cache eviction may cause
an earlier extra check, not an unnecessary redeployment.

## Verification

    python3 -m unittest discover -s tests -v
    bash scripts/smoke_image.sh

Only /data is persistent on Maritime. Do not replace the live /app binary as an
upgrade mechanism. The runtime requires a writable request ledger.
