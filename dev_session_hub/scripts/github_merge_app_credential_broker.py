#!/srv/devhub-uat/runtime/venv19/bin/python3
"""Mint an exact repository-only token for the separate Merge GitHub App."""
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path("/srv/devhub/credentials/github")
REPOSITORY = "sabryyoussef/veterinarian_19"
PERMISSIONS = {
    "checks": "read",
    "contents": "write",
    "metadata": "read",
    "pull_requests": "read",
    "statuses": "read",
}


def _b64url(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _required_integer(name):
    value = os.environ.get(name, "")
    if not value.isdigit() or int(value) <= 0:
        raise ValueError("invalid protected Merge App identity")
    return int(value)


def _sign_jwt(app_id, key_path):
    now = int(time.time())
    header = _b64url(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    payload = _b64url(
        json.dumps({"iat": now - 30, "exp": now + 540, "iss": app_id}).encode()
    )
    unsigned = ("%s.%s" % (header, payload)).encode()
    signed = subprocess.run(
        ["/usr/bin/openssl", "dgst", "-sha256", "-sign", str(key_path)],
        input=unsigned,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
        timeout=10,
    )
    if signed.returncode:
        raise RuntimeError("Merge App private-key signing failed")
    return "%s.%s" % (unsigned.decode(), _b64url(signed.stdout))


def _mint_token(jwt, installation_id):
    body = json.dumps(
        {"repositories": [REPOSITORY.split("/", 1)[1]], "permissions": PERMISSIONS}
    ).encode()
    request = urllib.request.Request(
        "https://api.github.com/app/installations/%s/access_tokens" % installation_id,
        data=body,
        method="POST",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": "Bearer %s" % jwt,
            "Content-Type": "application/json",
            "User-Agent": "devhub-human-merge-credential-broker",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            if response.status != 201:
                raise RuntimeError("Merge installation-token request failed")
            return json.load(response)
    except (urllib.error.URLError, TimeoutError):
        raise RuntimeError("Merge installation-token request failed")


def _write_gh_profile(profile, token):
    profile.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(profile, 0o700)
    content = (
        "github.com:\n"
        "    git_protocol: https\n"
        "    oauth_token: %s\n"
        "    user: devhub-human-merge-github-app\n" % token
    )
    descriptor, temporary = tempfile.mkstemp(prefix=".hosts-", dir=profile)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, profile / "hosts.yml")
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    os.umask(0o077)
    app_id = _required_integer("DEVHUB_GITHUB_APP_ID")
    installation_id = _required_integer("DEVHUB_GITHUB_INSTALLATION_ID")
    repository = os.environ.get("DEVHUB_GITHUB_REPOSITORY", "")
    profile = Path(os.environ.get("GH_CONFIG_DIR", ""))
    if (
        repository != REPOSITORY
        or not profile.is_absolute()
        or not str(profile.resolve()).startswith(str(ROOT) + "/")
    ):
        raise ValueError("Merge repository or profile escaped protected policy")
    key_path = ROOT / ("merge-app-%s.pem" % app_id)
    if (
        not key_path.is_file()
        or key_path.stat().st_mode & 0o077
        or key_path.resolve().parent != ROOT
    ):
        raise PermissionError("protected Merge App private key is unavailable")
    response = _mint_token(_sign_jwt(app_id, key_path), installation_id)
    token = response.pop("token", None)
    repositories = sorted(
        item.get("full_name")
        for item in response.get("repositories", [])
        if item.get("full_name")
    )
    if (
        not token
        or response.get("permissions") != PERMISSIONS
        or repositories != [REPOSITORY]
        or not response.get("expires_at")
    ):
        raise RuntimeError("Merge installation token exceeds exact policy")
    _write_gh_profile(profile, token)
    print(
        json.dumps(
            {
                "credential_type": "github_app_installation",
                "app_id": app_id,
                "installation_id": installation_id,
                "repositories": repositories,
                "permissions": PERMISSIONS,
                "expires_at": response["expires_at"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("GitHub Merge App credential broker failed safely.", file=sys.stderr)
        raise SystemExit(1)
