import hashlib
import os

from scripts.build_env.tests.base_test import BaseTest

os.environ.setdefault("ENVIRONMENT_NAME", "env-01")
os.environ.setdefault("CLUSTER_NAME", "cluster-01")

# ---------------------------------------------------------------------------
# Python reference implementations of Java sensitive-parameter processing rules
# (ParametersCalculationServiceV2 + ApplicationConstants)
# ---------------------------------------------------------------------------

# ApplicationConstants.SECURED_KEYS — keys moved from insecure to secure map (copyParams)
SECURED_KEYS = [
    "DBAAS_AGGREGATOR_USERNAME",
    "DBAAS_AGGREGATOR_PASSWORD",
    "DBAAS_CLUSTER_DBA_CREDENTIALS_USERNAME",
    "DBAAS_CLUSTER_DBA_CREDENTIALS_PASSWORD",
    "MAAS_CREDENTIALS_USERNAME",
    "MAAS_CREDENTIALS_PASSWORD",
    "VAULT_TOKEN",
    "CONSUL_ADMIN_TOKEN",
    "SSL_SECRET_VALUE",
]


def _copy_params(secure: dict, insecure: dict, k8s_token: str) -> None:
    for key in SECURED_KEYS:
        if key in insecure:
            secure[key] = insecure.pop(key)
    secure["K8S_TOKEN"] = k8s_token


def _prepare_bundle_parameters(secure: dict, insecure: dict) -> None:
    bundle = insecure.get("DEFAULT_SSL_CERTIFICATES_BUNDLE")
    if bundle is not None:
        secure["SSL_SECRET_VALUE"] = bundle
        secure["CA_BUNDLE_CERTIFICATE"] = bundle
        if bundle:
            insecure["CERTIFICATE_BUNDLE_MD5SUM"] = hashlib.md5(bundle.encode()).hexdigest()


def _build_credentials(*, insecure: dict, k8s_token: str) -> tuple[dict, dict]:
    secure: dict = {}
    _copy_params(secure, insecure, k8s_token)
    _prepare_bundle_parameters(secure, insecure)
    return secure, insecure


# ---------------------------------------------------------------------------
# UC-ES-DEP-A6: K8S_TOKEN always in credentials.yaml
# ---------------------------------------------------------------------------

class TestK8sTokenInCredentials(BaseTest):
    """UC-ES-DEP-A6 — K8S_TOKEN always written into credentials.yaml."""

    def test_k8s_token_value_matches_input(self):
        # UC-ES-DEP-A6: K8S_TOKEN is unconditionally written; value matches the cluster token.
        # (ParametersCalculationServiceV2.copyParams line 256)
        token = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.example"
        secure, _ = _build_credentials(insecure={}, k8s_token=token)
        assert secure["K8S_TOKEN"] == token


# ---------------------------------------------------------------------------
# UC-ES-DEP-A6: SSL bundle duplication into credentials.yaml
# ---------------------------------------------------------------------------

class TestSslBundleDuplication(BaseTest):
    """UC-ES-DEP-A6 — DEFAULT_SSL_CERTIFICATES_BUNDLE copied into SSL_SECRET_VALUE
    and CA_BUNDLE_CERTIFICATE in credentials.yaml; MD5SUM written to insecure params."""

    BUNDLE = "-----BEGIN CERTIFICATE-----\nMIIEI...\n-----END CERTIFICATE-----\n"

    def test_both_ssl_keys_equal_bundle_value(self):
        # UC-ES-DEP-A6: SSL_SECRET_VALUE and CA_BUNDLE_CERTIFICATE both equal the bundle.
        # (ParametersCalculationServiceV2.prepareBundleParameters lines 234-241)
        secure, _ = _build_credentials(
            insecure={"DEFAULT_SSL_CERTIFICATES_BUNDLE": self.BUNDLE},
            k8s_token="tok",
        )
        assert secure["SSL_SECRET_VALUE"] == self.BUNDLE
        assert secure["CA_BUNDLE_CERTIFICATE"] == self.BUNDLE

    def test_md5sum_written_to_insecure_params_when_bundle_non_empty(self):
        # UC-ES-DEP-A6: CERTIFICATE_BUNDLE_MD5SUM written to deployment-parameters.yaml (insecure).
        _, insecure = _build_credentials(
            insecure={"DEFAULT_SSL_CERTIFICATES_BUNDLE": self.BUNDLE},
            k8s_token="tok",
        )
        assert "CERTIFICATE_BUNDLE_MD5SUM" in insecure
        assert insecure["CERTIFICATE_BUNDLE_MD5SUM"] == hashlib.md5(self.BUNDLE.encode()).hexdigest()

    def test_ssl_keys_and_md5sum_absent_when_bundle_not_set(self):
        # UC-ES-DEP-A6: no bundle → SSL_SECRET_VALUE, CA_BUNDLE_CERTIFICATE, MD5SUM all absent.
        secure, insecure = _build_credentials(insecure={}, k8s_token="tok")
        assert "SSL_SECRET_VALUE" not in secure
        assert "CA_BUNDLE_CERTIFICATE" not in secure
        assert "CERTIFICATE_BUNDLE_MD5SUM" not in insecure


# ---------------------------------------------------------------------------
# UC-ES-DEP-A6: SECURED_KEYS moved from insecure to credentials.yaml
# ---------------------------------------------------------------------------

class TestSecuredKeysMoved(BaseTest):
    """UC-ES-DEP-A6 — SECURED_KEYS moved from deployment-parameters.yaml to credentials.yaml;
    keys absent from insecure are not created in secure; non-secured keys stay in insecure."""

    def test_all_secured_keys_moved_when_present(self):
        # UC-ES-DEP-A6: all nine SECURED_KEYS present in insecure → in secure, removed from insecure.
        # (ParametersCalculationServiceV2.copyParams lines 250-255)
        input_insecure = {k: f"val-{k}" for k in SECURED_KEYS}
        secure, insecure = _build_credentials(insecure=input_insecure, k8s_token="tok")
        for key in SECURED_KEYS:
            assert key in secure, f"{key} must be in credentials.yaml"
            assert key not in insecure, f"{key} must be removed from deployment-parameters.yaml"

    def test_secured_key_absent_from_insecure_is_not_created_in_secure(self):
        # UC-ES-DEP-A6: SECURED_KEY absent from insecure → silently skipped, not in credentials.yaml.
        # Feature-disabled case: feature secrets appear ONLY when the feature is enabled (key present).
        secure, _ = _build_credentials(insecure={}, k8s_token="tok")
        for key in SECURED_KEYS:
            assert key not in secure

    def test_non_secured_key_stays_in_insecure(self):
        # UC-ES-DEP-A6: ordinary deployment parameter is NOT moved to credentials.yaml.
        _, insecure = _build_credentials(
            insecure={"CLOUD_API_HOST": "api.cluster-01.example.com"},
            k8s_token="tok",
        )
        assert "CLOUD_API_HOST" in insecure
