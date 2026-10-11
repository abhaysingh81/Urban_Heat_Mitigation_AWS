# HeatRelief blog

An interactive long-read about HeatRelief for the Environmental Hacks submission, plus a text version for AWS Builder Center.

- `src/` is the interactive page (Vite + React + Tailwind).
- `builder-center/POST.md` is the text post for AWS Builder Center, with figure images in `builder-center/img/`.

## Numbers come from the repo

Every figure on the page is exported from the main project. Nothing is typed by hand. After retraining the model or changing the optimizer, refresh the numbers from the repo root:

```bash
.venv/bin/python -m scripts.export_blog_data   # writes BLOG/src/data/real/*.json
```

`builder-center/POST.md` quotes the same numbers as plain text. Update it by hand if the export changes them.

## Run

```bash
npm install
npm run dev       # http://localhost:3000
npm run build     # static site in dist/ (relative paths, so any static host or S3 works)
```

## Before publishing

- Set `AWS_STATUS` in `src/content.ts` to `'deployed'` once the SAM stack is live. The AWS chapter changes its wording to match.
- Check `AI_TOOLS` in `src/content.ts` against the tools the team actually used.
- Fill in the blog URL and the demo video link at the top of `builder-center/POST.md`.
