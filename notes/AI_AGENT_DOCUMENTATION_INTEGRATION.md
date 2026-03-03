# AI Agent Documentation Integration

**Date**: November 17, 2025
**Status**: Implemented ✅

## Overview

The `.github/copilot-instructions.md` file is now automatically included in the MkDocs documentation site, ensuring a single source of truth for AI agent instructions that's accessible to both AI agents and human developers.

## Implementation

### 1. MkDocs Configuration

Updated `mkdocs.yml` to enable the PyMdown Snippets extension:

```yaml
markdown_extensions:
    - pymdownx.snippets:
          base_path: ['.']
          check_paths: true
```

This allows us to include external files using the `--8<--` syntax.

### 2. Documentation Page

Created `docs/development/ai-agent-guide.md` that includes the copilot instructions:

```markdown
## AI Agent Instructions

--8<-- ".github/copilot-instructions.md"
```

### 3. Navigation

Added the AI Agent Guide to the MkDocs navigation in `mkdocs.yml`:

```yaml
- Development:
    - AI Agent Guide: development/ai-agent-guide.md
    - Testing Guide: development/testing.md
    - ...
```

### 4. Cross-References

Updated references in:

- `docs/index.md` - Documentation map
- `README.md` - Documentation topics list

## Benefits

1. **Single Source of Truth**: `.github/copilot-instructions.md` is the only file to maintain
2. **Automatic Sync**: MkDocs site always shows current instructions
3. **Dual Audience**: Same content serves AI agents and human developers
4. **Version Control**: Changes tracked in git history
5. **Discoverable**: Linked from main documentation and README

## File Locations

- **Source**: `.github/copilot-instructions.md` (maintained manually)
- **MkDocs page**: `docs/development/ai-agent-guide.md` (includes snippet)
- **Built output**: `site/development/ai-agent-guide/index.html` (auto-generated)
- **Online**: https://bvandewe.github.io/lablet-cloud-manager/development/ai-agent-guide/

## Maintenance Workflow

When updating AI agent instructions:

1. Edit `.github/copilot-instructions.md` (single source of truth)
2. Run `make docs-serve` to preview changes locally
3. Commit changes - MkDocs site will auto-rebuild
4. GitHub Pages will deploy updated documentation

No need to touch `docs/development/ai-agent-guide.md` - it automatically includes the latest content.

## Testing

Verify the snippet is working:

```bash
# Build docs
poetry run mkdocs build

# Check if content is included
grep -c "Architecture Overview" site/development/ai-agent-guide/index.html
# Should return 2 (once in TOC, once in content)
```

## References

- [PyMdown Snippets Documentation](https://facelessuser.github.io/pymdown-extensions/extensions/snippets/)
- [MkDocs Material - Content Tabs](https://squidfunk.github.io/mkdocs-material/reference/content-tabs/)
- `.github/copilot-instructions.md` - Source file
- `docs/development/ai-agent-guide.md` - Documentation page
