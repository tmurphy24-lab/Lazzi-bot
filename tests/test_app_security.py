'''
Security tests for app.py's request guard.

This panel serves LinkedIn credentials from GET /api/config and can start a
browser automation subprocess, while listening on a port any page in the user's
browser can reach. These tests pin the two properties that keep that safe:
cross-site requests are refused, and only loopback Host headers are answered.

License: MIT  (https://opensource.org/license/mit)
'''

import pytest


def test_cross_site_request_is_refused(client):
    '''A page on another origin must not be able to read the config.'''
    resp = client.get("/api/config", headers={
        "Origin": "https://evil.example",
        "Sec-Fetch-Site": "cross-site",
    })
    assert resp.status_code == 403


def test_same_site_request_is_refused(client):
    '''Sibling origins get no more trust than strangers here.'''
    resp = client.get("/api/config", headers={"Sec-Fetch-Site": "same-site"})
    assert resp.status_code == 403


@pytest.mark.parametrize("fetch_site", ["same-origin", "none"])
def test_panel_and_navigation_still_allowed(client, fetch_site):
    '''
    The panel's own fetches ('same-origin') and a user opening the page
    ('none' - typed URL, bookmark, desktop launcher) must both work. Blocking
    'none' would lock the app's own front door.
    '''
    assert client.get("/api/config", headers={"Sec-Fetch-Site": fetch_site}).status_code == 200


def test_no_cors_header_is_ever_sent(client):
    '''
    Nothing may re-introduce wildcard CORS: it is what previously let any
    website read the stored LinkedIn password.
    '''
    resp = client.get("/api/config", headers={"Origin": "https://evil.example"})
    assert not any(h.lower().startswith("access-control-") for h in resp.headers.keys())


def test_non_loopback_host_is_refused(client):
    '''DNS rebinding: an attacker hostname pointed at 127.0.0.1 still fails.'''
    assert client.get("/api/config", headers={"Host": "evil.example"}).status_code == 403


@pytest.mark.parametrize("host", ["127.0.0.1", "127.0.0.1:5000", "localhost:5000", "[::1]:5000"])
def test_loopback_hosts_are_accepted(client, host):
    assert client.get("/api/config", headers={"Host": host}).status_code == 200


def test_api_responses_are_not_cached(client):
    '''Config responses carry credentials; they must never sit in a cache.'''
    resp = client.get("/api/config")
    assert resp.headers.get("Cache-Control") == "no-store"
