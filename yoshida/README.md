# Profile cards

The images on the profile page are drawn by [Yoshida](https://github.com/XOYZ69/yoshida).

| Path | What it is |
| --- | --- |
| `designs/` | the hero banner (12 animation frames) and the project card |
| `cards/` | card data, written by `build_profile.py` from the GitHub API |
| `profile.config.json` | what you edit: login, coding start date, hero message, featured projects |
| `YOSHIDA_VERSION` | the Yoshida release used to render (`latest` is allowed) |
| `assets/` | the Sinon picture and the JetBrains Mono font (OFL) |

Output goes to `../generated/`.

## Build locally

```sh
pip install pillow
YOSHIDA_BIN=/path/to/yoshida python .github/scripts/build_profile.py --offline
```

`--offline` skips the GitHub API and reuses the data in `cards/`. Without it the script reads
public data of the login in `profile.config.json` (set `GITHUB_TOKEN` to avoid the rate limit).

## Workflows

- **Profile** (`profile.yml`): daily, on push to `main` and by hand. Rebuilds `generated/` and commits changes.
- **Profile preview** (`preview.yml`): on pull requests. Builds the cards as they would be after the merge and comments
  before/after images, the changed files and the changed data. Images live on the `pr-previews` branch and are deleted
  when the pull request closes. Run it by hand with the pull request number if a pull request was opened by a workflow.
- **Yoshida bump** (`yoshida-bump.yml`): opens a pull request when a new Yoshida release exists, so the preview shows
  what the new version does before you merge.

## Formatting

Every JSON file in this folder is written by `yoshida fmt` (CI fails on anything else).
Editors that format JSON on save fight with it, so:

- `.zed/settings.json` turns format on save off for this folder in Zed.
- `.githooks/pre-commit` runs `yoshida fmt` on staged files. Enable it once per clone:

  ```sh
  git config core.hooksPath .githooks
  ```

  It uses `$YOSHIDA_BIN` or `yoshida` from your `PATH`.
