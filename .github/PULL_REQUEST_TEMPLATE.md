# Pull Request Template

## Description
<!-- Clear description of what this PR does -->

## Type of Change
- [ ] Bug fix (non-breaking change that fixes an issue)
- [ ] New feature (non-breaking change that adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to not work as expected)
- [ ] Documentation update
- [ ] Refactoring / Code quality
- [ ] CI/CD / Infrastructure
- [ ] Tests

## Related Issues
<!-- Link to issues: Fixes #123, Relates to #456 -->

## Changes Made
- 
- 

## Testing
- [ ] All existing tests pass (`pytest`)
- [ ] New tests added for the changes
- [ ] Manual testing performed:
  - [ ] API endpoints tested
  - [ ] Database migrations verified
  - [ ] Docker build successful
- [ ] Coverage maintained/improved (target: ≥80%)

## Checklist
- [ ] Code follows style guidelines (`ruff check .`, `ruff format --check .`)
- [ ] Type checking passes (`mypy app`)
- [ ] No new `ruff` or `mypy` suppressions without justification
- [ ] Self-review completed
- [ ] Documentation updated (README, docstrings, CHANGELOG if applicable)
- [ ] No secrets or credentials committed
- [ ] `.env.example` updated if new env vars added
- [ ] Database migrations included if schema changed (`alembic revision --autogenerate`)

## Screenshots / Logs (if applicable)
<!-- Add screenshots, curl commands, or relevant logs -->

## Deployment Notes
<!-- Any special deployment considerations? Database migrations? Config changes? -->