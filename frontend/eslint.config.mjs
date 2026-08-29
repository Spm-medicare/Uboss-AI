//  eslint-config-next 16 exports flat config arrays directly, so there is no `FlatCompat`
//  shim here. `core-web-vitals` carries the React, hooks and jsx-a11y rules; `typescript` adds
//  the TypeScript parser and its rules.
import nextCoreWebVitals from "eslint-config-next/core-web-vitals";
import nextTypeScript from "eslint-config-next/typescript";

export default [
  ...nextCoreWebVitals,
  ...nextTypeScript,
  {
    rules: {
      //  PLAN and the frontend rules both forbid silencing the compiler at the API boundary.
      //  If the generated schema lacks a route, regenerate the contract instead.
      "@typescript-eslint/no-explicit-any": "error",
      "@typescript-eslint/ban-ts-comment": "error",
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
      //  A clickable div has no role, no keyboard behaviour and no accessible name. Use a
      //  button.
      "jsx-a11y/no-static-element-interactions": "error",
      "jsx-a11y/click-events-have-key-events": "error",
    },
  },
  {
    ignores: [".next/**", "node_modules/**", "next-env.d.ts"],
  },
];
