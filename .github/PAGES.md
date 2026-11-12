# Documentation publishing

`workflows/pages.yml` builds the repository root with the same pinned
`actions/jekyll-build-pages` action and Jekyll container used by the managed
Pages job. It keeps the existing site source and theme configuration. Both jobs
use `ubuntu-24.04`; JavaScript actions and the Pages uploader's pinned nested
upload action use Node24. The Docker Jekyll builder does not use a JavaScript
action runtime.

The build reads contents and Pages metadata. Only the deployment job receives
`pages: write` and `id-token: write`, and uses the `github-pages` environment.
Both jobs require this repository and `refs/heads/main`; pushes to other branches
and pull requests do not publish. A manual dispatch also requires main.
Concurrency preserves an in-progress deployment.

After maintainer review and owner-approved publication, the owner must set
**Settings → Pages → Build and deployment → Source → GitHub Actions**.
Keep the existing domain and environment protections. `configure-pages` has
`enablement: false`; the workflow does not change repository settings.
Confirm the new workflow completes and compare the deployed home page,
Community links and charts with the existing site before considering migration
verified. Earlier workflow runs retain their original warning annotations.

This workflow publishes documentation already merged into main. It does not
accept benchmark submissions, approve measurements or merge intake drafts.
The separate intake workflows have their own pinned actions and runner labels;
this Pages migration does not update those jobs.

References: [GitHub Pages publishing sources](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site),
[Node24 transition](https://github.blog/changelog/2026-09-23-node-20-is-no-longer-available-in-github-actions/).
