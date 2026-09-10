/** @type {import('tailwindcss').Config} */
module.exports = {
  // Static globs — resolved by the tailwindcss CLI directly, no Python plugin
  // discovery required (req-web-tailwind-pipeline-content-paths-2). Plugins
  // ship their own templates under plugins/*/templates and increasingly use
  // utility classes; without the third glob, classes used only in plugin
  // templates would silently miss the compiled CSS
  // (req-web-tailwind-pipeline-content-paths-1).
  content: [
    "./tap_web/templates/**/*.html",
    "./tap_viz/templates/**/*.html",
    "./plugins/**/templates/**/*.html",
  ],
  theme: {
    extend: {
      colors: {
        // Warm-neutral off-white page canvas — Tufte "paper, not glare". The
        // default app background (set on <html> in base.html). TRIAL
        // 2026-09-10: taken from git-serious-double-tap's workboard ground,
        // which reads calmer than the cool grey it replaces (#f4f5f7).
        // The trade the old value was chosen to avoid is real and is now
        // accepted deliberately: this warm taupe does NOT sit in the same
        // family as TAP's cool slate chrome (the slate-800 breadcrumb bar,
        // slate text), so the page reads warm and the chrome cool. Still
        // lifts off pure white so white panels separate, and still lighter
        // than slate-100 (#f1f5f9, hover/selected) so those keep reading.
        canvas: "#f1f0ec",
      },
    },
  },
  plugins: [],
}
