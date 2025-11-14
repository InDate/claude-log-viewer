# Publishing to PyPI

This guide explains how to publish `claude-log-viewer` to PyPI.

## Prerequisites

1. **PyPI Account**: Create accounts on both:
   - PyPI (production): https://pypi.org/account/register/
   - TestPyPI (testing): https://test.pypi.org/account/register/

2. **API Tokens**: Generate API tokens for authentication:
   - PyPI: https://pypi.org/manage/account/token/
   - TestPyPI: https://test.pypi.org/manage/account/token/

3. **Install build tools**:
   ```bash
   pip install --upgrade build twine
   ```

## Publishing Steps

### 1. Update Version Number

Edit `pyproject.toml` and increment the version:
```toml
version = "1.0.1"  # Change from 1.0.0
```

### 2. Build the Package

```bash
# Clean previous builds
rm -rf dist/ build/ *.egg-info

# Build source distribution and wheel
python -m build
```

This creates:
- `dist/claude-log-viewer-1.0.0.tar.gz` (source distribution)
- `dist/claude_log_viewer-1.0.0-py3-none-any.whl` (wheel)

### 3. Test on TestPyPI (Optional but Recommended)

```bash
# Upload to TestPyPI
python -m twine upload --repository testpypi dist/*

# Test installation
pip install --index-url https://test.pypi.org/simple/ claude-log-viewer
```

### 4. Publish to PyPI

```bash
# Upload to PyPI
python -m twine upload dist/*
```

You'll be prompted for:
- Username: `__token__`
- Password: Your PyPI API token (starts with `pypi-`)

### 5. Verify Installation

```bash
# Install from PyPI
pip install claude-log-viewer

# Test it works
claude-log-viewer --help
```

### 6. Create GitHub Release

```bash
# Tag the release
git tag v1.0.0
git push origin v1.0.0

# Create release on GitHub
gh release create v1.0.0 \
  --title "v1.0.0 - Initial Release" \
  --notes "See CHANGELOG.md for details"
```

## Using GitHub Actions (Automated)

For automated releases, we can set up GitHub Actions. See `.github/workflows/publish.yml`.

## Version Numbering

Follow semantic versioning (SemVer):
- **Major** (1.x.x): Breaking changes
- **Minor** (x.1.x): New features, backward compatible
- **Patch** (x.x.1): Bug fixes

## Checklist Before Publishing

- [ ] All tests pass (`pytest`)
- [ ] README is up to date
- [ ] Version number incremented in `pyproject.toml`
- [ ] CHANGELOG updated (if exists)
- [ ] No sensitive data in repository
- [ ] All files included in MANIFEST.in
- [ ] Package builds without errors
- [ ] Tested on TestPyPI

## Troubleshooting

### Missing Files in Package

Check `MANIFEST.in` includes all necessary files:
```
include README.md
include LICENSE
include INSTALL.md
recursive-include claude_log_viewer/templates *.html
recursive-include claude_log_viewer/static *
```

### Import Errors After Install

Verify `pyproject.toml` package-data includes static files:
```toml
[tool.setuptools.package-data]
claude_log_viewer = ["templates/*.html", "static/css/*.css", "static/js/*.js"]
```

### Authentication Failed

- Use `__token__` as username (not your PyPI username)
- Use API token as password (not your account password)
- Token must start with `pypi-` for PyPI or `pypi-` for TestPyPI

## Resources

- PyPI: https://pypi.org/
- TestPyPI: https://test.pypi.org/
- Packaging Guide: https://packaging.python.org/
- Twine Docs: https://twine.readthedocs.io/
