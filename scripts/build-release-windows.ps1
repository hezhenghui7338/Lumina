# Windows release packaging is discontinued.
# Official releases only ship macOS via ./scripts/build-release.sh and
# .github/workflows/release.yml. The WinUI app under apps/windows remains for
# local development; do not re-enable CI packaging without an explicit request.
$ErrorActionPreference = "Stop"
Write-Error @"
Windows release packaging is disabled.

Use macOS packaging instead:
  ./scripts/build-release.sh
  # or: just release

See docs/RELEASE.md and .cursor/skills/build-release/SKILL.md.
"@
exit 1
