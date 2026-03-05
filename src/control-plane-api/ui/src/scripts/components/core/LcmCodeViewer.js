/**
 * LcmCodeViewer — Lightweight read-only code viewer component.
 *
 * Provides a Monaco-like UX with:
 * - Syntax highlighting (via highlight.js)
 * - Line numbers (CSS counters)
 * - Tabbed file switcher
 * - Copy to clipboard button
 * - Word-wrap toggle
 * - Collapsible (accordion-friendly)
 *
 * Usage:
 *   const viewer = document.createElement('lcm-code-viewer');
 *   viewer.setFiles([
 *       { name: 'cml.yaml', content: '...', language: 'yaml' },
 *       { name: 'devices.json', content: '...', language: 'json' },
 *   ]);
 *   container.appendChild(viewer);
 *
 * Or with attributes:
 *   <lcm-code-viewer language="yaml" filename="cml.yaml"></lcm-code-viewer>
 *   viewer.setContent(yamlString);
 *
 * @module components/core/LcmCodeViewer
 */

import hljs from 'highlight.js/lib/core';
import yaml from 'highlight.js/lib/languages/yaml';
import json from 'highlight.js/lib/languages/json';
import xml from 'highlight.js/lib/languages/xml';
import plaintext from 'highlight.js/lib/languages/plaintext';

// Register only the languages we need (tree-shaking friendly)
hljs.registerLanguage('yaml', yaml);
hljs.registerLanguage('json', json);
hljs.registerLanguage('xml', xml);
hljs.registerLanguage('plaintext', plaintext);

const STYLES = `
<style>
    :host {
        display: block;
        font-family: 'Cascadia Code', 'Fira Code', 'JetBrains Mono', 'Consolas', 'Monaco', monospace;
        font-size: 13px;
    }

    .code-viewer {
        border: 1px solid var(--bs-border-color, #dee2e6);
        border-radius: 6px;
        overflow: hidden;
        background: #1e1e1e;
        color: #d4d4d4;
    }

    /* Toolbar */
    .code-toolbar {
        display: flex;
        align-items: center;
        justify-content: space-between;
        background: #2d2d2d;
        border-bottom: 1px solid #404040;
        padding: 0;
        min-height: 36px;
    }

    .code-tabs {
        display: flex;
        overflow-x: auto;
        scrollbar-width: none;
        flex: 1;
    }

    .code-tabs::-webkit-scrollbar { display: none; }

    .code-tab {
        padding: 6px 14px;
        cursor: pointer;
        color: #999;
        font-size: 12px;
        white-space: nowrap;
        border-right: 1px solid #404040;
        transition: color 0.15s, background 0.15s;
        user-select: none;
    }

    .code-tab:hover {
        color: #ccc;
        background: #333;
    }

    .code-tab.active {
        color: #fff;
        background: #1e1e1e;
        border-bottom: 2px solid #0078d4;
    }

    .code-tab .tab-icon {
        margin-right: 4px;
        font-size: 11px;
    }

    .code-actions {
        display: flex;
        align-items: center;
        padding: 0 8px;
        gap: 4px;
    }

    .code-action-btn {
        background: transparent;
        border: none;
        color: #999;
        cursor: pointer;
        padding: 4px 6px;
        border-radius: 3px;
        font-size: 12px;
        transition: color 0.15s, background 0.15s;
        display: flex;
        align-items: center;
        gap: 4px;
    }

    .code-action-btn:hover {
        color: #fff;
        background: #404040;
    }

    .code-action-btn.active {
        color: #0078d4;
    }

    .code-action-btn .copy-feedback {
        font-size: 11px;
    }

    /* Code area */
    .code-container {
        position: relative;
        overflow: auto;
        max-height: 500px;
    }

    .code-container pre {
        margin: 0;
        padding: 0;
        background: transparent;
    }

    .code-container code {
        display: block;
        padding: 12px 12px 12px 0;
        counter-reset: line;
        background: transparent;
        tab-size: 2;
    }

    /* Line numbers via CSS counters */
    .code-container code .line {
        display: block;
        padding-left: 56px;
        position: relative;
        min-height: 20px;
        line-height: 20px;
    }

    .code-container code .line::before {
        content: counter(line);
        counter-increment: line;
        position: absolute;
        left: 0;
        width: 44px;
        text-align: right;
        color: #555;
        font-size: 12px;
        padding-right: 12px;
        border-right: 1px solid #333;
        user-select: none;
    }

    /* Word wrap toggle */
    .code-container.word-wrap code .line {
        white-space: pre-wrap;
        word-break: break-all;
    }

    /* Info bar */
    .code-info {
        display: flex;
        align-items: center;
        justify-content: space-between;
        background: #2d2d2d;
        border-top: 1px solid #404040;
        padding: 3px 12px;
        font-size: 11px;
        color: #888;
    }

    /* Empty state */
    .code-empty {
        padding: 32px;
        text-align: center;
        color: #666;
        font-style: italic;
    }

    /* highlight.js GitHub Dark theme (subset) */
    .hljs-keyword { color: #c586c0; }
    .hljs-string { color: #ce9178; }
    .hljs-number { color: #b5cea8; }
    .hljs-literal { color: #569cd6; }
    .hljs-attr { color: #9cdcfe; }
    .hljs-built_in { color: #dcdcaa; }
    .hljs-comment { color: #6a9955; font-style: italic; }
    .hljs-tag { color: #569cd6; }
    .hljs-name { color: #569cd6; }
    .hljs-attribute { color: #9cdcfe; }
    .hljs-meta { color: #d7ba7d; }
    .hljs-section { color: #569cd6; }
    .hljs-type { color: #4ec9b0; }
    .hljs-bullet { color: #d4d4d4; }
    .hljs-symbol { color: #b5cea8; }
    .hljs-selector-tag { color: #d7ba7d; }
</style>
`;

const FILE_ICONS = {
    yaml: '📄',
    yml: '📄',
    json: '📋',
    xml: '📝',
    default: '📎',
};

function getFileIcon(language) {
    return FILE_ICONS[language] || FILE_ICONS.default;
}

export class LcmCodeViewer extends HTMLElement {
    constructor() {
        super();
        this.attachShadow({ mode: 'open' });
        this._files = [];
        this._activeIndex = 0;
        this._wordWrap = false;
    }

    connectedCallback() {
        this._render();
    }

    /**
     * Set multiple files for tabbed viewing.
     * @param {Array<{name: string, content: string, language: string}>} files
     */
    setFiles(files) {
        this._files = files.filter(f => f.content); // Skip files with no content
        this._activeIndex = 0;
        this._render();
    }

    /**
     * Set a single file's content (for attribute-based usage).
     * @param {string} content
     */
    setContent(content) {
        const filename = this.getAttribute('filename') || 'file';
        const language = this.getAttribute('language') || 'plaintext';
        this._files = [{ name: filename, content, language }];
        this._activeIndex = 0;
        this._render();
    }

    _render() {
        if (!this._files.length) {
            this.shadowRoot.innerHTML = `${STYLES}<div class="code-viewer"><div class="code-empty">No content available</div></div>`;
            return;
        }

        const activeFile = this._files[this._activeIndex];
        const highlighted = this._highlight(activeFile.content, activeFile.language);
        const lineCount = activeFile.content.split('\n').length;
        const sizeKb = (new TextEncoder().encode(activeFile.content).length / 1024).toFixed(1);

        const tabsHtml =
            this._files.length > 1
                ? this._files
                      .map(
                          (f, i) => `
                <div class="code-tab ${i === this._activeIndex ? 'active' : ''}" data-tab="${i}">
                    <span class="tab-icon">${getFileIcon(f.language)}</span>${this._escapeHtml(f.name)}
                </div>
            `
                      )
                      .join('')
                : `<div class="code-tab active">
                <span class="tab-icon">${getFileIcon(activeFile.language)}</span>${this._escapeHtml(activeFile.name)}
            </div>`;

        this.shadowRoot.innerHTML = `
            ${STYLES}
            <div class="code-viewer">
                <div class="code-toolbar">
                    <div class="code-tabs">${tabsHtml}</div>
                    <div class="code-actions">
                        <button class="code-action-btn" data-action="wrap" title="Toggle Word Wrap">
                            ${this._wordWrap ? '↩ Unwrap' : '↩ Wrap'}
                        </button>
                        <button class="code-action-btn" data-action="copy" title="Copy to Clipboard">
                            📋 Copy
                        </button>
                    </div>
                </div>
                <div class="code-container ${this._wordWrap ? 'word-wrap' : ''}">
                    <pre><code>${highlighted}</code></pre>
                </div>
                <div class="code-info">
                    <span>${activeFile.language.toUpperCase()} • ${lineCount} lines • ${sizeKb} KB</span>
                    <span>${activeFile.name}</span>
                </div>
            </div>
        `;

        this._setupHandlers();
    }

    _highlight(content, language) {
        let highlighted;
        try {
            const result = hljs.highlight(content, { language: language || 'plaintext' });
            highlighted = result.value;
        } catch {
            highlighted = this._escapeHtml(content);
        }

        // Wrap each line in a <span class="line"> for line numbering
        return highlighted
            .split('\n')
            .map(line => `<span class="line">${line || ' '}</span>`)
            .join('\n');
    }

    _setupHandlers() {
        // Tab switching
        this.shadowRoot.querySelectorAll('.code-tab[data-tab]').forEach(tab => {
            tab.addEventListener('click', () => {
                this._activeIndex = parseInt(tab.dataset.tab, 10);
                this._render();
            });
        });

        // Copy
        const copyBtn = this.shadowRoot.querySelector('[data-action="copy"]');
        if (copyBtn) {
            copyBtn.addEventListener('click', async () => {
                const file = this._files[this._activeIndex];
                try {
                    await navigator.clipboard.writeText(file.content);
                    copyBtn.innerHTML = '✅ Copied!';
                    setTimeout(() => {
                        copyBtn.innerHTML = '📋 Copy';
                    }, 2000);
                } catch {
                    // Fallback for older browsers
                    const ta = document.createElement('textarea');
                    ta.value = file.content;
                    document.body.appendChild(ta);
                    ta.select();
                    document.execCommand('copy');
                    document.body.removeChild(ta);
                    copyBtn.innerHTML = '✅ Copied!';
                    setTimeout(() => {
                        copyBtn.innerHTML = '📋 Copy';
                    }, 2000);
                }
            });
        }

        // Word wrap toggle
        const wrapBtn = this.shadowRoot.querySelector('[data-action="wrap"]');
        if (wrapBtn) {
            wrapBtn.addEventListener('click', () => {
                this._wordWrap = !this._wordWrap;
                this._render();
            });
        }
    }

    _escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

// Register the custom element
if (!customElements.get('lcm-code-viewer')) {
    customElements.define('lcm-code-viewer', LcmCodeViewer);
}
