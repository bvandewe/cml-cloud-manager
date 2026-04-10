/**
 * SubServicesCard Web Component (Resource Scheduler variant)
 * Fetches and displays sub-service health from /admin/sub-services endpoint.
 * Shows health cards for Scheduler, Timeslot Manager, and Cleanup services.
 */
class SubServicesCard extends HTMLElement {
    constructor() {
        super();
        this.attachShadow({ mode: 'open' });
        this.refreshInterval = null;
    }

    static get observedAttributes() {
        return ['theme-color', 'refresh-interval'];
    }

    connectedCallback() {
        this.render();
        this.fetchData();

        const interval = parseInt(this.getAttribute('refresh-interval')) || 30000;
        this.refreshInterval = setInterval(() => this.fetchData(), interval);
    }

    disconnectedCallback() {
        if (this.refreshInterval) {
            clearInterval(this.refreshInterval);
        }
    }

    async fetchData() {
        try {
            const response = await fetch('/api/admin/sub-services');
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json();
            this.renderData(data);
        } catch (error) {
            this.renderError(error.message);
        }
    }

    render() {
        const themeColor = this.getAttribute('theme-color') || '#667eea';

        this.shadowRoot.innerHTML = `
            <style>
                :host { display: block; }
                .services-card {
                    background: white; border-radius: 12px; padding: 1.25rem;
                    box-shadow: 0 2px 10px rgba(0,0,0,0.1);
                    border-left: 4px solid ${themeColor};
                }
                .card-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 1rem; }
                .card-title { font-size: 1rem; font-weight: 600; color: #333; }
                .services-grid {
                    display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
                    gap: 1rem;
                }
                .service-box {
                    border: 1px solid #e5e7eb; border-radius: 8px; padding: 1rem;
                    background: #fafafa;
                }
                .service-header {
                    display: flex; align-items: center; justify-content: space-between;
                    margin-bottom: 0.75rem;
                }
                .service-name { font-size: 0.85rem; font-weight: 600; color: #333; }
                .service-status {
                    display: inline-flex; align-items: center; gap: 0.25rem;
                    padding: 0.15rem 0.5rem; border-radius: 9999px;
                    font-size: 0.7rem; font-weight: 600;
                }
                .service-status.running { background: #dcfce7; color: #15803d; }
                .service-status.leader { background: linear-gradient(135deg, #fbbf24, #f59e0b); color: #78350f; }
                .service-status.follower { background: #e5e7eb; color: #4b5563; }
                .service-status.stopped { background: #fee2e2; color: #dc2626; }
                .service-status.disabled { background: #f3f4f6; color: #6b7280; }
                .mini-stats {
                    display: grid; grid-template-columns: repeat(auto-fit, minmax(70px, 1fr));
                    gap: 0.5rem;
                }
                .mini-stat { text-align: center; }
                .mini-value { font-size: 1.1rem; font-weight: 700; color: #212529; }
                .mini-value.success { color: #15803d; }
                .mini-value.error { color: #dc2626; }
                .mini-value.info { color: ${themeColor}; }
                .mini-value.warning { color: #f59e0b; }
                .mini-label { font-size: 0.6rem; text-transform: uppercase; color: #6c757d; }
                .service-meta {
                    margin-top: 0.5rem; font-size: 0.7rem; color: #6b7280;
                    border-top: 1px solid #e5e7eb; padding-top: 0.5rem;
                }
                .service-error { color: #dc2626; font-size: 0.7rem; margin-top: 0.25rem; }
                .loading {
                    display: flex; align-items: center; gap: 0.5rem;
                    color: #6c757d; padding: 1rem 0;
                }
                .spinner {
                    width: 18px; height: 18px; border: 2px solid #e9ecef;
                    border-top-color: ${themeColor}; border-radius: 50%;
                    animation: spin 1s linear infinite;
                }
                @keyframes spin { to { transform: rotate(360deg); } }
                .error-msg { color: #dc3545; padding: 0.75rem; background: #fee2e2; border-radius: 8px; font-size: 0.85rem; }
                .last-update { font-size: 0.7rem; color: #6c757d; text-align: right; margin-top: 0.75rem; }
            </style>
            <div class="services-card">
                <div class="card-header">
                    <span class="card-title">🔧 Sub-Services Health</span>
                </div>
                <div id="content">
                    <div class="loading"><div class="spinner"></div><span>Loading sub-services...</span></div>
                </div>
            </div>
        `;
    }

    renderData(data) {
        const content = this.shadowRoot.getElementById('content');
        let html = '<div class="services-grid">';

        // Scheduler
        if (data.scheduler) {
            html += this.renderSchedulerBox(data.scheduler);
        }

        // Timeslot Manager
        if (data.timeslot_manager) {
            html += this.renderTimeslotBox(data.timeslot_manager);
        }

        // Cleanup
        if (data.cleanup) {
            html += this.renderCleanupBox(data.cleanup);
        }

        html += '</div>';
        html += `<div class="last-update">Updated: ${new Date().toLocaleTimeString()}</div>`;
        content.innerHTML = html;
    }

    renderSchedulerBox(sched) {
        const isLeader = sched.is_leader === true;
        const isRunning = sched.running === true;

        let statusCls, statusLabel;
        if (isLeader) {
            statusCls = 'leader';
            statusLabel = '👑 Leader';
        } else if (isRunning) {
            statusCls = 'running';
            statusLabel = '● Running';
        } else {
            statusCls = 'follower';
            statusLabel = '👤 Follower';
        }

        // Format last reconcile time
        let lastReconcile = 'Never';
        if (sched.last_reconcile_time) {
            lastReconcile = new Date(sched.last_reconcile_time * 1000).toLocaleTimeString();
        }

        return `
            <div class="service-box">
                <div class="service-header">
                    <span class="service-name">📅 Scheduler</span>
                    <span class="service-status ${statusCls}">${statusLabel}</span>
                </div>
                <div class="mini-stats">
                    <div class="mini-stat"><div class="mini-value success">${sched.successful_placements || 0}</div><div class="mini-label">Placed</div></div>
                    <div class="mini-stat"><div class="mini-value error">${sched.failed_placements || 0}</div><div class="mini-label">Failed</div></div>
                    <div class="mini-stat"><div class="mini-value info">${sched.scale_up_requests || 0}</div><div class="mini-label">Scale Up</div></div>
                    <div class="mini-stat"><div class="mini-value info">${sched.total_reconciled || 0}</div><div class="mini-label">Cycles</div></div>
                </div>
                <div class="service-meta">Last reconcile: ${lastReconcile}</div>
            </div>`;
    }

    renderTimeslotBox(ts) {
        if (ts.message === 'Not configured') {
            return `
                <div class="service-box">
                    <div class="service-header">
                        <span class="service-name">⏰ Timeslot Manager</span>
                        <span class="service-status disabled">Not Configured</span>
                    </div>
                </div>`;
        }

        const isLeader = ts.is_leader === true;
        const isEnabled = ts.enabled !== false;
        let statusCls, statusLabel;
        if (!isEnabled) {
            statusCls = 'disabled';
            statusLabel = 'Disabled';
        } else if (isLeader) {
            statusCls = 'leader';
            statusLabel = '👑 Leader';
        } else {
            statusCls = 'follower';
            statusLabel = '👤 Follower';
        }

        let metaHtml = '';
        if (ts.last_scan_at) {
            metaHtml = `<div class="service-meta">Last scan: ${new Date(ts.last_scan_at).toLocaleTimeString()}</div>`;
        }
        if (ts.last_error) {
            metaHtml += `<div class="service-error">⚠ ${ts.last_error}</div>`;
        }

        return `
            <div class="service-box">
                <div class="service-header">
                    <span class="service-name">⏰ Timeslot Manager</span>
                    <span class="service-status ${statusCls}">${statusLabel}</span>
                </div>
                <div class="mini-stats">
                    <div class="mini-stat"><div class="mini-value info">${ts.scan_count || 0}</div><div class="mini-label">Scans</div></div>
                    <div class="mini-stat"><div class="mini-value warning">${ts.triggers || 0}</div><div class="mini-label">Triggers</div></div>
                    <div class="mini-stat"><div class="mini-value error">${ts.expirations || 0}</div><div class="mini-label">Expirations</div></div>
                    <div class="mini-stat"><div class="mini-value info">${(ts.tracked_triggered || 0) + (ts.tracked_expired || 0)}</div><div class="mini-label">Tracked</div></div>
                </div>
                ${metaHtml}
            </div>`;
    }

    renderCleanupBox(cleanup) {
        if (cleanup.message === 'Not configured') {
            return `
                <div class="service-box">
                    <div class="service-header">
                        <span class="service-name">🧹 Cleanup</span>
                        <span class="service-status disabled">Not Configured</span>
                    </div>
                </div>`;
        }

        const isLeader = cleanup.is_leader === true;
        const isEnabled = cleanup.enabled !== false;
        let statusCls, statusLabel;
        if (!isEnabled) {
            statusCls = 'disabled';
            statusLabel = 'Disabled';
        } else if (isLeader) {
            statusCls = 'leader';
            statusLabel = '👑 Leader';
        } else {
            statusCls = 'follower';
            statusLabel = '👤 Follower';
        }

        let metaHtml = '';
        if (cleanup.last_cleanup_at) {
            metaHtml = `<div class="service-meta">Last cleanup: ${new Date(cleanup.last_cleanup_at).toLocaleTimeString()} | Retention: ${cleanup.retention_days || '—'}d</div>`;
        }

        return `
            <div class="service-box">
                <div class="service-header">
                    <span class="service-name">🧹 Cleanup</span>
                    <span class="service-status ${statusCls}">${statusLabel}</span>
                </div>
                <div class="mini-stats">
                    <div class="mini-stat"><div class="mini-value info">${cleanup.cleanup_runs || 0}</div><div class="mini-label">Runs</div></div>
                </div>
                ${metaHtml}
            </div>`;
    }

    renderError(message) {
        const content = this.shadowRoot.getElementById('content');
        content.innerHTML = `<div class="error-msg">Failed to load sub-services data: ${message}</div>`;
    }
}

customElements.define('sub-services-card', SubServicesCard);
