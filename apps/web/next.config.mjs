import path from "node:path";

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // The workspace contract package ships ESM + type declarations; transpile it so
  // the App Router bundles it consistently.
  transpilePackages: ["@drw/experiment-spec"],
  // Carbon ships its Sass from the package root (`@carbon/react` -> index.scss).
  // Give Dart Sass a node_modules load path so `@use '@carbon/react'` resolves
  // under pnpm's symlinked layout.
  sassOptions: {
    includePaths: [path.join(process.cwd(), "node_modules")],
  },
};

export default nextConfig;
