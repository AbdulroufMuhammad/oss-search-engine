import pytest

from shared.url_safety import UnsafeUrlError, assert_safe_url


def test_blocks_non_http_scheme():
    with pytest.raises(UnsafeUrlError):
        assert_safe_url("ftp://example.com/file")


def test_blocks_file_scheme():
    with pytest.raises(UnsafeUrlError):
        assert_safe_url("file:///etc/passwd")


def test_blocks_loopback_hostname():
    with pytest.raises(UnsafeUrlError):
        assert_safe_url("http://127.0.0.1:8081/search")


def test_blocks_loopback_by_name():
    with pytest.raises(UnsafeUrlError):
        assert_safe_url("http://localhost/internal")


def test_blocks_private_ip():
    with pytest.raises(UnsafeUrlError):
        assert_safe_url("http://10.0.0.5/")


def test_blocks_link_local_cloud_metadata():
    with pytest.raises(UnsafeUrlError):
        assert_safe_url("http://169.254.169.254/latest/meta-data/")


def test_blocks_url_with_no_hostname():
    with pytest.raises(UnsafeUrlError):
        assert_safe_url("http:///path")


def test_allows_real_public_url():
    assert_safe_url("https://example.com/")


def test_allows_another_real_public_url():
    assert_safe_url("https://www.python.org/")
