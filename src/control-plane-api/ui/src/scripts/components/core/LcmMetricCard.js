/**
 * LcmMetricCard - Metric Display Card Web Component
 *
 * Displays a statistic with icon, value, and optional trend indicator.
 *
 * Usage:
 *   <lcm-metric-card
 *     title="Total Workers"
 *     value="24"
 *     icon="bi-server"
 *     color="primary"
 *     trend="up"
 *     trend-value="+12%">
 *   </lcm-metric-card>
 *
 * @module components/core/LcmMetricCard
 */

import { BaseComponent } from '../../core/BaseComponent.js';

export class LcmMetricCard extends BaseComponent {
    static get observedAttributes() {
        return ['title', 'value', 'subtitle', 'icon', 'color', 'trend', 'trend-value', 'loading', 'link'];
    }

    constructor() {
        super();
    }

    onMount() {
        this.render();
    }

    onAttributeChange() {
        this.render();
    }

    get title() {
        return this.getAttribute('title') || '';
    }

    get value() {
        return this.getAttribute('value') || '0';
    }

    get subtitle() {
        return this.getAttribute('subtitle');
    }

    get icon() {
        return this.getAttribute('icon') || 'bi-bar-chart';
    }

    get color() {
        return this.getAttribute('color') || 'primary';
    }

    get trend() {
        return this.getAttribute('trend'); // 'up', 'down', 'flat'
    }

    get trendValue() {
        return this.getAttribute('trend-value');
    }

    get isLoading() {
        return this.hasAttribute('loading');
    }

    get link() {
        return this.getAttribute('link');
    }

    /**
     * Update the card value programmatically
     * @param {string|number} newValue
     */
    setValue(newValue) {
        this.setAttribute('value', String(newValue));
    }

    /**
     * Update the trend programmatically
     * @param {string} direction - 'up', 'down', 'flat'
     * @param {string} value - e.g., '+12%'
     */
    setTrend(direction, value) {
        this.setAttribute('trend', direction);
        if (value) {
            this.setAttribute('trend-value', value);
        }
    }

    render() {
        const trendHtml = this._renderTrend();
        const subtitleHtml = this.subtitle ? `<small class="opacity-75">${this.subtitle}</small>` : '';
        const valueHtml = this.isLoading ? `<div class="placeholder-glow"><span class="placeholder col-6"></span></div>` : `<h2 class="card-title mb-0">${this.value}</h2>`;

        const cardContent = `
            <div class="card stats-card bg-${this.color} text-white h-100">
                <div class="card-body">
                    <div class="d-flex justify-content-between align-items-start">
                        <div>
                            <h6 class="card-subtitle mb-2 opacity-75">${this.title}</h6>
                            ${valueHtml}
                            ${subtitleHtml}
                            ${trendHtml}
                        </div>
                        <i class="${this.icon} fs-1 opacity-50"></i>
                    </div>
                </div>
            </div>
        `;

        if (this.link) {
            this.innerHTML = `
                <a href="${this.link}" class="text-decoration-none">
                    ${cardContent}
                </a>
            `;
        } else {
            this.innerHTML = cardContent;
        }

        // Add hover effect for clickable cards
        if (this.link) {
            this.querySelector('.card').style.cursor = 'pointer';
            this.querySelector('.card').addEventListener('mouseenter', () => {
                this.querySelector('.card').classList.add('shadow-lg');
            });
            this.querySelector('.card').addEventListener('mouseleave', () => {
                this.querySelector('.card').classList.remove('shadow-lg');
            });
        }
    }

    _renderTrend() {
        if (!this.trend || !this.trendValue) return '';

        let iconClass = 'bi-dash';
        let colorClass = 'text-light';

        if (this.trend === 'up') {
            iconClass = 'bi-arrow-up-short';
            colorClass = 'text-success-emphasis';
        } else if (this.trend === 'down') {
            iconClass = 'bi-arrow-down-short';
            colorClass = 'text-danger-emphasis';
        }

        return `
            <div class="mt-2 small ${colorClass}" style="opacity: 0.9;">
                <i class="${iconClass}"></i>
                <span>${this.trendValue}</span>
            </div>
        `;
    }
}

// Register custom element
if (!customElements.get('lcm-metric-card')) {
    customElements.define('lcm-metric-card', LcmMetricCard);
}

export default LcmMetricCard;
