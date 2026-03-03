# GitHub Pages Setup

This guide explains how to enable GitHub Pages for the documentation site.

## Prerequisites

- Repository pushed to GitHub
- Admin access to repository settings

## Setup Steps

### 1. Enable GitHub Pages

1. Go to your repository on GitHub
2. Click **Settings** (top menu)
3. Scroll down to **Pages** (left sidebar)
4. Under **Build and deployment**:
   - **Source**: Select "GitHub Actions"
   - (Don't select "Deploy from a branch")

### 2. Configure Permissions

The workflow requires write permissions to deploy:

1. In repository **Settings**
2. Go to **Actions** → **General** (left sidebar)
3. Scroll to **Workflow permissions**
4. Select **Read and write permissions**
5. Check ✅ **Allow GitHub Actions to create and approve pull requests**
6. Click **Save**

### 3. Trigger Deployment

The documentation will automatically deploy when:

- Changes are pushed to `main` branch in `docs/` directory
- Changes are made to `mkdocs.yml`
- Workflow is manually triggered

**Manual Trigger**:

1. Go to **Actions** tab
2. Click "Deploy Documentation" workflow
3. Click **Run workflow**
4. Select branch (usually `main`)
5. Click **Run workflow** button

### 4. Verify Deployment

After the workflow completes (2-3 minutes):

1. Go to **Settings** → **Pages**
2. You should see: "Your site is live at https://bvandewe.github.io/lablet-cloud-manager"
3. Click the URL to view the documentation

## Troubleshooting

### Pages Not Enabled

**Error**: "GitHub Pages is not enabled for this repository"

**Solution**: Follow Step 1 above to enable Pages with "GitHub Actions" source

### Permission Denied

**Error**: "Error: Unable to deploy" or "Permission denied"

**Solution**:

1. Check workflow permissions (Step 2)
2. Ensure you have admin access to the repository

### Build Failed

**Error**: Workflow fails during build step

**Solution**:

1. Check the workflow logs in Actions tab
2. Verify `mkdocs.yml` is valid: `make docs-build`
3. Ensure all documentation files exist and are valid Markdown

### Site Not Updating

**Symptom**: Changes not visible on GitHub Pages

**Solution**:

1. Check if workflow completed successfully in Actions tab
2. Hard refresh browser: Ctrl+Shift+R (Windows) or Cmd+Shift+R (Mac)
3. Wait a few minutes for GitHub CDN to update
4. Check if changes were pushed to `main` branch

### Custom Domain (Optional)

To use a custom domain:

1. Go to **Settings** → **Pages**
2. Under **Custom domain**, enter your domain
3. Add DNS records as instructed
4. Wait for DNS propagation (can take up to 48 hours)

## Local Testing

Before pushing, test documentation locally:

```bash
# Install dependencies
make docs-install

# Serve locally
make docs-serve

# Build to verify
make docs-build
```

Visit http://127.0.0.1:8000 to preview.

## Workflow Overview

The GitHub Actions workflow (`.github/workflows/docs.yml`):

1. **Build Job**:
   - Checks out code
   - Installs Python 3.11
   - Installs MkDocs dependencies
   - Builds documentation with `mkdocs build --strict`
   - Uploads site artifact

2. **Deploy Job** (only on `main` push):
   - Downloads build artifact
   - Deploys to GitHub Pages

3. **PR Check Job** (pull requests only):
   - Builds documentation to verify
   - Comments on PR with status

## Updating Documentation

### Local Changes

```bash
# Make changes to docs/*.md files

# Preview locally
make docs-serve

# Commit and push
git add docs/
git commit -m "docs: update documentation"
git push origin main
```

GitHub Actions will automatically deploy the changes.

### Pull Request Workflow

1. Create branch: `git checkout -b docs/my-changes`
2. Make documentation changes
3. Push: `git push origin docs/my-changes`
4. Create pull request on GitHub
5. Workflow will verify build succeeds
6. After merge, documentation auto-deploys

## Manual Deployment

To deploy from local machine (requires push access):

```bash
# Install dependencies
make docs-install

# Deploy to GitHub Pages
make docs-deploy
```

This uses `mkdocs gh-deploy` which:

- Builds documentation
- Creates/updates `gh-pages` branch
- Pushes to GitHub

**Note**: Manual deployment is not needed with GitHub Actions enabled.

## Configuration Files

### `.github/workflows/docs.yml`

GitHub Actions workflow for automatic deployment.

**Triggers**:

- Push to `main` with changes in `docs/` or `mkdocs.yml`
- Pull requests to `main` (build check only)
- Manual workflow dispatch

### `mkdocs.yml`

MkDocs configuration file.

**Key settings**:

- `site_name`: Documentation site title
- `site_url`: Published URL (update for custom domain)
- `repo_url`: Link to GitHub repository
- `nav`: Documentation structure
- `theme`: Material theme configuration

### `Makefile`

Documentation commands:

```bash
make docs-install  # Install MkDocs
make docs-serve    # Local preview
make docs-build    # Build site
make docs-deploy   # Manual deploy
make docs-clean    # Clean build artifacts
```

## URLs

- **Live Site**: https://bvandewe.github.io/lablet-cloud-manager
- **Repository**: https://github.com/bvandewe/lablet-cloud-manager
- **Workflow**: https://github.com/bvandewe/lablet-cloud-manager/actions/workflows/docs.yml

## Support

If you encounter issues:

1. Check [Troubleshooting](#troubleshooting) section above
2. Review GitHub Actions logs in the Actions tab
3. Test documentation build locally
4. Check [MkDocs documentation](https://www.mkdocs.org/)
5. Check [GitHub Pages documentation](https://docs.github.com/en/pages)
