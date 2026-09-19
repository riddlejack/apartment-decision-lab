import io
import zipfile

import pytest

from housing import network
from housing.config import default_config, save_config


def test_failed_download_preserves_existing_input(tmp_path, monkeypatch):
    target = tmp_path / 'cta.zip'
    target.write_bytes(b'previous input')
    class Response(io.BytesIO):
        headers = {}
    monkeypatch.setattr(network, '_request', lambda url: Response(b'<html>Error</html>'))
    with pytest.raises(zipfile.BadZipFile):
        network._download('https://example.org/gtfs.zip', target)
    assert target.read_bytes() == b'previous input'
    assert not list(tmp_path.glob('*.part'))


def test_network_reuses_inputs_without_network_and_records_config(tmp_path, monkeypatch):
    config = default_config()
    save_config(tmp_path, config)
    folder = tmp_path / 'network'
    folder.mkdir()
    for item in network.CHICAGO:
        (folder / item['name']).write_bytes(b'already downloaded')
    def unexpected(url):
        raise AssertionError('existing input downloaded again')
    monkeypatch.setattr(network, '_request', unexpected)
    result = network.prepare(tmp_path, config, download=True)
    assert all(item['status'] == 'reused' for item in result['files'])
    assert config['routing']['network_dir'] == str(folder)


def test_pace_feed_link_discovery_rejects_unrelated_links():
    parser = network.FeedLinks()
    parser.feed('<a href="https://other.example/gtfs.zip">Other</a><a href="/sites/default/files/2027-01/GTFS.zip">Schedule</a>')
    assert parser.links == ['https://www.pacebus.com/sites/default/files/2027-01/GTFS.zip']
