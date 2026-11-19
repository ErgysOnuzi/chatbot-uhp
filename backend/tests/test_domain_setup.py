import pytest

from app.domain_setup import build_domain_plan, normalize_domain


def test_normalize_domain_accepts_url_and_removes_www():
    assert normalize_domain("https://www.Universiteti-Yt.com/regjistrim") == "universiteti-yt.com"
    assert normalize_domain("universiteti-yt.com.") == "universiteti-yt.com"


@pytest.mark.parametrize(
    "value",
    ["", "localhost", "https://127.0.0.1", "bad_domain.com", "example.123", "-bad.com"],
)
def test_normalize_domain_rejects_invalid_values(value):
    with pytest.raises(ValueError):
        normalize_domain(value)


def test_build_domain_plan_returns_namecheap_and_coolify_values():
    plan = build_domain_plan("universiteti-yt.com", "94.100.53.9")

    assert plan["records"] == [
        {
            "type": "A Record",
            "host": "@",
            "value": "94.100.53.9",
            "ttl": "Automatic",
            "purpose": "Lidh domenin bazë universiteti-yt.com",
        },
        {
            "type": "CNAME Record",
            "host": "www",
            "value": "universiteti-yt.com",
            "ttl": "Automatic",
            "purpose": "Lidh www.universiteti-yt.com",
        },
    ]
    assert plan["coolify_domains"] == [
        "https://universiteti-yt.com",
        "https://www.universiteti-yt.com",
    ]


def test_build_domain_plan_rejects_invalid_server_ip():
    with pytest.raises(ValueError):
        build_domain_plan("universiteti-yt.com", "server.local")
