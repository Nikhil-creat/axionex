# Publish AxioNex on GitHub and GitHub Pages

GitHub Pages only serves static files. It cannot run FastAPI, Postgres, Redis or Qdrant. So this project ships two modes:

| Mode | Where it runs | What you get |
|---|---|---|
| **Browser demo** | GitHub Pages (free) | The full dashboard. The agents, forecast, simulator and price lab run in the visitor's browser on seeded data. |
| **Full stack** | Docker on your laptop or a cloud host | Real Postgres/PostGIS, Redis Streams, Qdrant RAG, the CNN and webhooks. |

## 1. Create the repository
1. Sign in at github.com and click **New repository**.
2. Name it `axionex`, choose Public (Pages on a private repo needs a paid plan), and leave every "Add a README/.gitignore/licence" box **unticked**.
3. Click **Create repository**.

## 2. Push the code
Install Git, unzip `axionex.zip`, then in a terminal:

```bash
cd axionex
git init -b main
git add .
git commit -m "Initial commit: AxioNex"
git remote add origin https://github.com/Nikhil-creat/axionex.git
git push -u origin main
```

When Git asks for a password, use a **personal access token** (GitHub > Settings > Developer settings > Personal access tokens), not your account password. GitHub Desktop or `gh auth login` also work.

## 3. Turn on GitHub Pages
1. In the repo open **Settings > Pages**.
2. Under **Build and deployment > Source**, choose **GitHub Actions**.
3. Open the **Actions** tab. The "Deploy demo to GitHub Pages" workflow starts from your push (or click **Run workflow**). It takes about 2 to 4 minutes.
4. When it turns green, your site is live at:

**https://nikhil-creat.github.io/axionex/**

If the repo has a different name, the URL is `https://<username>.github.io/<repo-name>/` and the workflow picks the name up automatically. For a repo named `<username>.github.io`, set `NEXT_PUBLIC_BASE_PATH` to an empty string in `.github/workflows/deploy-pages.yml`.

## 4. Troubleshooting
- **Blank page or missing styles:** the base path is wrong. Confirm the repo name matches the URL.
- **Workflow fails on `npm run build`:** open the failed step in the Actions tab and read the error; a missing network for Google Fonts is the most common cause on locked-down runners.
- **404 right after the first push:** wait for the green tick, then hard-refresh.
- **Every later `git push` redeploys automatically.**

## 5. Optional: connect the live site to a real backend
Deploy the `backend` container somewhere with HTTPS (Render, Fly.io, Railway, a VPS), then:
1. Add `https://nikhil-creat.github.io` to the backend `CORS_ORIGINS`.
2. In the workflow, set `NEXT_PUBLIC_DEMO_MODE: "false"` and `NEXT_PUBLIC_API_URL: https://your-api.example.com`.
3. Push. The Pages site now talks to your real API.

Never commit `.env` files or API keys; `.gitignore` already excludes `.env`.
