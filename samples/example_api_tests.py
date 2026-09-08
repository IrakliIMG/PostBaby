import requests


# TC-HEALTH-001
# Service health check
def test_health():
    response = requests.get("{{BASE_URL}}/health", timeout=30)
    assert response.status_code == 200


# TC-ENDPOINT-001
# Invalid endpoint returns not found
def test_invalid_endpoint():
    response = requests.get("{{BASE_URL}}/does-not-exist", timeout=30)
    assert response.status_code == 404
