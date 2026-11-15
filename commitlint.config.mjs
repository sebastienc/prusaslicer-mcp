// Conventional Commits, checked in CI by wagoid/commitlint-github-action (see .github/workflows/ci.yml).
// Release Please reads these messages to choose the next version and write the changelog (ADR 0008).
export default {
  extends: ["@commitlint/config-conventional"],
  // Dependabot writes long release-note lines into its commit bodies, which the body line limit would reject.
  ignores: [(message) => message.includes("Signed-off-by: dependabot[bot]")],
  rules: {
    // Same limit the project already used for subject lines.
    "header-max-length": [2, "always", 72],
  },
};
