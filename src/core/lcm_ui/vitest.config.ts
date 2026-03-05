import { defineConfig } from 'vitest/config';

export default defineConfig({
    test: {
        globals: true,
        environment: 'jsdom',
        include: ['tests/**/*.test.ts'],
        coverage: {
            provider: 'v8',
            reporter: ['text', 'html', 'lcov'],
            include: ['src/**/*.ts'],
            exclude: ['src/**/*.d.ts', 'src/**/index.ts'],
            thresholds: {
                lines: 80,
                branches: 80,
                functions: 80,
                statements: 80,
            },
        },
        testTimeout: 10000,
        hookTimeout: 10000,
    },
    resolve: {
        alias: {
            '@': '/src',
        },
    },
});
