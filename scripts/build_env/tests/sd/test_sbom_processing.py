import json
import os
import shutil
import sys
from pathlib import Path
from subprocess import CalledProcessError

import pytest

from scripts.build_env.tests.base_test import BaseTest

os.environ.setdefault("ENVIRONMENT_NAME", "env-01")
os.environ.setdefault("CLUSTER_NAME", "cluster-01")

from build_effective_set_generator.scripts.handle_effective_set_config import handle_effective_set_config

# effective_set_entrypoint uses a bare import ("from handle_effective_set_config import ...")
# that only resolves when build_effective_set_generator/scripts/ is on sys.path.
_ESE_SCRIPTS = Path(__file__).resolve().parents[4] / "build_effective_set_generator" / "scripts"
if str(_ESE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_ESE_SCRIPTS))

import effective_set_entrypoint as _ese
from effective_set_entrypoint import _build_cli_cmd, _run_full_generation

FEATURE_TEST_DIR = "test_sbom_processing"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


# ---------------------------------------------------------------------------
# SBOM fixture builder helpers
# ---------------------------------------------------------------------------

def _prop(name: str, value: str) -> dict:
    return {"name": name, "value": value}


def _service_component(name: str) -> dict:
    """application/vnd.qubership.service component — contributes to serviceNames."""
    return {
        "type": "application",
        "mime-type": "application/vnd.qubership.service",
        "bom-ref": f"ref-{name}",
        "name": name,
        "version": "1.0.0",
        "properties": [
            _prop("deploy_param", ""),
            _prop("full_image_name", f"registry.example.local/ns/{name}:1.0.0"),
        ],
    }


def _image_component(name: str, deploy_param: str, full_image_name: str) -> dict:
    """application/octet-stream component — candidate for root deploy_param key."""
    return {
        "type": "application",
        "mime-type": "application/octet-stream",
        "bom-ref": f"ref-{name}",
        "name": name,
        "version": "",
        "properties": [
            _prop("deploy_param", deploy_param),
            _prop("full_image_name", full_image_name),
            _prop("docker_registry", "registry.example.local"),
            _prop("image_type", "image"),
        ],
    }


def _app_chart_component(name: str = "app-chart") -> dict:
    """application/vnd.qubership.app.chart component — required by app chart validation."""
    return {
        "type": "application",
        "mime-type": "application/vnd.qubership.app.chart",
        "bom-ref": f"ref-chart-{name}",
        "name": name,
        "version": "1.0.0",
    }


def _sbom(app_name: str, components: list) -> dict:
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "metadata": {
            "component": {
                "type": "application",
                "mime-type": "application/vnd.qubership.application",
                "name": app_name,
                "version": "1.0.0",
                "components": [
                    {
                        "type": "data",
                        "mime-type": "application/vnd.qubership.deployment-descriptor",
                        "name": f"descriptor.{app_name}",
                        "version": "1.0.0",
                    }
                ],
            }
        },
        "components": components,
    }


# ---------------------------------------------------------------------------
# Python reference implementation of BomReaderUtilsImplV2.addImageParameters
# ---------------------------------------------------------------------------

def _extract_deploy_params(sbom: dict) -> dict:
    """
    Python reference of the Java addImageParameters deploy_param filtering rule
    (BomReaderUtilsImplV2, lines 332-340):

    For each application/octet-stream component with a non-empty deploy_param:
    - deploy_param equals a service component name → OMIT from root deployment params.
    - Otherwise → include as  deploy_param: full_image_name  in root deployment params.
    """
    components = sbom.get("components", [])
    service_names = {
        c["name"]
        for c in components
        if c.get("mime-type") == "application/vnd.qubership.service"
    }
    result = {}
    for comp in components:
        if comp.get("mime-type") == "application/octet-stream":
            props = {p["name"]: p["value"] for p in comp.get("properties", [])}
            key = props.get("deploy_param", "")
            if key and key not in service_names:
                result[key] = props.get("full_image_name")
    return result


# ---------------------------------------------------------------------------
# UC-ES-DEP-14: deploy_param image key filtering
# ---------------------------------------------------------------------------

class TestDeployParamFiltering(BaseTest):
    """
    UC-ES-DEP-14 — The Calculator derives root deployment parameters from
    application/octet-stream SBOM components.

    Rule (BomReaderUtilsImplV2.addImageParameters):
    - deploy_param non-empty AND NOT a service name → included as root key.
    - deploy_param equals a service name → omitted from root deployment parameters.

    Tested via a Python reference implementation of the Java filtering rule
    applied to programmatically built CycloneDX SBOM fixtures.
    """

    def test_uc_dep_14_non_service_deploy_param_becomes_root_key(self):
        # UC-ES-DEP-14: IMAGE_QA_KEY is not a service name → appears in root params.
        sbom = _sbom("my-app", [
            _image_component(
                "qa-image",
                deploy_param="IMAGE_QA_KEY",
                full_image_name="registry.example.local/ns/app:1.2.3",
            ),
        ])
        params = _extract_deploy_params(sbom)
        assert "IMAGE_QA_KEY" in params, (
            f"IMAGE_QA_KEY must be present in root deploy params; got: {params}"
        )
        assert params["IMAGE_QA_KEY"] == "registry.example.local/ns/app:1.2.3"

    def test_uc_dep_14_deploy_param_matching_service_name_omitted(self):
        # UC-ES-DEP-14: deploy_param "billing-service" matches a service component
        # with the same name → must be omitted from root deployment parameters.
        sbom = _sbom("my-app", [
            _service_component("billing-service"),
            _image_component(
                "billing-image",
                deploy_param="billing-service",
                full_image_name="registry.example.local/ns/billing:9.0.0",
            ),
        ])
        params = _extract_deploy_params(sbom)
        assert "billing-service" not in params, (
            f"billing-service must be omitted (it is a service name); got: {params}"
        )

    def test_uc_dep_14_combined_scenario_key_present_service_omitted(self):
        # UC-ES-DEP-14: full UC scenario — both components present.
        # IMAGE_QA_KEY must survive; billing-service must be dropped.
        sbom = _sbom("my-app", [
            _service_component("billing-service"),
            _image_component(
                "qa-image",
                deploy_param="IMAGE_QA_KEY",
                full_image_name="registry.example.local/ns/app:1.2.3",
            ),
            _image_component(
                "billing-image",
                deploy_param="billing-service",
                full_image_name="registry.example.local/ns/billing:9.0.0",
            ),
        ])
        params = _extract_deploy_params(sbom)
        assert "IMAGE_QA_KEY" in params
        assert params["IMAGE_QA_KEY"] == "registry.example.local/ns/app:1.2.3"
        assert "billing-service" not in params

    def test_uc_dep_14_empty_deploy_param_not_included(self):
        # deploy_param="" → the component contributes no root key.
        sbom = _sbom("my-app", [
            _image_component(
                "no-key-image",
                deploy_param="",
                full_image_name="registry.example.local/ns/app:1.0.0",
            ),
        ])
        params = _extract_deploy_params(sbom)
        assert params == {}, f"empty deploy_param must not produce any root key; got: {params}"

    def test_uc_dep_14_multiple_non_service_params_all_included(self):
        # Multiple non-service deploy_param values all appear in root params.
        sbom = _sbom("my-app", [
            _image_component("img1", deploy_param="KEY_ONE",
                             full_image_name="registry.example.local/ns/one:1.0"),
            _image_component("img2", deploy_param="KEY_TWO",
                             full_image_name="registry.example.local/ns/two:2.0"),
        ])
        params = _extract_deploy_params(sbom)
        assert "KEY_ONE" in params
        assert "KEY_TWO" in params
        assert params["KEY_ONE"] == "registry.example.local/ns/one:1.0"
        assert params["KEY_TWO"] == "registry.example.local/ns/two:2.0"

    def test_uc_dep_14_non_octet_stream_component_ignored(self):
        # Only application/octet-stream components contribute to root deploy params.
        sbom = _sbom("my-app", [
            _service_component("my-service"),
        ])
        params = _extract_deploy_params(sbom)
        assert params == {}


# ---------------------------------------------------------------------------
# UC-ES-DEP-14 / A16 / A18: CLI command wiring
# ---------------------------------------------------------------------------

class TestBuildCliCmdSbomWiring(BaseTest):
    """
    Verifies that _build_cli_cmd correctly wires --sboms-path (UC-ES-DEP-14)
    and --app_chart_validation (UC-ES-DEP-A16 / A18) into the CLI command
    passed to the Java effective-set-generator.
    """

    def setup_method(self):
        self.feature_dir = self.output_dir / FEATURE_TEST_DIR / "cli_cmd"
        if self.feature_dir.exists():
            shutil.rmtree(self.feature_dir)
        self.feature_dir.mkdir(parents=True)
        for var in ("EFFECTIVE_SET_CONFIG", "DEPLOYMENT_SESSION_ID", "CUSTOM_PARAMS"):
            os.environ.pop(var, None)

    def teardown_method(self):
        for var in ("EFFECTIVE_SET_CONFIG", "DEPLOYMENT_SESSION_ID", "CUSTOM_PARAMS"):
            os.environ.pop(var, None)

    # ------------------------------------------------------------------
    # UC-ES-DEP-14: --sboms-path wiring
    # ------------------------------------------------------------------

    def test_sboms_path_included_when_sd_file_exists(self):
        # UC-ES-DEP-14: sd file present → --sboms-path forwarded to CLI so the
        # Java Calculator can read SBOM components (deploy_param, full_image_name).
        sd_path = self.feature_dir / "sd.yaml"
        _write(sd_path, "applications: []\n")
        es_dir = self.feature_dir / "effective-set"

        cmd = _build_cli_cmd(es_dir, "cluster-01/env-01", sd_path)

        assert "--sboms-path=$CI_PROJECT_DIR/sboms" in cmd, (
            f"--sboms-path must be in CLI cmd when sd file exists;\ncmd: {cmd}"
        )

    def test_sboms_path_absent_when_sd_file_missing(self):
        # UC-ES-DEP-14: no sd file → --sboms-path omitted (no SBOMs to process).
        sd_path = self.feature_dir / "nonexistent_sd.yaml"
        es_dir = self.feature_dir / "effective-set"

        cmd = _build_cli_cmd(es_dir, "cluster-01/env-01", sd_path)

        assert "--sboms-path" not in cmd

    def test_sd_path_and_registries_present_with_sboms_path(self):
        # UC-ES-DEP-14: --sd-path and --registries are included alongside --sboms-path.
        sd_path = self.feature_dir / "sd.yaml"
        _write(sd_path, "applications: []\n")
        es_dir = self.feature_dir / "effective-set"

        cmd = _build_cli_cmd(es_dir, "cluster-01/env-01", sd_path)

        assert f"--sd-path={sd_path}" in cmd
        assert "--registries=" in cmd

    # ------------------------------------------------------------------
    # UC-ES-DEP-A16: --app_chart_validation=true reaches the CLI
    # ------------------------------------------------------------------

    def test_app_chart_validation_true_in_cli_command(self):
        # UC-ES-DEP-A16: EFFECTIVE_SET_CONFIG with validation enabled →
        # --app_chart_validation=true is appended to the CLI command.
        os.environ["EFFECTIVE_SET_CONFIG"] = '{"app_chart_validation": true}'
        sd_path = self.feature_dir / "sd.yaml"
        _write(sd_path, "applications: []\n")

        cmd = _build_cli_cmd(self.feature_dir / "es", "cluster-01/env-01", sd_path)

        assert "--app_chart_validation=true" in cmd, (
            f"--app_chart_validation=true expected in CLI cmd;\ncmd: {cmd}"
        )

    def test_no_effective_set_config_omits_app_chart_flag(self):
        # UC-ES-DEP-A16: without EFFECTIVE_SET_CONFIG the extra_args block is skipped.
        sd_path = self.feature_dir / "sd.yaml"
        _write(sd_path, "applications: []\n")

        cmd = _build_cli_cmd(self.feature_dir / "es", "cluster-01/env-01", sd_path)

        assert "--app_chart_validation" not in cmd

    # ------------------------------------------------------------------
    # UC-ES-DEP-A18: --app_chart_validation=false reaches the CLI
    # ------------------------------------------------------------------

    def test_app_chart_validation_false_in_cli_command(self):
        # UC-ES-DEP-A18: EFFECTIVE_SET_CONFIG with validation disabled →
        # --app_chart_validation=false is appended so the Java Calculator skips
        # app chart component presence checks.
        os.environ["EFFECTIVE_SET_CONFIG"] = '{"app_chart_validation": false}'
        sd_path = self.feature_dir / "sd.yaml"
        _write(sd_path, "applications: []\n")

        cmd = _build_cli_cmd(self.feature_dir / "es", "cluster-01/env-01", sd_path)

        assert "--app_chart_validation=false" in cmd, (
            f"--app_chart_validation=false expected in CLI cmd;\ncmd: {cmd}"
        )
        assert "--app_chart_validation=true" not in cmd


# ---------------------------------------------------------------------------
# UC-ES-DEP-A16 / A18: full generation lifecycle
# ---------------------------------------------------------------------------

class TestFullGenerationLifecycle(BaseTest):
    """
    UC-ES-DEP-A16 — generation fails (CalledProcessError propagated) when the
    Java CLI exits non-zero (e.g., app chart validation error).

    UC-ES-DEP-A18 — generation completes successfully when the Java CLI exits
    zero (app chart validation disabled via --app_chart_validation=false).
    """

    def setup_method(self):
        self.feature_dir = self.output_dir / FEATURE_TEST_DIR / "lifecycle"
        if self.feature_dir.exists():
            shutil.rmtree(self.feature_dir)
        self.feature_dir.mkdir(parents=True)

    def test_uc_dep_a16_cli_failure_propagates_as_called_process_error(self, monkeypatch):
        # UC-ES-DEP-A16: Java CLI exits non-zero (app chart validation error) →
        # _run_full_generation must propagate CalledProcessError.
        def _fail(cmd, shell=True, check=True):
            raise CalledProcessError(1, cmd)

        monkeypatch.setattr(_ese, "_build_cli_cmd", lambda *a, **kw: "fake_cmd")
        monkeypatch.setattr(_ese.subprocess, "run", _fail)

        es_dir = self.feature_dir / "effective-set"
        es_dir.mkdir(parents=True)
        sd_path = self.feature_dir / "sd.yaml"
        _write(sd_path, "applications: []\n")

        with pytest.raises(CalledProcessError):
            _run_full_generation(es_dir, "cluster-01/env-01", sd_path)

    def test_uc_dep_a16_es_dir_wiped_before_cli_is_called(self, monkeypatch):
        # UC-ES-DEP-A16: _run_full_generation deletes es_dir before invoking the CLI.
        # After a CLI failure the dir remains absent (CLI never recreated it).
        def _fail(cmd, shell=True, check=True):
            raise CalledProcessError(1, cmd)

        monkeypatch.setattr(_ese, "_build_cli_cmd", lambda *a, **kw: "fake_cmd")
        monkeypatch.setattr(_ese.subprocess, "run", _fail)

        es_dir = self.feature_dir / "effective-set-a16"
        es_dir.mkdir(parents=True)
        (es_dir / "old-output.txt").write_text("stale")
        sd_path = self.feature_dir / "sd-a16.yaml"
        _write(sd_path, "applications: []\n")

        with pytest.raises(CalledProcessError):
            _run_full_generation(es_dir, "cluster-01/env-01", sd_path)

        assert not es_dir.exists(), "effective-set dir must have been wiped before CLI call"

    def test_uc_dep_a18_cli_success_completes_without_exception(self, monkeypatch):
        # UC-ES-DEP-A18: Java CLI exits 0 (validation skipped) → _run_full_generation
        # returns normally without raising.
        monkeypatch.setattr(_ese, "_build_cli_cmd", lambda *a, **kw: "fake_cmd")
        monkeypatch.setattr(_ese.subprocess, "run", lambda cmd, shell=True, check=True: None)

        es_dir = self.feature_dir / "effective-set-a18"
        es_dir.mkdir(parents=True)
        sd_path = self.feature_dir / "sd-a18.yaml"
        _write(sd_path, "applications: []\n")

        # Must not raise.
        _run_full_generation(es_dir, "cluster-01/env-01", sd_path)

    def test_uc_dep_a18_stale_es_dir_cleared_on_success(self, monkeypatch):
        # UC-ES-DEP-A18: _run_full_generation deletes the existing effective-set dir
        # before invoking the CLI, so stale artifacts from a previous run are removed.
        monkeypatch.setattr(_ese, "_build_cli_cmd", lambda *a, **kw: "fake_cmd")
        monkeypatch.setattr(_ese.subprocess, "run", lambda cmd, shell=True, check=True: None)

        es_dir = self.feature_dir / "effective-set-a18-stale"
        es_dir.mkdir(parents=True)
        stale_file = es_dir / "stale-deployment.yaml"
        stale_file.write_text("old content")
        sd_path = self.feature_dir / "sd-a18-stale.yaml"
        _write(sd_path, "applications: []\n")

        _run_full_generation(es_dir, "cluster-01/env-01", sd_path)

        assert not stale_file.exists(), "stale file must have been removed before CLI invocation"


# ---------------------------------------------------------------------------
# UC-ES-DEP-A16 / UC-ES-DEP-A18: handle_effective_set_config app_chart flag
# ---------------------------------------------------------------------------

class TestHandleEffectiveSetConfigAppChart(BaseTest):
    """
    UC-ES-DEP-A16 — app chart validation enabled (default).
    UC-ES-DEP-A18 — app chart validation disabled via EFFECTIVE_SET_CONFIG.

    handle_effective_set_config() parses EFFECTIVE_SET_CONFIG JSON and emits
    CLI arguments consumed by the Java effective-set-generator.
    """

    # ------------------------------------------------------------------
    # UC-ES-DEP-A16: validation enabled — default and explicit true
    # ------------------------------------------------------------------

    def test_app_chart_validation_explicit_true_emits_true_flag(self):
        # UC-ES-DEP-A16: explicit true → --app_chart_validation=true; false must not appear.
        result = handle_effective_set_config('{"app_chart_validation": true}')
        assert "--app_chart_validation=true" in result["extra_args"]
        assert "--app_chart_validation=false" not in result["extra_args"]

    def test_app_chart_validation_true_version_flag_also_present(self):
        # UC-ES-DEP-A16: app chart flag and version flag both emitted.
        result = handle_effective_set_config(
            '{"version": "v2.0", "app_chart_validation": true}'
        )
        flags = result["extra_args"]
        assert any("app_chart_validation=true" in f for f in flags)
        assert any("effective-set-version=v2.0" in f for f in flags)

    def test_empty_config_defaults_app_chart_validation_to_true(self):
        # UC-ES-DEP-A16: empty JSON object → default True.
        result = handle_effective_set_config("{}")
        assert "--app_chart_validation=true" in result["extra_args"]

    # ------------------------------------------------------------------
    # UC-ES-DEP-A18: validation disabled via false flag
    # ------------------------------------------------------------------

    def test_app_chart_validation_false_emits_false_flag(self):
        # UC-ES-DEP-A18: "app_chart_validation": false → --app_chart_validation=false; true must not appear.
        result = handle_effective_set_config('{"app_chart_validation": false}')
        assert "--app_chart_validation=false" in result["extra_args"], (
            f"expected --app_chart_validation=false; got: {result['extra_args']}"
        )
        assert "--app_chart_validation=true" not in result["extra_args"]

    def test_app_chart_validation_false_with_version(self):
        # UC-ES-DEP-A18: version and app_chart_validation=false together.
        result = handle_effective_set_config(
            '{"version": "v2.0", "app_chart_validation": false}'
        )
        flags = result["extra_args"]
        assert "--app_chart_validation=false" in flags
        assert any("effective-set-version=v2.0" in f for f in flags)

    # ------------------------------------------------------------------
    # UC-ES-DEP-14: version flag
    # ------------------------------------------------------------------

    def test_version_default_applied_when_absent(self):
        # UC-ES-DEP-14: no version key → default v2.0.
        result = handle_effective_set_config('{"app_chart_validation": true}')
        assert any("effective-set-version=v2.0" in f for f in result["extra_args"])

    def test_custom_version_forwarded_to_cli(self):
        # UC-ES-DEP-14: custom version string is preserved verbatim.
        result = handle_effective_set_config('{"version": "v3.1"}')
        assert any("effective-set-version=v3.1" in f for f in result["extra_args"])

    # ------------------------------------------------------------------
    # Negative
    # ------------------------------------------------------------------

    def test_invalid_json_raises_json_decode_error(self):
        with pytest.raises(json.JSONDecodeError):
            handle_effective_set_config("not-json-{")

