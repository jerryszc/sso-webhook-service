# Security Policy

## Supported Versions

We actively maintain and provide security updates for the following versions:

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |

## Reporting a Vulnerability

We take security seriously. If you discover a security vulnerability, please report it responsibly:

### Preferred: GitHub Security Advisories
1. Go to the **Security** tab of this repository
2. Click **Report a vulnerability**
3. Fill in the details privately

### Alternative: Email
Send details to: **security@yourdomain.com** (replace with your contact)

### What to Include
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

### Response Timeline
- **Acknowledgment**: Within 48 hours
- **Initial Assessment**: Within 5 business days
- **Fix Timeline**: Depends on severity (critical: 7 days, high: 30 days, medium: 90 days)

## Security Best Practices for Contributors

- Never commit secrets, API keys, or credentials
- Use `.env.example` for documenting required environment variables
- Keep dependencies updated (Dependabot alerts enabled)
- Run `ruff check` and `mypy` before submitting PRs
- All PRs require passing CI checks before merge

## Scope

This policy covers:
- Application code in `app/`
- Infrastructure code (Docker, docker-compose, GitHub Actions)
- Configuration files (`pyproject.toml`, `requirements.txt`)

Out of scope:
- Third-party dependencies (report to their maintainers)
- Infrastructure not managed in this repository