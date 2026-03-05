/**
 * MetricCard - Metric Display Card Web Component
 *
 * Displays a statistic/metric with icon, value, subtitle, and trend indicator.
 * Supports loading states, links, and color themes.
 *
 * @example
 * ```html
 * <ui-metric-card
 *   title="Total Workers"
 *   value="24"
 *   icon="bi-server"
 *   color="primary"
 *   trend="up"
 *   trend-value="+12%">
 * </ui-metric-card>
 * ```
 *
 * @module components
 */

import { BaseComponent } from './BaseComponent.js';

/**
 * Trend direction type
 */
export type TrendDirection = 'up' | 'down' | 'flat';

/**
 * MetricCard configuration
 */
export interface MetricCardData {
    title: string;
    value: string | number;
    subtitle?: string;
    icon?: string;
    color?: string;
    trend?: TrendDirection;
    trendValue?: string;
    link?: string;
}

/**
 * MetricCard Web Component
 */
export class MetricCard extends BaseComponent {
    static get observedAttributes(): string[] {
        return ['title', 'value', 'subtitle', 'icon', 'color', 'trend', 'trend-value', 'loading', 'link', 'compact'];
    }

    constructor() {
        super();
    }

    protected override onMount(): void {
        this.render();
    }

    protected override onAttributeChange(): void {
        if (this._mounted) {
            this.render();
        }
    }

    // ===================== Getters =====================

    get cardTitle(): string {
        return this.getAttr('title', '');
    }

    get value(): string {
        return this.getAttr('value', '0');
    }

    get subtitle(): string {
        return this.getAttr('subtitle', '');
    }

    get icon(): string {
        return this.getAttr('icon', 'bi-bar-chart');
    }

    get color(): string {
        return this.getAttr('color', 'primary');
    }

    get trend(): TrendDirection | null {
        const t = this.getAttribute('trend');
        if (t === 'up' || t === 'down' || t === 'flat') return t;
        return null;
    }

    get trendValue(): string {
        return this.getAttr('trend-value', '');
    }

    get isLoading(): boolean {
        return this.getBoolAttr('loading');
    }

    get link(): string {
        return this.getAttr('link', '');
    }

    get isCompact(): boolean {
        return this.getBoolAttr('compact');
    }

    // ===================== Public API =====================

    /**
     * Update the card value programmatically
     */
    setValue(newValue: string | number): void {
        this.setAttribute('value', String(newValue));
    }

    /**
     * Update the trend programmatically
     */
    setTrend(direction: TrendDirection, value?: string): void {
        this.setAttribute('trend', direction);
        if (value !== undefined) {
            this.setAttribute('trend-value', value);
        }
    }

    /**
     * Set loading state
     */
    setLoading(loading: boolean): void {
        if (loading) {
            this.setAttribute('loading', '');
        } else {
            this.removeAttribute('loading');
        }
    }

    /**
     * Update card data
     */
    setData(data: Partial<MetricCardData>): void {
        if (data.title !== undefined) this.setAttribute('title', data.title);
        if (data.value !== undefined) this.setAttribute('value', String(data.value));
        if (data.subtitle !== undefined) this.setAttribute('subtitle', data.subtitle);
        if (data.icon !== undefined) this.setAttribute('icon', data.icon);
        if (data.color !== undefined) this.setAttribute('color', data.color);
        if (data.trend !== undefined) this.setAttribute('trend', data.trend);
        if (data.trendValue !== undefined) this.setAttribute('trend-value', data.trendValue);
        if (data.link !== undefined) this.setAttribute('link', data.link);
    }

    // ===================== Rendering =====================

    /**
     * Render trend indicator
     */
    private renderTrend(): string {
        if (!this.trend) return '';

        let trendIcon = '';
        let trendColor = '';

        switch (this.trend) {
            case 'up':
                trendIcon = 'bi-arrow-up';
                trendColor = 'text-success';
                break;
            case 'down':
                trendIcon = 'bi-arrow-down';
                trendColor = 'text-danger';
                break;
            case 'flat':
                trendIcon = 'bi-arrow-right';
                trendColor = 'text-warning';
                break;
        }

        const valueHtml = this.trendValue ? `<span>${this.trendValue}</span>` : '';

        return `
      <small class="mt-1 d-flex align-items-center opacity-75">
        <i class="${trendIcon} ${trendColor} me-1"></i>
        ${valueHtml}
      </small>
    `;
    }

    override render(): void {
        const trendHtml = this.renderTrend();
        const subtitleHtml = this.subtitle ? `<small class="opacity-75">${this.subtitle}</small>` : '';

        const valueHtml = this.isLoading ? `<div class="placeholder-glow"><span class="placeholder col-6"></span></div>` : `<h2 class="card-title mb-0 ${this.isCompact ? 'fs-4' : ''}">${this.value}</h2>`;

        const cardContent = `
      <div class="card stats-card bg-${this.color} text-white h-100 ${this.isCompact ? 'py-2' : ''}">
        <div class="card-body ${this.isCompact ? 'py-2' : ''}">
          <div class="d-flex justify-content-between align-items-start">
            <div>
              <h6 class="card-subtitle mb-2 opacity-75 ${this.isCompact ? 'small' : ''}">${this.cardTitle}</h6>
              ${valueHtml}
              ${subtitleHtml}
              ${trendHtml}
            </div>
            <i class="${this.icon} ${this.isCompact ? 'fs-3' : 'fs-1'} opacity-50"></i>
          </div>
        </div>
      </div>
    `;

        if (this.link) {
            this.innerHTML = `
        <a href="${this.link}" class="text-decoration-none d-block h-100">
          ${cardContent}
        </a>
      `;

            // Add hover effect listener
            const card = this.querySelector('.card') as HTMLElement;
            if (card) {
                this.addListener(card, 'mouseenter', () => {
                    card.style.transform = 'translateY(-2px)';
                    card.style.transition = 'transform 0.2s ease';
                });
                this.addListener(card, 'mouseleave', () => {
                    card.style.transform = '';
                });
            }
        } else {
            this.innerHTML = cardContent;
        }
    }
}

// Register the custom element
if (!customElements.get('ui-metric-card')) {
    customElements.define('ui-metric-card', MetricCard);
}

export default MetricCard;
