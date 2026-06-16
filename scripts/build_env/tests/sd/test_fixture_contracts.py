"""
Fixture contract tests — read the Java test fixtures verbatim and assert
cross-file invariants that CmdbCliTest.java does not check explicitly.

These tests do NOT run Java code.  Their purpose is:
  1. Document UC specifications as executable assertions.
  2. Catch inconsistencies between fixture files (e.g. mapping keys vs directory names).
  3. Fail fast when someone edits a fixture manually and breaks a contract.

All fixture paths are under:
  build_effective_set_generator/effective-set-generator/src/test/resources/
  environments/cluster-01/pl-01/effective-set/
"""
import os
import sys
from pathlib import Path

import pytest

from scripts.build_env.tests.base_test import BaseTest

os.environ.setdefault("ENVIRONMENT_NAME", "env-01")
os.environ.setdefault("CLUSTER_NAME", "cluster-01")

_ESE_SCRIPTS = Path(__file__).resolve().parents[4] / "build_effective_set_generator" / "scripts"
if str(_ESE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_ESE_SCRIPTS))

from envgenehelper.yaml_helper import openYaml

_FIXTURES = (
    Path(__file__).resolve().parents[4]
    / "build_effective_set_generator"
    / "effective-set-generator"
    / "src" / "test" / "resources"
    / "environments" / "cluster-01" / "pl-01" / "effective-set"
)

_SECURED_KEYS = {
    "DBAAS_AGGREGATOR_USERNAME", "DBAAS_AGGREGATOR_PASSWORD",
    "DBAAS_CLUSTER_DBA_CREDENTIALS_USERNAME", "DBAAS_CLUSTER_DBA_CREDENTIALS_PASSWORD",
    "MAAS_CREDENTIALS_USERNAME", "MAAS_CREDENTIALS_PASSWORD",
    "VAULT_TOKEN", "CONSUL_ADMIN_TOKEN", "SSL_SECRET_VALUE",
}


def _load(rel: str) -> dict:
    return dict(openYaml(_FIXTURES / rel))


def _exists(rel: str) -> bool:
    return (_FIXTURES / rel).exists()


# ---------------------------------------------------------------------------
# UC-ES-DEP-A14 / UC-ES-RUN-3 / UC-ES-CLN-3: mapping key consistency
# ---------------------------------------------------------------------------

class TestMappingKeyConsistency(BaseTest):
    """
    UC-ES-DEP-A14 / UC-ES-RUN-3 / UC-ES-CLN-3 — deployment, runtime, and cleanup
    mapping.yaml must all carry the same namespace keys; only the context segment
    of the path value differs.
    """

    def test_all_three_mapping_files_have_identical_key_sets(self):
        # UC-ES-DEP-A14 / RUN-3 / CLN-3: namespace keys in all three mapping files
        # must be exactly the same set.
        dep = set(_load("deployment/mapping.yaml").keys())
        run = set(_load("runtime/mapping.yaml").keys())
        cln = set(_load("cleanup/mapping.yaml").keys())
        assert dep == run == cln, (
            f"mapping.yaml key sets differ: deployment={dep}, runtime={run}, cleanup={cln}"
        )

    def test_deployment_mapping_values_contain_deployment_segment(self):
        # UC-ES-DEP-A14: every value in deployment/mapping.yaml must contain
        # "/effective-set/deployment/" — not runtime or cleanup.
        for key, val in _load("deployment/mapping.yaml").items():
            assert "/effective-set/deployment/" in val, (
                f"deployment mapping key '{key}' has wrong path: {val}"
            )

    def test_runtime_mapping_values_contain_runtime_segment(self):
        # UC-ES-RUN-3: values in runtime/mapping.yaml must contain "/effective-set/runtime/".
        for key, val in _load("runtime/mapping.yaml").items():
            assert "/effective-set/runtime/" in val, (
                f"runtime mapping key '{key}' has wrong path: {val}"
            )

    def test_cleanup_mapping_values_contain_cleanup_segment(self):
        # UC-ES-CLN-3: values in cleanup/mapping.yaml must contain "/effective-set/cleanup/".
        for key, val in _load("cleanup/mapping.yaml").items():
            assert "/effective-set/cleanup/" in val, (
                f"cleanup mapping key '{key}' has wrong path: {val}"
            )

    def test_mapping_keys_start_with_environments_prefix(self):
        # UC-ES-DEP-A14: values use /environments/... prefix as specified.
        for val in _load("deployment/mapping.yaml").values():
            assert val.startswith("/environments/"), (
                f"deployment mapping value must start with /environments/: {val}"
            )

    def test_deployment_mapping_namespace_folders_exist(self):
        # UC-ES-DEP-A14: each namespace folder referenced in deployment/mapping.yaml
        # must actually exist under deployment/.
        for key, val in _load("deployment/mapping.yaml").items():
            ns_folder = val.split("/effective-set/deployment/")[-1]
            assert (_FIXTURES / "deployment" / ns_folder).is_dir(), (
                f"namespace folder for key '{key}' does not exist: deployment/{ns_folder}"
            )

    def test_fixture_mapping_keys(self):
        # UC-ES-DEP-A14: cross-check exact fixture values from the Java test run.
        dep = _load("deployment/mapping.yaml")
        assert dep["pl-01-monitoring"] == (
            "/environments/cluster-01/pl-01/effective-set/deployment/monitoring-origin"
        )
        assert dep["pl-01-pg"] == (
            "/environments/cluster-01/pl-01/effective-set/deployment/pg"
        )


# ---------------------------------------------------------------------------
# UC-ES-DEP-16 / UC-ES-DEP-22 / UC-ES-DEP-23: deployment-parameters.yaml content
# ---------------------------------------------------------------------------

class TestDeploymentParametersContent(BaseTest):
    """
    UC-ES-DEP-16 / UC-ES-DEP-22 / UC-ES-DEP-23 — deployment-parameters.yaml
    for MONITORING contains mandatory identity keys, DBaaS URLs (enabled),
    and gateway URL formulas.
    """

    @pytest.fixture(autouse=True)
    def _params(self):
        self._p = _load(
            "deployment/monitoring-origin/MONITORING/values/deployment-parameters.yaml"
        )

    def test_mandatory_identity_keys_present(self):
        # UC-ES-DEP-16: predefined identity keys always written.
        for key in ("APPLICATION_NAME", "NAMESPACE", "TENANTNAME", "MANAGED_BY",
                    "CLOUD_API_HOST", "CLOUD_API_PORT", "CLOUD_PROTOCOL",
                    "CLOUD_PUBLIC_HOST", "DEPLOYMENT_SESSION_ID"):
            assert key in self._p, f"mandatory key missing: {key}"

    def test_managed_by_is_argocd(self):
        # UC-ES-DEP-16: MANAGED_BY defaults to argocd.
        assert self._p["MANAGED_BY"] == "argocd"

    def test_dbaas_enabled_and_urls_present(self):
        # UC-ES-DEP-22: DBaaS enabled → DBAAS_ENABLED true and URL keys present.
        assert self._p["DBAAS_ENABLED"] is True
        assert "API_DBAAS_ADDRESS" in self._p
        assert "DBAAS_AGGREGATOR_ADDRESS" in self._p

    def test_public_gateway_url_formula(self):
        # UC-ES-DEP-23: PUBLIC_GATEWAY_URL = {protocol}://public-gateway-{namespace}.{host}
        ns = self._p["NAMESPACE"]
        host = self._p["CLOUD_PUBLIC_HOST"]
        proto = self._p["CLOUD_PROTOCOL"]
        expected = f"{proto}://public-gateway-{ns}.{host}"
        assert self._p["PUBLIC_GATEWAY_URL"] == expected

    def test_private_gateway_url_formula(self):
        # UC-ES-DEP-23: PRIVATE_GATEWAY_URL = {protocol}://private-gateway-{namespace}.{host}
        ns = self._p["NAMESPACE"]
        host = self._p["CLOUD_PUBLIC_HOST"]
        proto = self._p["CLOUD_PROTOCOL"]
        expected = f"{proto}://private-gateway-{ns}.{host}"
        assert self._p["PRIVATE_GATEWAY_URL"] == expected

    def test_secured_keys_absent_from_deployment_parameters(self):
        # UC-ES-DEP-A6: SECURED_KEYS must not appear in deployment-parameters.yaml —
        # they belong in credentials.yaml only.
        found = _SECURED_KEYS & set(self._p.keys())
        assert not found, f"SECURED_KEYS must not be in deployment-parameters.yaml: {found}"


# ---------------------------------------------------------------------------
# UC-ES-DEP-A6: credentials.yaml content
# ---------------------------------------------------------------------------

class TestCredentialsContent(BaseTest):
    """
    UC-ES-DEP-A6 — credentials.yaml for MONITORING must contain K8S_TOKEN and
    the secured credential keys; none of these may appear in deployment-parameters.yaml.
    """

    @pytest.fixture(autouse=True)
    def _creds(self):
        self._c = _load(
            "deployment/monitoring-origin/MONITORING/values/credentials.yaml"
        )

    def test_k8s_token_in_credentials(self):
        # UC-ES-DEP-A6: K8S_TOKEN always written to credentials.yaml.
        assert "K8S_TOKEN" in self._c

    def test_secured_keys_present_in_credentials(self):
        # UC-ES-DEP-A6: SECURED_KEYS present in insecure params are moved here.
        # Fixture has DBaaS, MaaS, Consul credentials.
        for key in ("DBAAS_AGGREGATOR_USERNAME", "DBAAS_AGGREGATOR_PASSWORD",
                    "MAAS_CREDENTIALS_USERNAME", "MAAS_CREDENTIALS_PASSWORD",
                    "CONSUL_ADMIN_TOKEN"):
            assert key in self._c, f"secured key missing from credentials.yaml: {key}"

    def test_credentials_and_deployment_params_share_no_secured_keys(self):
        # UC-ES-DEP-A6: no key can be in both credentials.yaml and
        # deployment-parameters.yaml simultaneously.
        dep = set(_load(
            "deployment/monitoring-origin/MONITORING/values/deployment-parameters.yaml"
        ).keys())
        overlap = (_SECURED_KEYS | {"K8S_TOKEN"}) & dep
        assert not overlap, (
            f"keys present in both credentials and deployment-parameters: {overlap}"
        )


# ---------------------------------------------------------------------------
# UC-ES-DEP-20: collision-deployment-parameters.yaml
# ---------------------------------------------------------------------------

class TestCollisionDeploymentParameters(BaseTest):
    """
    UC-ES-DEP-20 — collision-deployment-parameters.yaml exists for every
    application; keys in it must not appear in deployment-parameters.yaml.
    """

    def test_collision_file_exists_for_monitoring(self):
        # UC-ES-DEP-20: file is always written (empty when no collisions).
        assert _exists(
            "deployment/monitoring-origin/MONITORING/values/collision-deployment-parameters.yaml"
        )

    def test_collision_file_exists_for_postgres(self):
        assert _exists(
            "deployment/pg/postgres/values/collision-deployment-parameters.yaml"
        )

    def test_collision_keys_absent_from_main_deployment_parameters(self):
        # UC-ES-DEP-20: keys routed to collision must be removed from main params.
        collision = _load(
            "deployment/monitoring-origin/MONITORING/values/collision-deployment-parameters.yaml"
        )
        if not collision:
            return  # empty fixture — no collision keys to check
        dep = _load(
            "deployment/monitoring-origin/MONITORING/values/deployment-parameters.yaml"
        )
        overlap = set(collision.keys()) & set(dep.keys())
        assert not overlap, (
            f"collision keys found in deployment-parameters.yaml: {overlap}"
        )


# ---------------------------------------------------------------------------
# UC-ES-DEP-15: DEPLOYMENT_SESSION_ID consistency across output files
# ---------------------------------------------------------------------------

class TestDeploymentSessionIdConsistency(BaseTest):
    """
    UC-ES-DEP-15 — DEPLOYMENT_SESSION_ID must be the same value in
    deployment-parameters.yaml and deploy-descriptor.yaml for the same run.
    """

    def test_session_id_matches_in_deployment_params_and_deploy_descriptor(self):
        # UC-ES-DEP-15: session ID written by CLI must be consistent.
        dep = _load(
            "deployment/monitoring-origin/MONITORING/values/deployment-parameters.yaml"
        )
        dd = _load(
            "deployment/monitoring-origin/MONITORING/values/deploy-descriptor.yaml"
        )
        assert dep["DEPLOYMENT_SESSION_ID"] == dd["DEPLOYMENT_SESSION_ID"], (
            "DEPLOYMENT_SESSION_ID differs between deployment-parameters.yaml and "
            "deploy-descriptor.yaml"
        )


# ---------------------------------------------------------------------------
# UC-ES-DEP-A9: deploy-descriptor.yaml structure
# ---------------------------------------------------------------------------

class TestDeployDescriptorStructure(BaseTest):
    """
    UC-ES-DEP-A9 — deploy-descriptor.yaml has required top-level keys and
    the correct shape for image-type services (artifacts always empty list).
    """

    @pytest.fixture(autouse=True)
    def _dd(self):
        self._d = _load(
            "deployment/monitoring-origin/MONITORING/values/deploy-descriptor.yaml"
        )

    def test_top_level_keys_present(self):
        # UC-ES-DEP-A9: global, deployDescriptor, APPLICATION_NAME, DEPLOYMENT_SESSION_ID,
        # MANAGED_BY must exist at root level.
        for key in ("global", "deployDescriptor", "APPLICATION_NAME",
                    "DEPLOYMENT_SESSION_ID", "MANAGED_BY"):
            assert key in self._d, f"top-level key missing from deploy-descriptor.yaml: {key}"

    def test_deploy_descriptor_section_is_non_empty(self):
        # UC-ES-DEP-A9: deployDescriptor must contain at least one service entry.
        assert self._d["deployDescriptor"], "deployDescriptor section must not be empty"

    def test_image_service_has_empty_artifacts_list(self):
        # UC-ES-DEP-A9: image-type services always have artifacts: [].
        dd_section = self._d["deployDescriptor"]
        # alertmanager is application/octet-stream — always empty artifacts
        assert dd_section["alertmanager"]["artifacts"] == [], (
            "alertmanager (image service) must have artifacts: [] in deploy-descriptor"
        )

    def test_image_service_has_docker_fields(self):
        # UC-ES-DEP-A9: image-type service has docker_registry and full_image_name.
        svc = self._d["deployDescriptor"]["alertmanager"]
        assert "docker_registry" in svc
        assert "full_image_name" in svc


# ---------------------------------------------------------------------------
# UC-ES-DEP-A11: per-service-parameters structure
# ---------------------------------------------------------------------------

class TestPerServiceParametersStructure(BaseTest):
    """
    UC-ES-DEP-A11 — per-service-parameters/ directory exists under each
    application's values/; each service entry has the required predefined keys.
    """

    def test_per_service_parameters_dir_exists_for_monitoring(self):
        # UC-ES-DEP-A11: charted SBOM → per-service-parameters/{chart}/ created.
        assert (_FIXTURES / "deployment/monitoring-origin/MONITORING/values/"
                "per-service-parameters").is_dir()

    def test_per_service_parameters_dir_exists_for_postgres(self):
        assert (_FIXTURES / "deployment/pg/postgres/values/"
                "per-service-parameters").is_dir()

    def test_per_service_entries_have_required_keys(self):
        # UC-ES-DEP-A11: each service entry has SERVICE_NAME, DEPLOYMENT_VERSION,
        # DEPLOYMENT_RESOURCE_NAME, ARTIFACT_DESCRIPTOR_VERSION.
        params = _load(
            "deployment/pg/postgres/values/per-service-parameters/"
            "postgres/deployment-parameters.yaml"
        )
        for svc_name, svc_params in params.items():
            for key in ("SERVICE_NAME", "DEPLOYMENT_VERSION",
                        "DEPLOYMENT_RESOURCE_NAME", "ARTIFACT_DESCRIPTOR_VERSION"):
                assert key in svc_params, (
                    f"per-service key '{key}' missing for service '{svc_name}'"
                )

    def test_service_name_value_matches_key(self):
        # UC-ES-DEP-A11: SERVICE_NAME value equals the map key (service name).
        params = _load(
            "deployment/pg/postgres/values/per-service-parameters/"
            "postgres/deployment-parameters.yaml"
        )
        for svc_name, svc_params in params.items():
            assert svc_params["SERVICE_NAME"] == svc_name, (
                f"SERVICE_NAME value '{svc_params['SERVICE_NAME']}' "
                f"does not match map key '{svc_name}'"
            )

    def test_deployment_version_is_v1(self):
        # UC-ES-DEP-A11: DEPLOYMENT_VERSION is always "v1" (suffix convention).
        params = _load(
            "deployment/pg/postgres/values/per-service-parameters/"
            "postgres/deployment-parameters.yaml"
        )
        for svc_name, svc_params in params.items():
            assert svc_params["DEPLOYMENT_VERSION"] == "v1", (
                f"DEPLOYMENT_VERSION must be 'v1' for service '{svc_name}'"
            )


# ---------------------------------------------------------------------------
# UC-ES-RUN-1 / UC-ES-RUN-2: runtime output files exist
# ---------------------------------------------------------------------------

class TestRuntimeOutputFiles(BaseTest):
    """
    UC-ES-RUN-1 / UC-ES-RUN-2 — runtime/parameters.yaml and
    runtime/credentials.yaml exist for each processed application.
    """

    def test_runtime_parameters_yaml_exists_for_monitoring(self):
        # UC-ES-RUN-1: runtime non-sensitive output written per namespace/app.
        assert _exists("runtime/monitoring-origin/MONITORING/parameters.yaml")

    def test_runtime_credentials_yaml_exists_for_monitoring(self):
        # UC-ES-RUN-2: runtime sensitive output written per namespace/app.
        assert _exists("runtime/monitoring-origin/MONITORING/credentials.yaml")

    def test_runtime_parameters_yaml_exists_for_postgres(self):
        assert _exists("runtime/pg/postgres/parameters.yaml")

    def test_runtime_credentials_yaml_exists_for_postgres(self):
        assert _exists("runtime/pg/postgres/credentials.yaml")

    def test_runtime_parameters_contains_technical_config_keys(self):
        # UC-ES-RUN-1: technicalConfigurationParameters from cloud/namespace are
        # merged into runtime/parameters.yaml.
        params = _load("runtime/monitoring-origin/MONITORING/parameters.yaml")
        # cloud.yml has integrations.ndo-api-gw.url; namespace has TECHNICAL_PARAM_1
        assert "integrations.ndo-api-gw.url" in params
        assert "TECHNICAL_PARAM_1" in params


# ---------------------------------------------------------------------------
# UC-ES-PIPE-1: pipeline output files exist and have expected content
# ---------------------------------------------------------------------------

class TestPipelineOutputFiles(BaseTest):
    """
    UC-ES-PIPE-1 — pipeline/parameters.yaml and pipeline/credentials.yaml
    exist; parameters.yaml contains e2eParameters from cloud.
    """

    def test_pipeline_parameters_yaml_exists(self):
        # UC-ES-PIPE-1: non-sensitive e2eParameters written to pipeline/parameters.yaml.
        assert _exists("pipeline/parameters.yaml")

    def test_pipeline_credentials_yaml_exists(self):
        # UC-ES-PIPE-1: sensitive e2eParameters written to pipeline/credentials.yaml.
        assert _exists("pipeline/credentials.yaml")

    def test_pipeline_parameters_contains_cloud_e2e_key(self):
        # UC-ES-PIPE-1: cloud.yml e2eParameters.CLOUD_LEVEL_PARAM_1 appears in
        # pipeline/parameters.yaml (non-sensitive split).
        params = _load("pipeline/parameters.yaml")
        assert "CLOUD_LEVEL_PARAM_1" in params
        assert params["CLOUD_LEVEL_PARAM_1"] == "cloud-level-value-1"


# ---------------------------------------------------------------------------
# UC-ES-CLN-3: cleanup output files exist
# ---------------------------------------------------------------------------

class TestCleanupOutputFiles(BaseTest):
    """
    UC-ES-CLN-3 — cleanup/parameters.yaml and cleanup/credentials.yaml exist
    for each namespace; credentials.yaml contains K8S_TOKEN.
    """

    def test_cleanup_parameters_yaml_exists_for_monitoring(self):
        assert _exists("cleanup/monitoring-origin/parameters.yaml")

    def test_cleanup_credentials_yaml_exists_for_monitoring(self):
        assert _exists("cleanup/monitoring-origin/credentials.yaml")

    def test_cleanup_credentials_contains_k8s_token(self):
        # UC-ES-CLN-3 / UC-ES-DEP-A6: K8S_TOKEN in cleanup credentials as well.
        creds = _load("cleanup/monitoring-origin/credentials.yaml")
        assert "K8S_TOKEN" in creds

    def test_topology_files_exist(self):
        # Topology parameters and credentials written for BG domain context.
        assert _exists("topology/parameters.yaml")
        assert _exists("topology/credentials.yaml")

    def test_topology_parameters_contains_cluster_and_namespaces(self):
        # topology/parameters.yaml has cluster config and namespace mapping.
        params = _load("topology/parameters.yaml")
        assert "cluster" in params
        assert "environments" in params
