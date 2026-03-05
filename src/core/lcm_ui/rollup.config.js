import resolve from '@rollup/plugin-node-resolve';
import typescript from '@rollup/plugin-typescript';
import dts from 'rollup-plugin-dts';

const external = [];

// Shared plugins for all builds
const plugins = [
    resolve(),
    typescript({
        tsconfig: './tsconfig.json',
        declaration: false, // We generate declarations separately
        declarationDir: undefined,
    }),
];

// Build configurations for each entry point
const entries = [
    { input: 'src/index.ts', name: 'index' },
    { input: 'src/core/index.ts', name: 'core/index' },
    { input: 'src/session/index.ts', name: 'session/index' },
    { input: 'src/middleware/index.ts', name: 'middleware/index' },
    { input: 'src/components/index.ts', name: 'components/index' },
];

// Generate ESM and UMD builds for each entry
const builds = entries.flatMap(({ input, name }) => [
    // ESM build
    {
        input,
        output: {
            file: `dist/${name}.esm.js`,
            format: 'esm',
            sourcemap: true,
        },
        external,
        plugins,
    },
    // UMD build
    {
        input,
        output: {
            file: `dist/${name}.umd.js`,
            format: 'umd',
            name: 'NeurogliaUI',
            sourcemap: true,
            globals: {},
        },
        external,
        plugins,
    },
]);

// Type declarations build
const typeBuilds = entries.map(({ input, name }) => ({
    input,
    output: {
        file: `dist/types/${name}.d.ts`,
        format: 'esm',
    },
    plugins: [dts()],
}));

export default [...builds, ...typeBuilds];
