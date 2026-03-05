import { defineConfig } from 'vitest/config';
import path from 'path';

export default defineConfig({
    test: {
        globals: true,
        environment: 'jsdom',
        include: ['tests/**/*.test.js'],
        coverage: {
            provider: 'v8',
            reporter: ['text', 'html'],
            include: ['src/scripts/**/*.js'],
            exclude: ['src/scripts/vendor/**', 'src/scripts/lib/**'],
        },
        testTimeout: 10000,
        hookTimeout: 10000,
    },
    resolve: {
        alias: {
            '@scripts': path.resolve(__dirname, 'src/scripts'),
        },
    },
});
