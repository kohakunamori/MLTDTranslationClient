# Project Maintenance & CI Rules

## Required Verification Checks
Run all three checks after modifying repository content, scripts, manifests, or tests:
1. `python -m scripts.validate_repo`
2. `python -m unittest discover -s tests`
3. `python -m scripts.build_portal_resource_manifest` (ensure `manifests/portal-resource-manifest.json` stays in sync; stage it if its content changes)

## GitHub Actions Rules
- Always validate YAML syntax with Python `yaml.safe_load` after modifying `.github/workflows/*.yml`.
- Never use unverified GitHub Actions version tags; verify tags exist upstream before pinning or upgrading (e.g., `astral-sh/setup-uv@v10.3.3`, `actions/checkout@v7`).
