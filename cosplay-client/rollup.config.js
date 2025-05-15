import resolve from '@rollup/plugin-node-resolve';
import commonjs from '@rollup/plugin-commonjs';
import typescript from '@rollup/plugin-typescript';
import { terser } from 'rollup-plugin-terser';
import nodePolyfills from 'rollup-plugin-polyfill-node';
import pkg from './package.json';

export default [
  // UMD build for browsers
  {
    input: 'src/index.ts',
    output: {
      name: 'CosplayClient',
      file: pkg.browser,
      format: 'umd',
      sourcemap: true,
      globals: {
        events: 'EventEmitter'
      }
    },
    plugins: [
      nodePolyfills(),
      resolve({
        browser: true,
        preferBuiltins: false
      }),
      commonjs(),
      typescript({ tsconfig: './tsconfig.json' }),
      terser()
    ]
  },
  // ESM build for modern environments
  {
    input: 'src/index.ts',
    output: {
      file: pkg.module,
      format: 'es',
      sourcemap: true
    },
    plugins: [
      typescript({ tsconfig: './tsconfig.json' })
    ],
    external: Object.keys(pkg.dependencies || {}).concat(Object.keys(pkg.peerDependencies || {}))
  },
  // CommonJS build for Node.js
  {
    input: 'src/index.ts',
    output: {
      file: pkg.main,
      format: 'cjs',
      sourcemap: true
    },
    plugins: [
      typescript({ tsconfig: './tsconfig.json' })
    ],
    external: Object.keys(pkg.dependencies || {}).concat(Object.keys(pkg.peerDependencies || {}))
  }
];
