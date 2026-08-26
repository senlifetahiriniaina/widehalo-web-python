from __future__ import annotations

import pytest
from django.test import Client, override_settings

from apps.core.models.user import User

pytestmark = pytest.mark.django_db


def _access_token(client: Client, email: str, password: str) -> str:
    response = client.post(
        "/api/v1/auth/login",
        {"email": email, "password": password},
        content_type="application/json",
    )
    return response.json()["access"]


def _auth_header(token: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


def test_health_live_returns_200_without_dependencies() -> None:
    client = Client()
    response = client.get("/api/v1/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_health_ready_reports_db_and_redis() -> None:
    client = Client()
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["db"] is True
    assert body["redis"] is True


def test_meta_endpoint_is_public() -> None:
    client = Client()
    response = client.get("/api/v1/meta")
    assert response.status_code == 200
    assert response.json()["base_currency"] == "MGA"


def test_protected_endpoint_without_token_is_unauthorized() -> None:
    client = Client()
    response = client.get("/api/v1/tenants")
    assert response.status_code == 401


def test_idempotent_endpoint_without_header_returns_400_problem_detail() -> None:
    user = User.objects.create_user(email="idem@example.com", password="Str0ngPassw0rd!23")
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")

    response = client.post(
        "/api/v1/meta/echo",
        {"message": "hello"},
        content_type="application/json",
        **_auth_header(token),
    )
    assert response.status_code == 400
    assert response["Content-Type"] == "application/problem+json"


def test_idempotent_endpoint_replays_response_for_same_key() -> None:
    user = User.objects.create_user(email="idem2@example.com", password="Str0ngPassw0rd!23")
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _auth_header(token)
    headers["HTTP_IDEMPOTENCY_KEY"] = "fixed-key-123"

    from apps.core.models.idempotency import IdempotencyKey

    first = client.post(
        "/api/v1/meta/echo", {"message": "hello"}, content_type="application/json", **headers
    )
    assert first.status_code == 200
    assert IdempotencyKey.objects.count() == 1

    second = client.post(
        "/api/v1/meta/echo", {"message": "hello"}, content_type="application/json", **headers
    )
    assert second.status_code == 200
    assert second.json() == first.json()
    # Aucun nouvel enregistrement : la reponse a ete rejouee, pas recalculee.
    assert IdempotencyKey.objects.count() == 1


def test_idempotent_endpoint_rejects_same_key_with_different_body() -> None:
    user = User.objects.create_user(email="idem3@example.com", password="Str0ngPassw0rd!23")
    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = _auth_header(token)
    headers["HTTP_IDEMPOTENCY_KEY"] = "fixed-key-456"

    client.post(
        "/api/v1/meta/echo", {"message": "hello"}, content_type="application/json", **headers
    )
    response = client.post(
        "/api/v1/meta/echo", {"message": "different"}, content_type="application/json", **headers
    )
    assert response.status_code == 409


@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
def test_rate_limit_exceeded_returns_429() -> None:
    from apps.core.throttling import throttle

    @throttle(limit=2, window=60)
    def view(request):
        return {"status": "ok"}

    factory_request_count = {"n": 0}

    class FakeUser:
        id = "user-x"

    class FakeRequest:
        auth = FakeUser()
        META = {"REMOTE_ADDR": "127.0.0.1"}
        path = "/api/v1/fake"

    for _ in range(2):
        result = view(FakeRequest())
        assert result == {"status": "ok"}
        factory_request_count["n"] += 1

    blocked = view(FakeRequest())
    assert blocked.status_code == 429
