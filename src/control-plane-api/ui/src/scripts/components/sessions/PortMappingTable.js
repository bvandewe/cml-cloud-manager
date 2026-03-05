/**
 * PortMappingTable — Phase 11 (P11-17)
 *
 * Displays resolved device port allocations for a LabletRecordRun.
 * Port mappings are frozen at run creation for LDS/grading stability.
 *
 * Architecture ref: §3.4 (LabletRecordRun.allocated_ports), §9.3 (port mapping table).
 *
 * Usage:
 *   <port-mapping-table></port-mapping-table>
 *   // then: element.setPorts({ node_label: { protocol, external_port, internal_port, host } })
 *
 * @module components/sessions/PortMappingTable
 */

import { BaseComponent } from '../../core/BaseComponent.js';

export class PortMappingTable extends BaseComponent {
    static get observedAttributes() {
        return ['compact'];
    }

    constructor() {
        super();
        this._ports = {};
    }

    onMount() {
        this.render();
    }

    onAttributeChange() {
        this.render();
    }

    /**
     * Set port mappings data
     * @param {Object} ports - Port allocations keyed by node_label
     *   Each value: { protocol, external_port, internal_port, host } or array of such objects
     */
    setPorts(ports) {
        this._ports = ports || {};
        this.render();
    }

    /**
     * Flatten port mappings into table rows
     */
    _flattenPorts() {
        const rows = [];
        Object.entries(this._ports).forEach(([nodeLabel, portInfo]) => {
            if (Array.isArray(portInfo)) {
                portInfo.forEach(p => {
                    rows.push({ node_label: nodeLabel, ...p });
                });
            } else if (portInfo && typeof portInfo === 'object') {
                rows.push({ node_label: nodeLabel, ...portInfo });
            }
        });
        return rows;
    }

    render() {
        const rows = this._flattenPorts();
        const isCompact = this.hasAttribute('compact');

        if (rows.length === 0) {
            this.innerHTML = `
                <div class="text-muted small py-2">
                    <i class="bi bi-ethernet me-1"></i>No port mappings available
                </div>
            `;
            return;
        }

        const tableClass = isCompact ? 'table table-sm table-borderless mb-0' : 'table table-sm table-hover mb-0';

        this.innerHTML = `
            <div class="table-responsive">
                <table class="${tableClass}">
                    <thead>
                        <tr class="text-muted small">
                            <th>Device</th>
                            <th>Protocol</th>
                            <th>External</th>
                            <th>Internal</th>
                            ${isCompact ? '' : '<th>Host</th>'}
                            ${isCompact ? '' : '<th>Access</th>'}
                        </tr>
                    </thead>
                    <tbody>
                        ${rows.map(row => this._renderRow(row, isCompact)).join('')}
                    </tbody>
                </table>
            </div>
        `;
    }

    _renderRow(row, isCompact) {
        const protocol = (row.protocol || 'tcp').toUpperCase();
        const extPort = row.external_port ?? '—';
        const intPort = row.internal_port ?? '—';
        const host = row.host || '—';
        const nodeLabel = row.node_label || 'Unknown';

        const protocolIcon = protocol === 'SSH' ? 'bi-terminal' : protocol === 'HTTP' || protocol === 'HTTPS' ? 'bi-globe' : 'bi-ethernet';

        // Build access URL if we have enough info
        let accessHtml = '';
        if (!isCompact && host !== '—' && extPort !== '—') {
            if (['HTTP', 'HTTPS'].includes(protocol)) {
                const scheme = protocol.toLowerCase();
                accessHtml = `<a href="${scheme}://${host}:${extPort}" target="_blank" rel="noopener" class="btn btn-sm btn-outline-primary py-0 px-1">
                    <i class="bi bi-box-arrow-up-right me-1"></i>Open
                </a>`;
            } else if (protocol === 'SSH') {
                accessHtml = `<code class="small user-select-all">ssh -p ${extPort} ${host}</code>`;
            } else {
                accessHtml = `<code class="small user-select-all">${host}:${extPort}</code>`;
            }
        }

        return `
            <tr>
                <td>
                    <span class="fw-medium">${this._escapeHtml(nodeLabel)}</span>
                </td>
                <td>
                    <i class="${protocolIcon} me-1 text-muted"></i>
                    <span class="badge bg-light text-dark border">${protocol}</span>
                </td>
                <td><code class="small">${extPort}</code></td>
                <td><code class="small">${intPort}</code></td>
                ${isCompact ? '' : `<td class="text-truncate small" style="max-width: 150px;">${this._escapeHtml(String(host))}</td>`}
                ${isCompact ? '' : `<td>${accessHtml}</td>`}
            </tr>
        `;
    }

    _escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }
}

if (!customElements.get('port-mapping-table')) {
    customElements.define('port-mapping-table', PortMappingTable);
}

export default PortMappingTable;
