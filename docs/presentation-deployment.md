# Publish the presentation with GitHub Pages

The workflow in [pages.yml](../.github/workflows/pages.yml) publishes the
self-contained slide deck at:

**https://srujanponnapalli.github.io/raleigh-equity-analysis/**

`/repo` in a generic GitHub Pages example means the repository name. This
repository is named `raleigh-equity-analysis`; it does not need to be renamed.

## First-time setup

1. Open the repository's
   [Pages settings](https://github.com/SrujanPonnapalli/raleigh-equity-analysis/settings/pages).
2. Under **Build and deployment**, choose **GitHub Actions** as the source.
   The workflow is already included, so do not create a second workflow.
3. Open [Actions](https://github.com/SrujanPonnapalli/raleigh-equity-analysis/actions),
   select **Deploy presentation to Pages**, then choose **Run workflow** on `main`.
   If a run started before Pages was enabled and failed, rerun it after step 2.
4. Wait for the deployment to succeed. Open the URL shown in the deployment
   summary, or the address above.

The repository was private when the workflow was prepared. GitHub Pages supports
private repositories on eligible paid plans; GitHub Free supports Pages for
public repositories. If Pages settings ask for an upgrade or a public repository,
choose whether to keep the code private with a supported plan or make the
repository public yourself. Preparing this workflow does not change visibility.
The deployed site can be publicly accessible even when its source repository is
private. See GitHub's [Pages availability and site types](https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages).

## What gets deployed

The workflow copies only
[`presentation/raleigh-briefing/index.html`](../presentation/raleigh-briefing/index.html)
into the Pages artifact. Fonts, charts, map geometry, speaker notes, and
interactive controls are already embedded in that HTML file. It needs no build
tool, JavaScript package installation, data server, or API key.

The repository's raw request files, working notes, Python files, and Git history
are not uploaded as website files by this workflow. Speaker notes embedded in
the HTML remain inspectable by anyone who can access the presentation.

## Later updates

Push changes to the presentation on `main`; the workflow republishes it
automatically. Changes to the workflow also trigger deployment. Other repository
changes do not rerun Pages unless you select **Run workflow** manually.

The URL remains the same. If a browser shows an old version after a successful
deployment, reload it or use a private browsing window. Local inline edits stay
in that browser until downloaded and committed; they do not update the website.

This follows GitHub's
[custom Pages workflow](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)
approach. No `gh-pages` branch or custom domain is required.
