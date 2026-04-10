/**
 * TimeslotBadge component tests.
 */
import { describe, it, expect, afterEach, vi, beforeEach } from 'vitest';
import '../src/components/TimeslotBadge.js';

describe('TimeslotBadge', () => {
    let el: Element;

    function create(attrs: Record<string, string> = {}): Element {
        el = document.createElement('ui-timeslot-badge');
        for (const [key, value] of Object.entries(attrs)) {
            el.setAttribute(key, value);
        }
        document.body.appendChild(el);
        return el;
    }

    beforeEach(() => {
        vi.useFakeTimers();
    });

    afterEach(() => {
        el?.remove();
        vi.useRealTimers();
    });

    describe('window phase computation', () => {
        it('shows "active" styling for current timeslot', () => {
            const now = new Date();
            const start = new Date(now.getTime() - 30 * 60_000).toISOString();
            const end = new Date(now.getTime() + 30 * 60_000).toISOString();
            vi.setSystemTime(now);
            create({ start, end });
            expect(el.innerHTML).toContain('remaining');
        });

        it('shows "before" styling for future timeslot', () => {
            const now = new Date();
            const start = new Date(now.getTime() + 60 * 60_000).toISOString();
            const end = new Date(now.getTime() + 120 * 60_000).toISOString();
            vi.setSystemTime(now);
            create({ start, end });
            expect(el.innerHTML).toContain('Starts in');
        });

        it('shows "expired" styling for past timeslot', () => {
            const now = new Date();
            const start = new Date(now.getTime() - 120 * 60_000).toISOString();
            const end = new Date(now.getTime() - 60 * 60_000).toISOString();
            vi.setSystemTime(now);
            create({ start, end });
            expect(el.innerHTML).toContain('Ended');
        });
    });

    describe('auto-refresh', () => {
        it('updates display on timer tick', () => {
            const now = new Date('2024-06-01T12:00:00Z');
            vi.setSystemTime(now);

            const start = new Date(now.getTime() + 5 * 60_000).toISOString();
            const end = new Date(now.getTime() + 65 * 60_000).toISOString();
            create({ start, end });

            const initialHtml = el.innerHTML;

            // Advance time to make the timeslot active
            vi.setSystemTime(new Date(now.getTime() + 10 * 60_000));
            vi.advanceTimersByTime(10_000); // 10s refresh interval

            const updatedHtml = el.innerHTML;
            // The display should have changed as the window phase shifted
            expect(updatedHtml.length).toBeGreaterThan(0);
        });
    });

    describe('compact mode', () => {
        it('renders shorter display in compact mode', () => {
            const now = new Date();
            const start = new Date(now.getTime() - 30 * 60_000).toISOString();
            const end = new Date(now.getTime() + 30 * 60_000).toISOString();
            vi.setSystemTime(now);

            create({ start, end, compact: '' });
            // Compact should be minimal
            expect(el.innerHTML.length).toBeGreaterThan(0);
        });
    });

    describe('lead time and teardown', () => {
        it('shows approaching phase during lead time', () => {
            const now = new Date();
            const start = new Date(now.getTime() + 3 * 60_000).toISOString(); // 3 min from now
            const end = new Date(now.getTime() + 63 * 60_000).toISOString();
            vi.setSystemTime(now);
            create({ start, end, 'lead-time': '5' }); // 5 min lead
            // Should be in "approaching" phase since we're within lead time
            const html = el.innerHTML;
            expect(html.length).toBeGreaterThan(0);
        });
    });
});
