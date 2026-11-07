# Small Print

A Chrome extension that shows the real cost of what you're about to buy, what you'd be locked into, and the public record of the company behind it.

## Backend

Live at **https://smallprint-production.up.railway.app** (Railway project `superb-love`, service `SmallPrint`).

- `GET /health` returns `{"ok": true}`.
- `POST /analyse` streams cards over SSE. It needs an `X-Install-Id` header.

### Deploying

Railway builds the repo root with Railpack:

- `requirements.txt` (repo root) is the only dependency list Railpack installs. Railpack copies that file on its own into the install step, so it can't include `backend/requirements.txt`. Add new backend dependencies to it.
- `railpack.json` and `railway.json` set the start command: `uvicorn server.main:app --app-dir backend ...`.
- Keep the service's root directory as the repo root. The mock responses are read from `fixtures/`.

The service is linked to this GitHub repo, so pushes to its deploy branch (Railway's default is `main`; check the service's Settings → Source) redeploy it. To deploy a local branch: `railway up --service SmallPrint`.

### Running locally

```
pip install -r requirements.txt
uvicorn server.main:app --app-dir backend --port 8000
```

## Extension

See `extension/README.md`.
