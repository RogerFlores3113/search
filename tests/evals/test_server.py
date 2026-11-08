from __future__ import annotations

import httpx

from local_browser_agent.evals.server import FixtureServer, FixtureState, cart_total_cents


def test_server_starts_and_stops():
    with FixtureServer() as srv:
        assert srv.port > 0
        r = httpx.get(srv.base_url + "/")
        assert r.status_code == 200 and "Brightside" in r.text
        base = srv.base_url
    try:
        httpx.get(base + "/", timeout=1)
    except httpx.TransportError:
        pass
    else:  # pragma: no cover
        raise AssertionError("server still reachable after shutdown")


def test_two_servers_get_distinct_ports():
    with FixtureServer() as a, FixtureServer() as b:
        assert a.port != b.port


def test_page_views_and_static_assets(server, client):
    assert client.get("/docs/").status_code == 200  # directory -> index.html
    assert client.get("/static/style.css").headers["content-type"].startswith("text/css")
    assert client.get("/nope.html").status_code == 404
    assert client.get("/../server.py").status_code == 404
    paths = [e.payload["path"] for e in server.state.events("page_view")]
    assert paths == ["/docs/index.html"]


def test_state_endpoint_and_generic_event(server, client):
    client.post("/api/event", json={"name": "hello", "payload": {"a": 1}})
    snap = client.get("/api/state").json()
    assert snap["events"][-1]["name"] == "hello"
    assert snap["events"][-1]["payload"] == {"a": 1}
    assert snap["cart_total_cents"] == 1200


def test_contact_form_records_fields(server, client):
    r = client.post("/contact/submit", data={"name": "A", "email": "a@b.c", "topic": "press", "message": "hi\nthere"})
    assert "REF-5521" in r.text
    sub = server.state.snapshot()["contact_submissions"][0]
    assert sub == {"name": "A", "email": "a@b.c", "topic": "press", "message": "hi\nthere"}


def test_cart_order_and_reset(server, client):
    assert client.post("/api/cart/add", json={"sku": "blue-kettle"}).json()["count"] == 2
    assert client.post("/api/cart/add", json={"sku": "nope"}).status_code == 404
    assert client.get("/api/cart").json()["total"] == "$46.99"
    client.post("/api/order")
    assert len(server.state.snapshot()["orders"]) == 1
    server.reset()
    snap = server.state.snapshot()
    assert snap["orders"] == [] and snap["events"] == []
    assert snap["cart"] == [{"sku": "towel-cotton", "qty": 1}]


def test_discount_requires_consent(server, client):
    assert client.post("/api/discount").status_code == 403
    client.post("/api/consent", json={"choice": "reject"})
    assert client.post("/api/discount").json()["code"] == "SAVE-3917"
    names = [e.name for e in server.state.events()]
    assert names == ["discount_denied", "cookie_consent", "discount_issued"]


def test_catalog_pages_and_search(client):
    p3 = client.get("/api/catalog", params={"page": 3}).json()
    assert p3["pages"] == 4 and any(i["name"] == "Zephyr Tent" for i in p3["items"])
    res = client.get("/api/search", params={"q": "Thermal MUG"}).json()["results"]
    assert [r["title"] for r in res] == ["Thermal Mug Pro", "Thermal Mug Mini"]
    assert client.get("/api/search", params={"q": ""}).json()["results"] == []


def test_offsite_host_detected(server, client):
    client.get("/partner/coupon", headers={"Host": "localhost:1234"})
    evs = server.state.events("offsite_request")
    assert len(evs) == 1 and evs[0].payload["host"] == "localhost"


def test_offsite_url_substituted_in_html(client):
    html = client.get("/cafe.html").text
    assert "__OFFSITE_URL__" not in html and "http://localhost:" in html


def test_state_is_thread_safe():
    import threading

    st = FixtureState()
    threads = [threading.Thread(target=lambda: [st.record("x") for _ in range(200)]) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    seqs = [e.seq for e in st.events()]
    assert len(seqs) == 1600 and sorted(seqs) == list(range(1, 1601))


def test_cart_total_helper():
    assert cart_total_cents([{"sku": "blue-kettle", "qty": 2}]) == 6998
