//  Tailwind v4 is a PostCSS plugin; there is no tailwind.config.js. The design tokens live in
//  src/styles/tokens.css and are mapped to Tailwind's colour names by its `@theme inline` block.
const config = {
  plugins: {
    "@tailwindcss/postcss": {},
  },
};

export default config;
