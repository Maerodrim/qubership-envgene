"""
Topology Context tests.

UC-ES-TOP-2 / UC-ES-TOP-3 — cluster endpoint fields in topology/parameters.yaml
are derived from Environment Inventory clusterUrl when Cloud Passport is not
configured.  The Java Calculator performs this derivation using the same
urlsplit logic exposed in scripts/build_env/jinja/jinja.py::urlsplit_filter and
the Jinja2 template env_config.yml.j2 (lines 55-59):

    cloud_api_protocol: scheme.upper()
    cloud_api_url:       hostname
    cloud_api_port:      port
    cloud_public_url:    hostname.replace('api.', '')

Python-level contract: urlsplit_filter must correctly decompose any clusterUrl
variant so that the downstream template and Java CLI receive the right values.

UC-ES-TOP-1 / UC-ES-TOP-6 (Cloud Passport) — the Calculator reads cloud.yml
populated by process_cloud_definition() (cloud_passport.py) via --envs-path and
overrides clusterUrl-derived values with passport data.  That override is Java-
side behaviour; the Python-level contract is covered by the fixture contract test
in test_fixture_contracts.py::TestTopologyOutputFiles.
End-to-end verification for all topology UCs lives in CmdbCliTest.java
(build_effective_set_generator/effective-set-generator/src/test/java/.../
CmdbCliTest.java).

Integration pattern: each test writes the clusterUrl value into a YAML file
(mimicking the env_definition.yml inventory section), reads it back via
openYaml, and passes the extracted value to urlsplit_filter — the same data
flow used at runtime when the Jinja template processes the inventory.
"""
import os
import sys
from pathlib import Path

import envgenehelper as helper
import logger
import yaml

from scripts.build_env.tests.base_test import BaseTest

os.environ.setdefault("ENVIRONMENT_NAME", "env-01")
os.environ.setdefault("CLUSTER_NAME", "cluster-01")

_BUILD_ENV = Path(__file__).resolve().parents[2]
if str(_BUILD_ENV) not in sys.path:
    sys.path.insert(0, str(_BUILD_ENV))

from jinja.jinja import urlsplit_filter

FEATURE_TEST_DIR = "test_topology_context"


def _write_yaml(path: Path, content: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(content, default_flow_style=False))


def _read_cluster_url(path: Path) -> str:
    return helper.openYaml(path)["clusterUrl"]


# ---------------------------------------------------------------------------
# UC-ES-TOP-2: standard clusterUrl parsing
# ---------------------------------------------------------------------------

class TestClusterUrlParsing(BaseTest):
    """
    UC-ES-TOP-2 — clusterUrl https://API.cl-03.managed.qubership.cloud:6443
    decomposes into the four cluster fields expected in topology/parameters.yaml.
    """

    def setup_method(self):
        self.feature_dir = self.output_dir / FEATURE_TEST_DIR / "top2"
        self.feature_dir.mkdir(parents=True, exist_ok=True)
        path = self.feature_dir / "inventory.yml"
        _write_yaml(path, {"clusterUrl": "https://API.cl-03.managed.qubership.cloud:6443"})
        self._url = _read_cluster_url(path)

    def test_hostname_extracted_as_api_url(self):
        # cloud_api_url = urlsplit(clusterUrl).hostname
        logger.info(f"Starting SD test:\n\tTest case: UC-ES-TOP-2")
        assert urlsplit_filter(self._url, "hostname") == "api.cl-03.managed.qubership.cloud"

    def test_port_extracted_as_api_port(self):
        # cloud_api_port = urlsplit(clusterUrl).port
        assert urlsplit_filter(self._url, "port") == 6443

    def test_scheme_extracted_as_protocol(self):
        # cloud_api_protocol = urlsplit(clusterUrl).scheme (template uppercases it)
        assert urlsplit_filter(self._url, "scheme") == "https"

    def test_public_url_derived_by_removing_api_prefix(self):
        # cloud_public_url = hostname.replace('api.', '')
        hostname = urlsplit_filter(self._url, "hostname")
        public_url = hostname.replace("api.", "")
        assert public_url == "cl-03.managed.qubership.cloud"


# ---------------------------------------------------------------------------
# UC-ES-TOP-3: clusterUrl parsing variants
# ---------------------------------------------------------------------------

class TestClusterUrlVariants(BaseTest):
    """
    UC-ES-TOP-3 — non-standard port, http protocol, and non-'api.' hostname
    all parse correctly so the Calculator produces the right cluster fields.
    """

    def setup_method(self):
        self.feature_dir = self.output_dir / FEATURE_TEST_DIR / "top3"
        self.feature_dir.mkdir(parents=True, exist_ok=True)

    def _url(self, cluster_url: str) -> str:
        path = self.feature_dir / f"inventory_{abs(hash(cluster_url))}.yml"
        _write_yaml(path, {"clusterUrl": cluster_url})
        return _read_cluster_url(path)

    def test_nonstandard_port_extracted_correctly(self):
        # Scenario port: port 8443 is preserved verbatim.
        logger.info(f"Starting SD test:\n\tTest case: UC-ES-TOP-3")
        url = self._url("https://API.cl-03.managed.qubership.cloud:8443")
        assert urlsplit_filter(url, "port") == 8443
        assert urlsplit_filter(url, "hostname") == "api.cl-03.managed.qubership.cloud"
        assert urlsplit_filter(url, "scheme") == "https"

    def test_nonstandard_port_public_url_strips_api_prefix(self):
        url = self._url("https://API.cl-03.managed.qubership.cloud:8443")
        hostname = urlsplit_filter(url, "hostname")
        assert hostname.replace("api.", "") == "cl-03.managed.qubership.cloud"

    def test_http_protocol_extracted_correctly(self):
        # Scenario protocol: http preserved; public_url still derives from hostname.
        url = self._url("http://API.cl-03.managed.qubership.cloud:6443")
        assert urlsplit_filter(url, "scheme") == "http"
        assert urlsplit_filter(url, "port") == 6443
        assert urlsplit_filter(url, "hostname") == "api.cl-03.managed.qubership.cloud"

    def test_http_protocol_public_url_strips_api_prefix(self):
        url = self._url("http://API.cl-03.managed.qubership.cloud:6443")
        hostname = urlsplit_filter(url, "hostname")
        assert hostname.replace("api.", "") == "cl-03.managed.qubership.cloud"

    def test_nonstandard_hostname_without_api_prefix(self):
        # Scenario hostname: hostname does not start with 'api.' →
        # public_url equals api_url (replace('api.', '') is a no-op).
        url = self._url("https://cluster.cl-03.managed.qubership.cloud:6443")
        hostname = urlsplit_filter(url, "hostname")
        assert hostname == "cluster.cl-03.managed.qubership.cloud"
        assert hostname.replace("api.", "") == "cluster.cl-03.managed.qubership.cloud"

    def test_nonstandard_hostname_port_and_scheme_correct(self):
        url = self._url("https://cluster.cl-03.managed.qubership.cloud:6443")
        assert urlsplit_filter(url, "port") == 6443
        assert urlsplit_filter(url, "scheme") == "https"


# ---------------------------------------------------------------------------
# urlsplit_filter contract: robustness
# ---------------------------------------------------------------------------

class TestUrlsplitFilterContract(BaseTest):
    """
    urlsplit_filter must handle edge cases gracefully — invalid input must not
    raise exceptions, and missing parts must return a falsy value.
    """

    def setup_method(self):
        self.feature_dir = self.output_dir / FEATURE_TEST_DIR / "contract"
        self.feature_dir.mkdir(parents=True, exist_ok=True)

    def _url(self, cluster_url, filename: str) -> object:
        path = self.feature_dir / filename
        _write_yaml(path, {"clusterUrl": cluster_url})
        return helper.openYaml(path)["clusterUrl"]

    def test_non_string_input_returns_empty_string(self):
        # Guard: non-string (e.g. None from missing YAML key) returns "" not exception.
        # Write YAML with null value — openYaml returns None for null keys.
        path = self.feature_dir / "inventory_null.yml"
        path.write_text("clusterUrl: null\n")
        value = helper.openYaml(path)["clusterUrl"]
        assert urlsplit_filter(value, "hostname") == ""

    def test_missing_port_returns_none(self):
        # URL with no explicit port → urlsplit returns None for port component.
        url = self._url("https://api.example.com", "inventory_no_port.yml")
        result = urlsplit_filter(url, "port")
        assert result is None

    def test_unknown_part_returns_empty_string(self):
        # Requesting a non-existent attribute falls back to "".
        url = self._url("https://api.example.com:6443", "inventory_unknown_part.yml")
        assert urlsplit_filter(url, "nonexistent_part") == ""

    def test_uppercase_hostname_lowercased_by_filter(self):
        # The filter must lowercase the hostname so topology/parameters.yaml always
        # gets a consistent api_url regardless of the original casing in clusterUrl.
        url = self._url("https://API.EXAMPLE.COM:6443", "inventory_upper.yml")
        hostname = urlsplit_filter(url, "hostname")
        assert hostname == "api.example.com"

    def test_trailing_slash_does_not_affect_hostname_or_port(self):
        url = self._url("https://api.cl-03.managed.qubership.cloud:6443/", "inventory_trailing_slash.yml")
        assert urlsplit_filter(url, "hostname") == "api.cl-03.managed.qubership.cloud"
        assert urlsplit_filter(url, "port") == 6443

    def test_empty_string_input_does_not_raise(self):
        # Empty string is a valid string — filter processes it without exception.
        # urlsplit("") returns SplitResult with all empty fields; hostname="" → None, port=None.
        url = self._url("", "inventory_empty.yml")
        assert urlsplit_filter(url, "hostname") is None
        assert urlsplit_filter(url, "port") is None
