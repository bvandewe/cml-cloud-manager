/**
 * workerOverview.js
 * Pure rendering for worker AWS overview section.
 */

import { formatDateWithRelative, parseUTCDate } from '../utils/dates.js';
import { escapeHtml } from './escape.js';
import { isAdmin } from '../utils/roles.js';
import { getStatusBadgeClass, getServiceStatusBadgeClass } from './status-badges.js';

export function renderWorkerOverview(worker) {
    if (!worker) return '<div class="alert alert-warning">Worker data unavailable</div>';
    return `
    <div class="row mb-3" aria-label="Runtime infrastructure" role="group">
      <div class="col-12">
        <div class="d-flex align-items-center gap-2">
          <span class="badge bg-dark"><i class="bi bi-cloud"></i> AWS EC2</span>
          <span class="text-muted small">Runtime Infrastructure</span>
          <span class="text-muted small ms-auto">State Version: <code>${worker.state_version ?? 'N/A'}</code></span>
        </div>
      </div>
    </div>
    <div class="row" aria-label="Worker basic information" role="group">
      <div class="col-md-6">
        <h5 class="border-bottom pb-2 mb-3">Basic Information</h5>
        <table class="table table-sm table-borderless" aria-label="Basic worker attributes">
          <tr><td class="text-muted" width="40%">Name:</td><td><strong>${escapeHtml(worker.aws_tags?.Name || worker.name || 'N/A')}</strong>${worker.aws_tags?.Name && worker.name !== worker.aws_tags.Name ? `<br><span class="text-muted small">${escapeHtml(worker.name)}</span>` : ''}</td></tr>
          <tr><td class="text-muted">Worker ID:</td><td><code class="small">${worker.id}</code></td></tr>
          <tr><td class="text-muted">Instance ID:</td><td>${
              worker.aws_instance_id
                  ? `<code class="small">${worker.aws_instance_id}</code> <a href="https://${worker.aws_region}.console.aws.amazon.com/ec2/home?region=${worker.aws_region}#InstanceDetails:instanceId=${worker.aws_instance_id}" target="_blank" class="text-decoration-none ms-1" title="View in AWS Console" aria-label="Open in AWS Console"><i class="bi bi-box-arrow-up-right text-primary"></i></a>`
                  : '<span class="text-muted">N/A</span>'
          }</td></tr>
          <tr><td class="text-muted">Region:</td><td><span class="badge bg-secondary">${worker.aws_region}</span></td></tr>
          <tr><td class="text-muted">Instance Type:</td><td><span class="badge bg-info">${worker.instance_type}</span></td></tr>
          <tr><td class="text-muted">Status:</td><td><span class="badge ${getStatusBadgeClass(worker.status)}">${worker.status}</span>
            ${
                worker.status === 'pending' && worker.start_initiated_at
                    ? (() => {
                          try {
                              const startedMs = parseUTCDate(worker.start_initiated_at).getTime();
                              const diffSec = Math.max(0, Math.floor((Date.now() - startedMs) / 1000));
                              const m = Math.floor(diffSec / 60);
                              const s = diffSec % 60;
                              return `<div class='small text-muted mt-1 transition-duration' data-init-ts='${worker.start_initiated_at}' data-type='start'>Starting (<span class='elapsed'>${m}m ${s}s</span>)</div>`;
                          } catch (_) {
                              return `<div class='small text-muted mt-1'>Starting...</div>`;
                          }
                      })()
                    : ''
            }
            ${
                worker.status === 'stopping' && worker.stop_initiated_at
                    ? (() => {
                          try {
                              const stopMs = parseUTCDate(worker.stop_initiated_at).getTime();
                              const diffSec = Math.max(0, Math.floor((Date.now() - stopMs) / 1000));
                              const m = Math.floor(diffSec / 60);
                              const s = diffSec % 60;
                              return `<div class='small text-muted mt-1 transition-duration' data-init-ts='${worker.stop_initiated_at}' data-type='stop'>Stopping (<span class='elapsed'>${m}m ${s}s</span>)</div>`;
                          } catch (_) {
                              return `<div class='small text-muted mt-1'>Stopping...</div>`;
                          }
                      })()
                    : ''
            }
          </td></tr>
                    <tr><td class="text-muted">Service Status:</td><td><span class="badge ${getServiceStatusBadgeClass(worker.service_status)}">${worker.service_status}</span></td></tr>
        </table>
      </div>
      <div class="col-md-6">
        <h5 class="border-bottom pb-2 mb-3">AMI Information</h5>
        <table class="table table-sm table-borderless" aria-label="AMI information">
          <tr><td class="text-muted" width="40%">AMI ID:</td><td>${
              worker.ami_id
                  ? `<code class="small">${worker.ami_id}</code> <a href="https://${worker.aws_region}.console.aws.amazon.com/ec2/home?region=${worker.aws_region}#ImageDetails:imageId=${worker.ami_id}" target="_blank" class="text-decoration-none ms-1" title="View AMI in AWS Console" aria-label="Open AMI in AWS Console"><i class="bi bi-box-arrow-up-right text-primary"></i></a>`
                  : '<span class="text-muted">N/A</span>'
          }</td></tr>
          <tr><td class="text-muted">AMI Name:</td><td>${escapeHtml(worker.ami_name || 'N/A')}</td></tr>
          <tr><td class="text-muted">Description:</td><td>${escapeHtml(worker.ami_description || 'N/A')}</td></tr>
          <tr><td class="text-muted">Created:</td><td>${worker.ami_creation_date ? formatDateWithRelative(worker.ami_creation_date) : '<span class="text-muted">N/A</span>'}</td></tr>
        </table>
      </div>
    </div>
    <div class="row mt-3" aria-label="Network information" role="group">
      <div class="col-md-6">
        <h5 class="border-bottom pb-2 mb-3">Network</h5>
        <table class="table table-sm table-borderless" aria-label="Network attributes">
          <tr><td class="text-muted" width="40%">Public IP:</td><td>${worker.public_ip ? `<a href="https://${escapeHtml(worker.public_ip)}" target="_blank" class="text-decoration-none" title="Open via HTTPS">${escapeHtml(worker.public_ip)} <i class="bi bi-box-arrow-up-right small"></i></a>` : '<span class="text-muted">N/A</span>'}</td></tr>
          <tr><td class="text-muted">Private IP:</td><td>${worker.private_ip || '<span class="text-muted">N/A</span>'}</td></tr>
          <tr><td class="text-muted">HTTPS Endpoint:</td><td>${(() => {
              const endpoint = worker.https_endpoint;
              const fallbackUrl = worker.public_ip ? `https://${worker.public_ip}` : null;
              const displayUrl = endpoint || fallbackUrl;
              if (displayUrl) {
                  const label = endpoint ? escapeHtml(endpoint) : `${escapeHtml(fallbackUrl)} <span class="badge bg-warning text-dark ms-1" style="font-size: 0.7em;">via Public IP</span>`;
                  return `<a href="${escapeHtml(displayUrl)}" target="_blank" class="text-decoration-none" aria-label="Open HTTPS endpoint">${label} <i class="bi bi-box-arrow-up-right"></i></a>`;
              }
              return '<span class="text-muted">N/A</span>';
          })()}</td></tr>
        </table>
      </div>
      <div class="col-md-6">
        <h5 class="border-bottom pb-2 mb-3">Tags</h5>
        <div id="worker-tags-section" aria-label="AWS EC2 Instance Tags">
          <div id="worker-tags-list" class="mb-2">
            ${(() => {
                const tags = worker.aws_tags || {};
                const keys = Object.keys(tags);
                if (!keys.length) return '<span class="text-muted">No tags found</span>';
                return keys
                    .map(
                        k =>
                            `<span class="badge bg-light text-dark border me-1 mb-1 tag-item" data-tag-key="${escapeHtml(k)}" title="${escapeHtml(k)}: ${escapeHtml(tags[k])}">${escapeHtml(k)}: ${escapeHtml(tags[k])}${
                                isAdmin()
                                    ? ' <button type="button" class="btn btn-sm btn-outline-danger ms-1 p-0 px-1 remove-tag-btn" data-remove-tag="' + escapeHtml(k) + '" aria-label="Remove tag ' + escapeHtml(k) + '"><i class="bi bi-x"></i></button>'
                                    : ''
                            }</span>`
                    )
                    .join('');
            })()}
          </div>
          ${
              isAdmin()
                  ? `<form id="add-tag-form" class="row g-2" autocomplete="off" aria-label="Add tag form">
            <div class="col-5"><input type="text" class="form-control form-control-sm" id="new-tag-key" placeholder="Key" aria-label="Tag key" required maxlength="128"></div>
            <div class="col-5"><input type="text" class="form-control form-control-sm" id="new-tag-value" placeholder="Value" aria-label="Tag value" required maxlength="256"></div>
            <div class="col-2 d-grid"><button type="submit" class="btn btn-sm btn-outline-success" id="add-tag-btn" aria-label="Add tag"><i class="bi bi-plus"></i> Add</button></div>
            <div class="col-12"><div id="add-tag-feedback" class="small text-muted" aria-live="polite"></div></div>
          </form>`
                  : ''
          }
        </div>
      </div>
    </div>
    <div class="row mt-3" aria-label="Lifecycle information" role="group">
      <div class="col-md-6">
        <h5 class="border-bottom pb-2 mb-3">Lifecycle</h5>
        <table class="table table-sm table-borderless" aria-label="Lifecycle timestamps">
          <tr><td class="text-muted" width="40%"><i class="bi bi-plus-circle"></i> Created:</td><td>${formatDateWithRelative(worker.created_at)}</td></tr>
          <tr><td class="text-muted"><i class="bi bi-arrow-repeat"></i> Updated:</td><td>${formatDateWithRelative(worker.updated_at)}</td></tr>
          <tr><td class="text-muted"><i class="bi bi-clock-history"></i> Last Synced:</td><td>${worker.cml_last_synced_at ? formatDateWithRelative(worker.cml_last_synced_at) : '<span class="text-muted">N/A</span>'}</td></tr>
          <tr><td class="text-muted"><i class="bi bi-hourglass-split"></i> Next Refresh:</td><td>${worker.next_refresh_at ? formatDateWithRelative(worker.next_refresh_at) : '<span class="text-muted">N/A</span>'}</td></tr>
          <tr><td class="text-muted"><i class="bi bi-x-circle"></i> Terminated:</td><td>${worker.terminated_at ? formatDateWithRelative(worker.terminated_at) : '<span class="text-muted">N/A</span>'}</td></tr>
        </table>
      </div>
      <div class="col-md-6">
        <h5 class="border-bottom pb-2 mb-3">Activity & Usage</h5>
        <table class="table table-sm table-borderless" aria-label="Activity and usage statistics">
          <tr><td class="text-muted" width="40%">Running Labs:</td><td>${(() => {
              const count = worker.active_labs_count ?? worker.cml_labs_count ?? 0;
              return count > 0 ? `<span class="badge bg-info">${count}</span>` : '<span class="text-muted">0</span>';
          })()}</td></tr>
          <tr><td class="text-muted">Port Allocation:</td><td>${(() => {
              const allocated = worker.allocated_port_count;
              const available = worker.available_port_count;
              const pct = worker.port_utilization_pct;
              if (allocated == null && available == null) return '<span class="text-muted">N/A</span>';
              const usedCount = allocated ?? 0;
              const availCount = available ?? 0;
              const total = usedCount + availCount;
              const utilPct = pct != null ? parseFloat(pct).toFixed(1) : (total > 0 ? ((usedCount / total) * 100).toFixed(1) : '0.0');
              const barColor = utilPct > 80 ? 'bg-danger' : utilPct > 50 ? 'bg-warning' : 'bg-success';
              return `<span class="small">${usedCount} / ${total} ports</span>
                <div class="progress mt-1" style="height: 6px;" title="${utilPct}% port utilization">
                  <div class="progress-bar ${barColor}" role="progressbar" style="width: ${utilPct}%;" aria-valuenow="${utilPct}" aria-valuemin="0" aria-valuemax="100"></div>
                </div>`;
          })()}</td></tr>
          <tr><td class="text-muted">Resource Util:</td><td>${(() => {
              const cpu = worker.cpu_utilization;
              const mem = worker.memory_utilization;
              const disk = worker.disk_utilization ?? worker.storage_utilization;
              const parts = [];
              if (cpu != null) parts.push(`CPU ${parseFloat(cpu).toFixed(1)}%`);
              if (mem != null) parts.push(`Mem ${parseFloat(mem).toFixed(1)}%`);
              if (disk != null) parts.push(`Disk ${parseFloat(disk).toFixed(1)}%`);
              return parts.length > 0 ? `<span class="small">${parts.join(' · ')}</span>` : '<span class="text-muted">N/A</span>';
          })()}</td></tr>
          <tr><td class="text-muted">Pauses:</td><td>${(worker.auto_pause_count || 0) + (worker.manual_pause_count || 0)} <span class="text-muted small">(auto: ${worker.auto_pause_count || 0}, manual: ${worker.manual_pause_count || 0})</span></td></tr>
          <tr><td class="text-muted">Resumes:</td><td>${(worker.auto_resume_count || 0) + (worker.manual_resume_count || 0)} <span class="text-muted small">(auto: ${worker.auto_resume_count || 0}, manual: ${worker.manual_resume_count || 0})</span></td></tr>
          <tr><td class="text-muted">Idle Detection:</td><td>${worker.is_idle_detection_enabled ? '<span class="badge bg-success">Enabled</span>' : '<span class="badge bg-secondary">Disabled</span>'}</td></tr>
          <tr><td class="text-muted">Last Activity:</td><td>${worker.last_activity_at ? formatDateWithRelative(worker.last_activity_at) : '<span class="text-muted">N/A</span>'}</td></tr>
        </table>
      </div>
    </div>
  `;
}
