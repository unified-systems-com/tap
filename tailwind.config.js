/** @type {import('tailwindcss').Config} */
module.exports = {
  // Static globs — resolved by the tailwindcss CLI directly, no Python plugin
  // discovery required (req-web-tailwind-pipeline-content-paths-2). Plugins
  // ship their own templates and increasingly use utility classes; a class
  // used only in a plugin template and not covered by a glob below silently
  // misses the compiled CSS (req-web-tailwind-pipeline-content-paths-1).
  //
  // A plugin reaches a session by exactly THREE roads, and the config must
  // name all three — the one glob that used to stand here (`./plugins/**`)
  // covers only the road nothing travels any more (tap#619):
  //
  //   plugins/<slug>/…            in-tree plugin (supported, currently empty:
  //                               plugins/ holds only __init__.py post-eviction)
  //   _dev-plugins/<slug>/…       plugin-workspace dev checkout, editable-installed
  //                               (tap/dev_workspace.py DEV_PLUGINS_DIR)
  //   .venv/…/tap_plugin/<pkg>/…  wheel-installed plugin in the container venv
  //                               (tap/plugin_testing.py plugin_package_dir)
  //
  // An editable install leaves a .pth pointer in site-packages, not files, so
  // the dev-checkout glob is NOT redundant with the venv one — each covers a
  // road the other cannot see. The python* wildcard keeps the venv glob alive
  // across interpreter bumps.
  //
  // KNOWN, DELIBERATE: the last two globs make the compiled artifact depend on
  // which plugins the builder has installed — reproducibility across sessions
  // is no longer free. That question is tap#622; scanning nothing is not the
  // answer to it.
  content: [
    "./tap_web/templates/**/*.html",
    "./tap_viz/templates/**/*.html",
    "./plugins/**/templates/**/*.html",
    "./_dev-plugins/**/templates/**/*.html",
    "./.venv/lib/python*/site-packages/tap_plugin/**/templates/**/*.html",
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
