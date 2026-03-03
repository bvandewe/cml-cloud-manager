export function getStatusBadgeClass(status) {
    const s = (status || '').toLowerCase();
    switch (s) {
        case 'running':
            return 'bg-success';
        case 'stopped':
            return 'bg-warning';
        case 'pending':
            return 'bg-info';
        case 'stopping':
        case 'shutting-down':
            return 'bg-warning';
        case 'terminated':
            return 'bg-danger';
        default:
            return 'bg-secondary';
    }
}

export function getServiceStatusBadgeClass(serviceStatus) {
    const s = (serviceStatus || '').toLowerCase();
    switch (s) {
        case 'available':
        case 'ready':
            return 'bg-success';
        case 'initializing':
        case 'degraded':
            return 'bg-warning';
        case 'error':
        case 'unavailable':
            return 'bg-danger';
        default:
            return 'bg-secondary';
    }
}

/**
 * Get Bootstrap badge class for lablet session status
 * @param {string} status - Session status (LabletSessionStatus enum)
 * @returns {string} Bootstrap badge class
 */
export function getLabletSessionStatusBadgeClass(status) {
    const s = (status || '').toLowerCase();
    switch (s) {
        case 'pending':
            return 'bg-secondary';
        case 'scheduled':
            return 'bg-info';
        case 'instantiating':
            return 'bg-warning text-dark';
        case 'ready':
            return 'bg-success';
        case 'running':
            return 'bg-success';
        case 'collecting':
            return 'bg-primary';
        case 'grading':
            return 'bg-primary';
        case 'stopping':
            return 'bg-warning text-dark';
        case 'stopped':
            return 'bg-secondary';
        case 'archived':
            return 'bg-dark';
        case 'terminated':
            return 'bg-danger';
        default:
            return 'bg-secondary';
    }
}

/**
 * Get icon class for lablet session status
 * @param {string} status - Session status (LabletSessionStatus enum)
 * @returns {string} Bootstrap icon class
 */
export function getLabletSessionStatusIcon(status) {
    const s = (status || '').toLowerCase();
    switch (s) {
        case 'pending':
            return 'bi-hourglass';
        case 'scheduled':
            return 'bi-calendar-check';
        case 'instantiating':
            return 'bi-gear-wide-connected';
        case 'ready':
            return 'bi-check-circle';
        case 'running':
            return 'bi-play-circle-fill';
        case 'collecting':
            return 'bi-cloud-download';
        case 'grading':
            return 'bi-clipboard-check';
        case 'stopping':
            return 'bi-stop-circle';
        case 'stopped':
            return 'bi-stop-fill';
        case 'archived':
            return 'bi-archive';
        case 'terminated':
            return 'bi-x-circle';
        default:
            return 'bi-question-circle';
    }
}

/** @deprecated Use getLabletSessionStatusBadgeClass */
export const getLabletInstanceStatusBadgeClass = getLabletSessionStatusBadgeClass;
/** @deprecated Use getLabletSessionStatusIcon */
export const getLabletInstanceStatusIcon = getLabletSessionStatusIcon;

/**
 * Get Bootstrap badge class for lablet definition status
 * @param {string} status - Definition status
 * @returns {string} Bootstrap badge class
 */
export function getLabletDefinitionStatusBadgeClass(status) {
    const s = (status || '').toLowerCase();
    switch (s) {
        case 'active':
            return 'bg-success';
        case 'deprecated':
            return 'bg-warning text-dark';
        case 'archived':
            return 'bg-secondary';
        case 'draft':
            return 'bg-info';
        default:
            return 'bg-secondary';
    }
}

export function getCpuProgressClass(value) {
    if (value == null) return 'bg-secondary';
    if (value >= 90) return 'bg-danger';
    if (value >= 70) return 'bg-warning';
    return 'bg-success';
}

export function getMemoryProgressClass(value) {
    if (value == null) return 'bg-secondary';
    if (value >= 90) return 'bg-danger';
    if (value >= 70) return 'bg-warning';
    return 'bg-info';
}

export function getDiskProgressClass(value) {
    if (value == null) return 'bg-secondary';
    if (value >= 90) return 'bg-danger';
    if (value >= 70) return 'bg-warning';
    return 'bg-primary';
}
