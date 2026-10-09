"""Exercise Nginx -> FastAPI -> PostgreSQL in a disposable Compose project."""

import argparse
import json
from http.client import HTTPConnection, HTTPSConnection
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def request(
    base: str, path: str, *, data: bytes | None = None, content_type: str | None = None
) -> tuple[int, bytes, dict]:
    headers = {"Content-Type": content_type} if content_type else {}
    outgoing = Request(base.rstrip("/") + path, data=data, headers=headers)
    try:
        response = urlopen(outgoing, timeout=10)
    except HTTPError as error:
        response = error
    with response:
        return response.status, response.read(), dict(response.headers)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--expect-provider-unavailable", action="store_true")
    args = parser.parse_args()
    base = args.base_url
    status, body, _ = request(base, "/")
    assert status == 200 and b'<div id="root">' in body
    for path in ("/health", "/api/health", "/api/ready"):
        status, body, _ = request(base, path)
        assert status == 200 and json.loads(body)["status"] == "ok", path
    status, body, headers = request(
        base, "/api/questions", data=b'{"question":""}', content_type="application/json"
    )
    assert status == 422 and json.loads(body)["detail"]
    assert headers.get("x-request-id") or headers.get("X-Request-ID")
    boundary = "devdocs-smoke-boundary"
    upload = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
        'filename="deployment-smoke.md"\r\nContent-Type: text/markdown\r\n\r\n'
        "# Smoke fixture\nUse ROLLBACK to discard uncommitted changes.\r\n"
        f"--{boundary}--\r\n"
    ).encode()
    status, body, _ = request(
        base,
        "/api/documents",
        data=upload,
        content_type=f"multipart/form-data; boundary={boundary}",
    )
    assert status == 201, (status, body)
    document = json.loads(body)
    assert document["chunk_count"] == 1
    status, body, _ = request(base, f"/api/documents/{document['id']}/chunks")
    assert status == 200 and "ROLLBACK" in json.loads(body)[0]["text"]
    status, body, _ = request(base, "/api/documents")
    assert status == 200 and any(d["id"] == document["id"] for d in json.loads(body))
    assert request(base, "/assets/missing.js")[0] == 404
    status, body, _ = request(base, "/api/not-a-route")
    assert status == 404 and json.loads(body)["detail"]
    # Advertise an oversized body without transmitting megabytes of test data.
    endpoint = urlsplit(base)
    connection_type = HTTPSConnection if endpoint.scheme == "https" else HTTPConnection
    connection = connection_type(endpoint.hostname, endpoint.port, timeout=10)
    try:
        connection.request(
            "POST",
            endpoint.path.rstrip("/") + "/api/documents",
            headers={"Content-Length": str(13 * 1024 * 1024)},
        )
        response = connection.getresponse()
        assert response.status == 413
        assert "request limit" in json.loads(response.read())["detail"]
    finally:
        connection.close()
    if args.expect_provider_unavailable:
        status, body, _ = request(
            base, f"/api/documents/{document['id']}/index", data=b""
        )
        assert status == 502 and "Set OPENAI_API_KEY" in json.loads(body)["detail"]
    print("Compose smoke passed: UI, API, migration, persistence, and safe errors.")


if __name__ == "__main__":
    main()
