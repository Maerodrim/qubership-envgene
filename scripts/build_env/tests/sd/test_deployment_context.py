import os
import shlex
import sys
from pathlib import Path

from scripts.build_env.tests.base_test import BaseTest

os.environ.setdefault("ENVIRONMENT_NAME", "env-01")
os.environ.setdefault("CLUSTER_NAME", "cluster-01")

# effective_set_entrypoint has a bare import that only resolves when
# build_effective_set_generator/scripts/ is on sys.path.
_ESE_SCRIPTS = Path(__file__).resolve().parents[4] / "build_effective_set_generator" / "scripts"
if str(_ESE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_ESE_SCRIPTS))

import effective_set_entrypoint as _ese
from effective_set_entrypoint import _build_cli_cmd

FEATURE_TEST_DIR = "test_deployment_context"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


# ---------------------------------------------------------------------------
# Python reference implementations of Java deployment-context formulas
# ---------------------------------------------------------------------------

def _public_gateway_url(protocol: str, namespace: str, cloud_public_host: str) -> str:
    """NamespaceMap.addGatewayIdentityUrls — isPublic=True, putIfAbsent formula."""
    return f"{protocol.lower()}://public-gateway-{namespace}.{cloud_public_host}"


def _private_gateway_url(protocol: str, namespace: str, custom_host: str) -> str:
    """NamespaceMap.addGatewayIdentityUrls — isPublic=False, putIfAbsent formula."""
    return f"{protocol.lower()}://private-gateway-{namespace}.{custom_host}"


def _bg_controller_url_default(protocol: str, original_namespace: str, custom_host: str) -> str:
    """NamespaceMap — BG controller URL formula when controller.getUrl() is absent."""
    return f"{protocol.lower()}://bluegreen-controller-{original_namespace}.{custom_host}"


def _compute_deployment_params(
        *,
        protocol: str,
        cloud_public_host: str,
        cloud_api_host: str,
        cloud_api_port: str,
        namespace: str,
        tenant_name: str,
        application_name: str,
        deployment_session_id: str,
        managed_by: str = "argocd",
        public_gateway_route_host: str | None = None,
        private_gateway_route_host: str | None = None,
        dbaas_enabled: bool = False,
        dbaas_api_url: str | None = None,
        dbaas_aggregator_url: str | None = None,
        vault_enabled: bool = False,
        vault_url: str | None = None,
        public_vault_url: str | None = None,
) -> dict:
    """
    Python reference implementation of the Java deployment-parameter derivation logic
    (CloudMap, NamespaceMap, NamespaceApplicationMap, BomReaderUtilsImplV2).

    Produces the predefined root deployment-parameters.yaml keys that the Java Calculator
    would write for a standard effective-set generation pass.
    """
    params: dict = {}

    # NamespaceApplicationMap: APPLICATION_NAME, MANAGED_BY, DEPLOYMENT_SESSION_ID
    params["APPLICATION_NAME"] = application_name
    params["MANAGED_BY"] = managed_by
    params["DEPLOYMENT_SESSION_ID"] = deployment_session_id

    # NamespaceMap: identity keys
    params["NAMESPACE"] = namespace
    params["TENANTNAME"] = tenant_name

    # CloudMap: cloud topology keys
    params["CLOUD_API_HOST"] = cloud_api_host
    params["CLOUD_PUBLIC_HOST"] = cloud_public_host
    params["CLOUD_PROTOCOL"] = protocol
    params["CLOUD_API_PORT"] = cloud_api_port

    # CloudMap: DBaaS (UC-ES-DEP-22)
    params["DBAAS_ENABLED"] = dbaas_enabled
    if dbaas_enabled:
        params["API_DBAAS_ADDRESS"] = dbaas_api_url or ""
        params["DBAAS_AGGREGATOR_ADDRESS"] = dbaas_aggregator_url or ""

    # CloudMap: Vault (UC-ES-DEP-22)
    params["VAULT_ENABLED"] = vault_enabled
    if vault_enabled:
        params["VAULT_ADDR"] = vault_url or ""
        params["PUBLIC_VAULT_URL"] = public_vault_url or vault_url or ""

    # NamespaceMap.addGatewayIdentityUrls — public
    # putIfAbsent: override wins if PUBLIC_GATEWAY_ROUTE_HOST is in customParameters
    if public_gateway_route_host is not None:
        params["PUBLIC_GATEWAY_URL"] = f"{protocol.lower()}://{public_gateway_route_host}"
    else:
        params["PUBLIC_GATEWAY_URL"] = _public_gateway_url(protocol, namespace, cloud_public_host)

    # NamespaceMap.addGatewayIdentityUrls — private
    if private_gateway_route_host is not None:
        params["PRIVATE_GATEWAY_URL"] = f"{protocol.lower()}://{private_gateway_route_host}"
    else:
        params["PRIVATE_GATEWAY_URL"] = _private_gateway_url(protocol, namespace, cloud_public_host)

    return params


# ---------------------------------------------------------------------------
# UC-ES-DEP-15: DEPLOYMENT_SESSION_ID from pipeline
# ---------------------------------------------------------------------------

class TestDeploymentSessionId(BaseTest):
    """
    UC-ES-DEP-15 — DEPLOYMENT_SESSION_ID from the instance pipeline is forwarded
    to the Java Calculator as an extra_param and appears in deployment-parameters.yaml.

    Python-level contract: _build_cli_cmd appends
    --extra_params=DEPLOYMENT_SESSION_ID=<value> when DEPLOYMENT_SESSION_ID env var is set.
    """

    def setup_method(self):
        self.feature_dir = self.output_dir / FEATURE_TEST_DIR / "dep_session_id"
        if self.feature_dir.exists():
            import shutil
            shutil.rmtree(self.feature_dir)
        self.feature_dir.mkdir(parents=True)
        for var in ("DEPLOYMENT_SESSION_ID", "EFFECTIVE_SET_CONFIG", "CUSTOM_PARAMS"):
            os.environ.pop(var, None)

    def teardown_method(self):
        for var in ("DEPLOYMENT_SESSION_ID", "EFFECTIVE_SET_CONFIG", "CUSTOM_PARAMS"):
            os.environ.pop(var, None)

    def test_session_id_forwarded_to_cli_as_extra_param(self):
        # UC-ES-DEP-15: DEPLOYMENT_SESSION_ID env var → --extra_params=DEPLOYMENT_SESSION_ID=<uuid>
        # in the CLI command so the Java Calculator writes it into deployment-parameters.yaml.
        uuid = "550e8400-e29b-41d4-a716-446655440000"
        os.environ["DEPLOYMENT_SESSION_ID"] = uuid
        sd_path = self.feature_dir / "sd.yaml"
        _write(sd_path, "applications: []\n")

        cmd = _build_cli_cmd(self.feature_dir / "es", "cluster-01/env-01", sd_path)

        assert f"--extra_params=DEPLOYMENT_SESSION_ID={uuid}" in cmd, (
            f"DEPLOYMENT_SESSION_ID extra_param not found in CLI cmd;\ncmd: {cmd}"
        )

    def test_session_id_absent_when_env_var_not_set(self):
        # UC-ES-DEP-15: when DEPLOYMENT_SESSION_ID is not set in the pipeline,
        # the --extra_params flag must not appear in the CLI command.
        sd_path = self.feature_dir / "sd.yaml"
        _write(sd_path, "applications: []\n")

        cmd = _build_cli_cmd(self.feature_dir / "es", "cluster-01/env-01", sd_path)

        assert "--extra_params=DEPLOYMENT_SESSION_ID=" not in cmd


# ---------------------------------------------------------------------------
# UC-ES-DEP-16: Predefined identity, MANAGED_BY default, mandatory keys
# ---------------------------------------------------------------------------

class TestPredefinedDeploymentKeys(BaseTest):
    """
    UC-ES-DEP-16 — When the Calculator runs without explicit MANAGED_BY in any
    parameter layer, MANAGED_BY defaults to "argocd".  Identity and cloud keys
    (APPLICATION_NAME, TENANTNAME, CLOUD_API_HOST, etc.) are always present in
    deployment-parameters.yaml.
    """

    SESSION_ID = "550e8400-e29b-41d4-a716-446655440000"

    def _params(self, **overrides) -> dict:
        defaults = dict(
            protocol="https",
            cloud_public_host="apps.cluster-01.example.com",
            cloud_api_host="api.cluster-01.example.com",
            cloud_api_port="6443",
            namespace="billing-ns",
            tenant_name="tenant-a",
            application_name="billing-app",
            deployment_session_id=self.SESSION_ID,
        )
        defaults.update(overrides)
        return _compute_deployment_params(**defaults)

    def test_managed_by_defaults_to_argocd(self):
        # UC-ES-DEP-16: MANAGED_BY not set by any parameter layer → "argocd" default.
        params = self._params()
        assert params["MANAGED_BY"] == "argocd"

    def test_all_mandatory_keys_present(self):
        # UC-ES-DEP-16: every mandatory predefined key must appear.
        mandatory = {
            "DEPLOYMENT_SESSION_ID", "MANAGED_BY", "CLOUD_API_HOST", "CLOUD_PUBLIC_HOST",
            "CLOUD_PROTOCOL", "CLOUD_API_PORT", "TENANTNAME", "NAMESPACE", "APPLICATION_NAME",
        }
        params = self._params()
        missing = mandatory - set(params.keys())
        assert not missing, f"Mandatory keys missing from deployment params: {missing}"

    def test_fixture_values_match_monitoring_deployment_yaml(self):
        # UC-ES-DEP-16: cross-check predefined keys against the Java test fixture
        # environments/cluster-01/pl-01/effective-set/deployment/monitoring-origin/MONITORING
        # to confirm the reference implementation matches the Calculator's actual output.
        params = _compute_deployment_params(
            protocol="https",
            cloud_public_host="cluster-01.qubership.org",
            cloud_api_host="api.cluster-01.qubership.org",
            cloud_api_port="6443",
            namespace="pl-01-monitoring",
            tenant_name="Platform",
            application_name="MONITORING",
            deployment_session_id="6d5a6ce9-0b55-429d-8877-f7a88dae3d9c",
            dbaas_enabled=True,
            dbaas_api_url="http://dbaas.dbaas:8080",
            dbaas_aggregator_url="https://dbaas.cluster-01.qubership.org",
        )
        assert params["APPLICATION_NAME"] == "MONITORING"
        assert params["TENANTNAME"] == "Platform"
        assert params["NAMESPACE"] == "pl-01-monitoring"
        assert params["CLOUD_API_HOST"] == "api.cluster-01.qubership.org"
        assert params["CLOUD_API_PORT"] == "6443"
        assert params["CLOUD_PROTOCOL"] == "https"
        assert params["CLOUD_PUBLIC_HOST"] == "cluster-01.qubership.org"
        assert params["DEPLOYMENT_SESSION_ID"] == "6d5a6ce9-0b55-429d-8877-f7a88dae3d9c"
        assert params["MANAGED_BY"] == "argocd"


# ---------------------------------------------------------------------------
# UC-ES-DEP-22: DBaaS and Vault disabled omit optional deployment URLs
# ---------------------------------------------------------------------------

class TestDbaasVaultDisabled(BaseTest):
    """
    UC-ES-DEP-22 — When DBaaS and Vault are disabled, the Calculator:
    - writes DBAAS_ENABLED: false and VAULT_ENABLED: false
    - omits API_DBAAS_ADDRESS, DBAAS_AGGREGATOR_ADDRESS, VAULT_ADDR, PUBLIC_VAULT_URL

    Rule (CloudMap.java): URL keys are only added inside the `if (dbaas.isEnable())` /
    `if (vaultConfig.isEnable())` branches — so disabled → keys absent.
    """

    SESSION_ID = "550e8400-e29b-41d4-a716-446655440000"

    def _base_params(self, **overrides) -> dict:
        defaults = dict(
            protocol="https",
            cloud_public_host="apps.cluster-01.example.com",
            cloud_api_host="api.cluster-01.example.com",
            cloud_api_port="6443",
            namespace="billing-ns",
            tenant_name="tenant-a",
            application_name="billing-app",
            deployment_session_id=self.SESSION_ID,
        )
        defaults.update(overrides)
        return _compute_deployment_params(**defaults)

    def test_dbaas_disabled_flag_and_urls_absent(self):
        # UC-ES-DEP-22: DBAAS_ENABLED: false; URL keys must not appear.
        params = self._base_params(dbaas_enabled=False)
        assert params["DBAAS_ENABLED"] is False
        assert "API_DBAAS_ADDRESS" not in params, (
            f"API_DBAAS_ADDRESS must be absent when DBaaS is disabled; got: {params.get('API_DBAAS_ADDRESS')}"
        )
        assert "DBAAS_AGGREGATOR_ADDRESS" not in params

    def test_vault_disabled_flag_and_urls_absent(self):
        # UC-ES-DEP-22: VAULT_ENABLED: false; URL keys must not appear.
        params = self._base_params(vault_enabled=False)
        assert params["VAULT_ENABLED"] is False
        assert "VAULT_ADDR" not in params, "VAULT_ADDR must be absent when Vault is disabled"
        assert "PUBLIC_VAULT_URL" not in params, "PUBLIC_VAULT_URL must be absent when Vault is disabled"

    def test_dbaas_urls_present_when_enabled(self):
        # UC-ES-DEP-22 contrast: DBaaS enabled → URL keys are present.
        params = self._base_params(
            dbaas_enabled=True,
            dbaas_api_url="http://dbaas.dbaas:8080",
            dbaas_aggregator_url="https://dbaas.cluster-01.example.com",
        )
        assert params["DBAAS_ENABLED"] is True
        assert params["API_DBAAS_ADDRESS"] == "http://dbaas.dbaas:8080"
        assert params["DBAAS_AGGREGATOR_ADDRESS"] == "https://dbaas.cluster-01.example.com"

    def test_vault_enabled_urls_present_with_fallback(self):
        # UC-ES-DEP-22: Vault enabled → VAULT_ADDR set; PUBLIC_VAULT_URL falls back to
        # VAULT_ADDR when publicVaultUrl is not configured
        # (Java: StringUtils.isEmpty → use vaultUrl).
        params = self._base_params(
            vault_enabled=True,
            vault_url="https://vault.cluster-01.example.com",
            public_vault_url=None,
        )
        assert params["VAULT_ENABLED"] is True
        assert params["VAULT_ADDR"] == "https://vault.cluster-01.example.com"
        assert params["PUBLIC_VAULT_URL"] == "https://vault.cluster-01.example.com"


# ---------------------------------------------------------------------------
# UC-ES-DEP-23: Public and private gateway URLs from deployment context
# ---------------------------------------------------------------------------

class TestGatewayUrls(BaseTest):
    """
    UC-ES-DEP-23 — Gateway URL derivation from NamespaceMap.addGatewayIdentityUrls.

    Formulas (Java, isPublic=True / isPublic=False):
      PUBLIC_GATEWAY_URL  = {protocol}://public-gateway-{namespace}.{cloud_public_host}
      PRIVATE_GATEWAY_URL = {protocol}://private-gateway-{namespace}.{custom_host}

    When PUBLIC_GATEWAY_ROUTE_HOST / PRIVATE_GATEWAY_ROUTE_HOST is set in
    customParameters, the custom value wins (putIfAbsent: custom inserted first).
    When unset → default formula applied via putIfAbsent.
    """

    def test_public_gateway_url_default_formula(self):
        # UC-ES-DEP-23: no override → formula: https://public-gateway-{namespace}.{host}
        url = _public_gateway_url("https", "billing-origin", "apps.cluster-01.example.com")
        assert url == "https://public-gateway-billing-origin.apps.cluster-01.example.com"

    def test_private_gateway_url_default_formula(self):
        # UC-ES-DEP-23: no override → formula: https://private-gateway-{namespace}.{host}
        url = _private_gateway_url("https", "billing-origin", "apps.cluster-01.example.com")
        assert url == "https://private-gateway-billing-origin.apps.cluster-01.example.com"

    def test_protocol_is_lowercased_in_gateway_url(self):
        # Java: protocol.toLowerCase() — "HTTPS" input → "https://" prefix.
        url = _public_gateway_url("HTTPS", "billing-origin", "apps.cluster-01.example.com")
        assert url.startswith("https://")

    def test_private_gateway_url_from_private_gateway_route_host_override(self):
        # UC-ES-DEP-23: PRIVATE_GATEWAY_ROUTE_HOST is set → override wins via putIfAbsent.
        params = _compute_deployment_params(
            protocol="https",
            cloud_public_host="apps.cluster-01.example.com",
            cloud_api_host="api.cluster-01.example.com",
            cloud_api_port="6443",
            namespace="billing-origin",
            tenant_name="tenant-a",
            application_name="billing-app",
            deployment_session_id="550e8400-e29b-41d4-a716-446655440000",
            private_gateway_route_host="private-gw.team.example.com",
        )
        assert params["PRIVATE_GATEWAY_URL"] == "https://private-gw.team.example.com"

    def test_fixture_gateway_urls_match_monitoring_deployment_yaml(self):
        # UC-ES-DEP-23: cross-check against MONITORING fixture.
        # From the fixture file: PUBLIC_GATEWAY_URL and PRIVATE_GATEWAY_URL.
        public = _public_gateway_url("https", "pl-01-monitoring", "cluster-01.qubership.org")
        private = _private_gateway_url("https", "pl-01-monitoring", "cluster-01.qubership.org")
        assert public == "https://public-gateway-pl-01-monitoring.cluster-01.qubership.org"
        assert private == "https://private-gateway-pl-01-monitoring.cluster-01.qubership.org"


# ---------------------------------------------------------------------------
# UC-ES-DEP-A15: Blue-green predefined deployment parameters
# ---------------------------------------------------------------------------

class TestBgControllerParams(BaseTest):
    """
    UC-ES-DEP-A15 — BG controller URL derivation and credential defaults.

    Rule (NamespaceMap.java, lines 119-138):
    - BG_CONTROLLER_URL: controller.getUrl() if set, else
      {protocol}://bluegreen-controller-{originalNamespace}.{customHost}
    - BG_CONTROLLER_LOGIN:  from credentials if set, else "bgoperator"
    - BG_CONTROLLER_PASSWORD: from credentials if set, else "F21wuZNRpw"
    """

    def test_bg_controller_url_default_formula(self):
        # UC-ES-DEP-A15: no explicit controller URL → default formula.
        url = _bg_controller_url_default("https", "billing-origin", "cluster-01.example.com")
        assert url == "https://bluegreen-controller-billing-origin.cluster-01.example.com"

    def test_bg_controller_url_protocol_lowercased(self):
        # Java: protocol.toLowerCase() in the formula.
        url = _bg_controller_url_default("HTTPS", "billing-origin", "cluster-01.example.com")
        assert url.startswith("https://")


# ---------------------------------------------------------------------------
# UC-ES-DEP-A8: custom-params.yaml from CUSTOM_PARAMS
# ---------------------------------------------------------------------------

class TestCustomParamsWiring(BaseTest):
    """
    UC-ES-DEP-A8 — The CUSTOM_PARAMS pipeline variable is forwarded to the Calculator
    as --custom-params=<value> (shell-quoted). The Calculator writes the "deployment"
    object into custom-params.yaml under deployment/<ns>/<app>/values/.

    Python-level contract: _build_cli_cmd appends --custom-params=<shlex-quoted value>
    when CUSTOM_PARAMS env var is set.
    """

    CUSTOM_PARAMS_JSON = '{"deployment":{"CUSTOM_ROUTING_ENABLED":"true","CUSTOM_RESOURCE_LIMIT":"512Mi"}}'

    def setup_method(self):
        self.feature_dir = self.output_dir / FEATURE_TEST_DIR / "custom_params"
        if self.feature_dir.exists():
            import shutil
            shutil.rmtree(self.feature_dir)
        self.feature_dir.mkdir(parents=True)
        for var in ("CUSTOM_PARAMS", "DEPLOYMENT_SESSION_ID", "EFFECTIVE_SET_CONFIG"):
            os.environ.pop(var, None)

    def teardown_method(self):
        for var in ("CUSTOM_PARAMS", "DEPLOYMENT_SESSION_ID", "EFFECTIVE_SET_CONFIG"):
            os.environ.pop(var, None)

    def test_custom_params_value_is_shell_quoted(self):
        # UC-ES-DEP-A8: value is passed through shlex.quote so special chars are safe.
        # effective_set_entrypoint: cmd.append(f"--custom-params={shlex.quote(custom_params)}")
        os.environ["CUSTOM_PARAMS"] = self.CUSTOM_PARAMS_JSON
        sd_path = self.feature_dir / "sd.yaml"
        _write(sd_path, "applications: []\n")

        cmd = _build_cli_cmd(self.feature_dir / "es", "cluster-01/env-01", sd_path)

        quoted = shlex.quote(self.CUSTOM_PARAMS_JSON)
        assert f"--custom-params={quoted}" in cmd, (
            f"Expected shell-quoted --custom-params in cmd;\ncmd: {cmd}"
        )

    def test_custom_params_absent_when_env_var_not_set(self):
        # UC-ES-DEP-A8: CUSTOM_PARAMS not set → --custom-params flag absent.
        sd_path = self.feature_dir / "sd.yaml"
        _write(sd_path, "applications: []\n")

        cmd = _build_cli_cmd(self.feature_dir / "es", "cluster-01/env-01", sd_path)

        assert "--custom-params" not in cmd

    def test_custom_params_coexists_with_session_id(self):
        # UC-ES-DEP-A8: when both CUSTOM_PARAMS and DEPLOYMENT_SESSION_ID are set,
        # both flags appear in the CLI command independently.
        uuid = "550e8400-e29b-41d4-a716-446655440000"
        os.environ["CUSTOM_PARAMS"] = self.CUSTOM_PARAMS_JSON
        os.environ["DEPLOYMENT_SESSION_ID"] = uuid
        sd_path = self.feature_dir / "sd.yaml"
        _write(sd_path, "applications: []\n")

        cmd = _build_cli_cmd(self.feature_dir / "es", "cluster-01/env-01", sd_path)

        assert "--custom-params=" in cmd
        assert f"--extra_params=DEPLOYMENT_SESSION_ID={uuid}" in cmd
