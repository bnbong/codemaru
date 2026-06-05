<p align="center">
  <img src=".github/codemaru_logo_text.png" alt="codemaru"/>
</p>
<p align="center">
<em><b>Codemaru:</b> Render a developer's public activity and algorithm-training stats as an embeddable <b>summary card</b> for GitHub profile READMEs.</em>
</p>
<p align="center">
<img src="https://img.shields.io/badge/Python-3.12+-3776ab.svg?style=flat&logo=python&logoColor=white" alt="Python"/>
<img src="https://img.shields.io/badge/FastAPI-009688.svg?style=flat&logo=fastapi&logoColor=white" alt="FastAPI"/>
<a href="https://codecov.io/gh/bnbong/codemaru" >
 <img src="https://codecov.io/gh/bnbong/codemaru/graph/badge.svg?token=A7B1BHUtSm"/>
 </a>
</p>
<p align="center">
  <b>English</b> · <a href="README.ko.md">한국어</a>
</p>

---

> `code` + `마루` (native Korean for *ridge / summit*) — climb to the top of your coding ability and keep growing.

A tool that turns your public developer activity into an embeddable SVG card.

It reads **GitHub**, **BOJ / solved.ac**, and **LeetCode**, scores it across five axes, places you on an 8-rung tier ladder, and renders a self-contained card you can drop straight into a README.

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset=".github/preview/card-dark.png">
    <img width="560" alt="codemaru summary card" src=".github/preview/card-light.png">
  </picture>
</p>

## Tiers

Eight ranks, from a humble Seed to the summit, **Maru**:

<p align="center">
  <img width="820" alt="codemaru tier ladder: Seed, Bronze, Silver, Gold, Platinum, Diamond, Master, Maru" src=".github/preview/tier-ladder.png">
</p>

```
Seed → Bronze → Silver → Gold → Platinum → Diamond → Master → Maru
```

## Themes

Three themes are available, selected with the `theme` parameter (or the generator's Theme dropdown).

<table>
  <tr>
    <td align="center"><code>default</code></td>
    <td align="center"><code>dark</code></td>
    <td align="center"><code>transparent</code></td>
  </tr>
  <tr>
    <td><img src=".github/preview/card-light.png" width="280" alt="default theme"/></td>
    <td><img src=".github/preview/card-dark.png" width="280" alt="dark theme"/></td>
    <td><img src=".github/preview/card-transparent.png" width="280" alt="transparent theme"/></td>
  </tr>
</table>

> More themes are coming.

A **compact** layout drops the radar and metric row, leaving the **tier panel only** (`250×270`) — handy for tight spaces or a README sidebar. Enable it with `compact=true` (or the generator's Layout → compact).

<p align="center">
  <img src=".github/preview/card-compact.png" width="220" alt="compact layout"/>
</p>

## Quick start

### Use the hosted generator

At **[codemaru.bnbong.com](https://codemaru.bnbong.com)**, enter your handles to get a live preview plus copy-paste Markdown / HTML snippets for your README.

<p align="center">
  <img src=".github/preview/generator.png" width="760" alt="codemaru hosted generator"/>
</p>

1. Enter your **GitHub username** (required) and, optionally, your **BOJ / solved.ac** and **LeetCode** handles.
2. Pick a **Theme** (default / dark / transparent) and **Layout** (default / compact).
3. Check the **Preview**, then hit **Copy** on the **Markdown** or **HTML `<picture>`** snippet and paste it into your README.
4. Press **↻ Reload** to refetch the data.

### Run locally

```bash
uv sync                          # install deps into .venv
uv run uvicorn codemaru.app:app --reload   # http://localhost:8000
```

Open `http://localhost:8000` for the generator (live preview + copy snippets), or call the API directly.

> For the API endpoints, fixture / live modes, and other run / contribution details, see [CONTRIBUTING.md](CONTRIBUTING.md).

## GitHub Action (static generation)

Prefer not to depend on the hosted endpoint? The **`bnbong/codemaru`** Action runs the same scoring/render pipeline inside your own repo's CI, commits the SVG, and the card then loads straight from your repository.

Add this workflow under `.github/workflows/`:

```yaml
name: Update codemaru card
on:
  schedule:
    - cron: "0 3 * * *"   # daily, 03:00 UTC
  workflow_dispatch:
jobs:
  update:
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@v4
      - uses: bnbong/codemaru@v1
        with:
          github: ${{ github.repository_owner }}   # your GitHub username (auto-filled)
          boj: your-solvedac-handle                # optional
          leetcode: your-leetcode-handle           # optional
          out: profile/codemaru.svg
      - run: |
          git config user.name "github-actions"
          git config user.email "github-actions@users.noreply.github.com"
          git add profile/codemaru.svg
          git commit -m "Update codemaru card" || exit 0
          git push
```

Then embed the committed file anywhere in your README: `![codemaru](profile/codemaru.svg)`.

| Input          | Default                | Description                                  |
| -------------- | ---------------------- | -------------------------------------------- |
| `github`       | —  (required)          | **GitHub username** to summarize (e.g. `octocat`) |
| `boj`          | `""`                   | solved.ac / BOJ handle                       |
| `leetcode`     | `""`                   | LeetCode handle                              |
| `theme`        | `default`              | `default` \| `dark` \| `transparent`         |
| `compact`      | `false`                | compact (tier-panel-only) layout             |
| `out`          | `profile/codemaru.svg` | output path for the SVG                       |
| `github-token` | `${{ github.token }}`  | auth token for reading data (**Optional**, the default workflow token is enough) |

> **`github` is not `github-token`.** `github` takes a **GitHub username** — not a token.
>
> The `${{ github.repository_owner }}` in the example is a built-in GitHub variable that auto-resolves to the username of the owner of the repo the workflow runs in, so if you wrote it as in the example you don't need to change anything.
>
> `github-token`, by contrast, is the **auth token used to read data**. If you want the analysis to also cover **private repositories**, issue a PAT with private-repo read access, add it to your repository secrets, and pass it on `github-token` (see the table) — e.g. `github-token: ${{ secrets.YOUR_PAT }}`.

The Action wraps the `codemaru generate --github <user> --out <path>` CLI, so you can also run it locally with `uv run codemaru generate`.

## Scoring

*Scores summarize **public activity** — not an absolute skill rating.*

| Axis            | Signals (source)                                                |
| --------------- | --------------------------------------------------------------- |
| Open Source     | commits, PRs, reviews, contributed repos, issues (GitHub)       |
| Impact          | stars, forks, followers, public repos (GitHub)                  |
| Consistency     | active days, longest streak (GitHub)                            |
| Problem Solving | solved counts (solved.ac + LeetCode)                            |
| Depth           | BOJ tier, hard-problem mix, LeetCode hard/contest, lang breadth |

```
overall (the number in the tier medallion) = 0.30*openSource + 0.20*problemSolving + 0.20*depth + 0.15*consistency + 0.15*impact
```

Confidence is weighted across platforms (GitHub ×0.6 volume-weighted, solved.ac ×0.25, LeetCode ×0.15 discounted as experimental).

Low confidence caps the tier, so a GitHub-only profile tops out at Gold.
