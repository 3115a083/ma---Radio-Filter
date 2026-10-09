# Security policy

Radio Filter is an experimental Music Assistant plugin. Please do not install unreviewed forks or downloaded Python scripts into a production Music Assistant server.

## Reporting a vulnerability

Report privately through GitHub **Security → Advisories → Report a vulnerability** (if enabled for the repository), or contact the repository maintainer privately. Do not open a public issue with credentials, attack steps for live targets or private radio URLs.

## Threat model

- The plugin runs with the Music Assistant server's Python permissions.
- Rule input and ICY metadata are untrusted. Never evaluate text as code.
- Stream-monitor requests must only reach public IP addresses; DNS rebinding and HTTP redirects must not be able to reach Home Assistant, the host network or cloud metadata endpoints.
- Music Assistant media URIs must be validated and the plugin must not deliberately start local files, shell commands or arbitrary URLs from rule settings.
- Monitor connections must have limits, timeouts and cleanup on unload.
- Any change to CI/workflows, Dockerfiles, addon packaging or network access deserves manual review.

## Maintainer checklist

Enable GitHub Rulesets for `main`: require pull requests, code-owner review, successful tests, block force pushes and branch deletion, and disallow bypasses. Enable secret scanning, Dependabot alerts and private vulnerability reporting in repository Settings → Security & analysis where available. Restrict Actions to trusted sources and review Dependabot PRs before merging. Use two-factor authentication/passkeys for maintainers and least-privilege tokens.

CI is only a safeguard. Review commits before installing; a successful syntax or unit test run does **not** certify that a server is safe from all attacks.
