import json
import threading
from functools import partial
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from housing.config import default_config, save_config
from housing.server import Handler
from housing.store import Store


def test_local_api_protects_configuration_and_imports(tmp_path):
    store = Store(tmp_path)
    save_config(tmp_path, default_config())
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, store=store, lock=threading.Lock()))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    try:
        assert json.load(urlopen(url + "/api/state"))["listings"] == []
        for headers in ({"Host": "untrusted.example"}, {"Origin": "https://untrusted.example"}):
            try:
                urlopen(Request(url + "/api/state", headers=headers))
                raise AssertionError("Non-local read accepted")
            except HTTPError as exc:
                assert exc.code == 403
        body = json.dumps({"listings": [{"id": "test", "rent": 2000}]}).encode()
        request = Request(url + "/api/import", data=body, headers={"Content-Type": "application/json", "Origin": "https://untrusted.example"})
        try:
            urlopen(request)
            raise AssertionError("Cross-origin write accepted")
        except HTTPError as exc:
            assert exc.code == 403
        assert store.listings() == []
        request.remove_header("Origin")
        assert json.load(urlopen(request))["observations_added"] == 1
        try:
            urlopen(url + "/../config.json")
            raise AssertionError("Private configuration served as static file")
        except HTTPError as exc:
            assert exc.code == 404
    finally:
        server.shutdown()
        server.server_close()
