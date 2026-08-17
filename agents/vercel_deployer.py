"""Deploys a swarm-generated file set to Vercel via the real Vercel REST API
(v13 deployments endpoint). https://vercel.com/docs/rest-api/endpoints#deployments
"""
import requests

VERCEL_API_BASE = "https://api.vercel.com"


class VercelDeployError(RuntimeError):
    pass


def deploy_files(token: str, project_name: str, files: dict, target: str = "production") -> dict:
    """files: {"relative/path": "text content"}. Returns the Vercel deployment
    JSON (includes `url`) on success."""
    if not token:
        raise VercelDeployError("Missing Vercel token. Add it in Settings before deploying.")
    if not files:
        raise VercelDeployError("No files to deploy.")

    payload = {
        "name": _slugify(project_name),
        "target": target,
        "files": [{"file": path, "data": content} for path, content in files.items()],
        "projectSettings": {"framework": None},
    }

    try:
        resp = requests.post(
            f"{VERCEL_API_BASE}/v13/deployments",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=60,
        )
    except requests.RequestException as exc:
        raise VercelDeployError(f"Could not reach Vercel API: {exc}") from exc

    if resp.status_code not in (200, 201):
        raise VercelDeployError(f"Vercel API returned {resp.status_code}: {resp.text[:500]}")

    data = resp.json()
    return {
        "id": data.get("id"),
        "url": f"https://{data.get('url')}" if data.get("url") else None,
        "readyState": data.get("readyState"),
        "raw": data,
    }


def get_deployment_status(token: str, deployment_id: str) -> dict:
    if not token:
        raise VercelDeployError("Missing Vercel token.")
    try:
        resp = requests.get(
            f"{VERCEL_API_BASE}/v13/deployments/{deployment_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
    except requests.RequestException as exc:
        raise VercelDeployError(f"Could not reach Vercel API: {exc}") from exc
    if resp.status_code != 200:
        raise VercelDeployError(f"Vercel API returned {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    return {"id": data.get("id"), "readyState": data.get("readyState"), "url": data.get("url")}


def _slugify(name: str) -> str:
    slug = "".join(c.lower() if c.isalnum() else "-" for c in (name or "void-cutting-slash-app"))
    slug = "-".join(filter(None, slug.split("-")))
    return slug or "void-cutting-slash-app"
