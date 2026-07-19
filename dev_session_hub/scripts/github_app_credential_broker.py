#!/srv/devhub-uat/runtime/venv19/bin/python3
"""Mint one short-lived, repository-scoped GitHub App installation token.

Install this script and the App private key under the protected credential root.
It writes the token only to the protected gh profile and emits sanitized
attestation metadata on stdout.
"""
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
PERMISSIONS = {
    "contents": "read",
    "metadata": "read",
    "pull_requests": "write",
}


def _b64url(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _required_integer(name):
    value = os.environ.get(name, "")
    if not value.isdigit() or int(value) <= 0:
        raise ValueError("invalid protected broker identity")
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
        raise RuntimeError("private-key signing failed")
    return "%s.%s" % (unsigned.decode(), _b64url(signed.stdout))


def _mint_token(jwt, installation_id, repository):
    repository_name = repository.split("/", 1)[1]
    body = json.dumps(
        {"repositories": [repository_name], "permissions": PERMISSIONS}
    ).encode()
    request = urllib.request.Request(
        "https://api.github.com/app/installations/%s/access_tokens"
        % installation_id,
        data=body,
        method="POST",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": "Bearer %s" % jwt,
            "Content-Type": "application/json",
            "User-Agent": "devhub-pr-credential-broker",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            if response.status != 201:
                raise RuntimeError("installation-token request failed")
            return json.load(response)
    except (urllib.error.URLError, TimeoutError):
        raise RuntimeError("installation-token request failed")


def _write_gh_profile(profile, token):
    profile.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(profile, 0o700)
    content = (
        "github.com:\n"
        "    git_protocol: https\n"
        "    oauth_token: %s\n"
        "    user: devhub-pr-github-app\n"
        % token
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
        repository != "sabryyoussef/veterinarian_19"
        or not profile.is_absolute()
        or not str(profile.resolve()).startswith(str(ROOT) + "/")
    ):
        raise ValueError("repository or profile escaped protected policy")
    key_path = ROOT / ("app-%s.pem" % app_id)
    if (
        not key_path.is_file()
        or key_path.stat().st_mode & 0o077
        or key_path.resolve().parent != ROOT
    ):
        raise PermissionError("protected App private key is unavailable")
    token_response = _mint_token(_sign_jwt(app_id, key_path), installation_id, repository)
    token = token_response.pop("token", None)
    repositories = sorted(
        item.get("full_name")
        for item in token_response.get("repositories", [])
        if item.get("full_name")
    )
    if (
        not token
        or token_response.get("permissions") != PERMISSIONS
        or repositories != [repository]
        or not token_response.get("expires_at")
    ):
        raise RuntimeError("installation token exceeds exact policy")
    _write_gh_profile(profile, token)
    print(
        json.dumps(
            {
                "credential_type": "github_app_installation",
                "app_id": app_id,
                "installation_id": installation_id,
                "repositories": repositories,
                "permissions": PERMISSIONS,
                "expires_at": token_response["expires_at"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("GitHub App credential broker failed safely.", file=sys.stderr)
        raise SystemExit(1)
