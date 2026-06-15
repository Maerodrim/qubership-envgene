import logging
import os
import shutil
from pathlib import Path

import pytest

from envgenehelper import openYaml
from envgenehelper.env_helper import Environment
from envgenehelper.test_helpers import TestHelpers
from scripts.build_env.tests.base_test import BaseTest

os.environ.setdefault("ENVIRONMENT_NAME", "env-01")
os.environ.setdefault("CLUSTER_NAME", "cluster-01")
os.environ.setdefault("CI_PROJECT_DIR", "/tmp")
os.environ.setdefault("FULL_ENV_NAME", "cluster-01/env-01")

from process_sd import handle_sd

FEATURE_TEST_DIR = "test_handle_deploy_postfix"
CLUSTER = "cluster-01"
ENV_NAME = "env-01"
FULL_ENV_NAME = f"{CLUSTER}/{ENV_NAME}"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _copy_namespaces(src_namespaces_dir: Path, env: Environment) -> None:
    """Copy namespace folder fixtures into the environment's Namespaces directory."""
    target_ns_dir = Path(env.env_path) / "Namespaces"
    if target_ns_dir.exists():
        shutil.rmtree(target_ns_dir)
    shutil.copytree(src_namespaces_dir, target_ns_dir)


def _load_tc(test_data_dir: Path, tc_name: str) -> tuple:
    file_path = test_data_dir / tc_name / f"{tc_name}.yaml"
    data = openYaml(file_path)
    return (
        data.get("SD_DATA", "{}"),
        data.get("SD_SOURCE_TYPE", ""),
        data.get("SD_VERSION", ""),
        data.get("SD_DELTA", ""),
        data.get("SD_REPO_MERGE_MODE", "basic-merge"),
    )


class TestHandleDeployPostfixPositive(BaseTest):
    """
    UC-CC-DP-1..3 positive paths exercised through handle_sd():
    namespace.yml fixtures are placed on disk before each test, handle_sd() processes
    them, and the resulting sd.yaml is compared against the ER directory.
    """

    def setup_method(self):
        self.feature_dir = self.output_dir / FEATURE_TEST_DIR
        self.test_data_dir = self.test_data_dir / FEATURE_TEST_DIR
        self.ns_prerequisites = self.test_data_dir / "prerequisites" / "namespaces"

        TestHelpers.clean_test_dir(self.feature_dir)
        os.environ["CLUSTER_NAME"] = CLUSTER
        os.environ["ENVIRONMENT_NAME"] = ENV_NAME
        os.environ["FULL_ENV_NAME"] = FULL_ENV_NAME
        self.set_ci_project_dir(self.feature_dir)

    def _prepare(self, ns_preset: str) -> Environment:
        """Create a fresh environment directory with the requested namespace fixtures."""
        env = Environment(str(self.feature_dir), CLUSTER, ENV_NAME)
        _copy_namespaces(self.ns_prerequisites / ns_preset, env)
        return env

    def _assert_sd(self, env: Environment, tc_name: str) -> None:
        sd_dir = Path(env.env_path) / "Inventory" / "solution-descriptor"
        er_dir = self.test_data_dir / "ER" / tc_name
        TestHelpers.assert_dirs_content(er_dir, sd_dir, check_for_missing_files=True, check_for_extra_files=True)

    # ------------------------------------------------------------------
    # TC-DP-001: UC-CC-DP-1 — exact match: logical name → folder name
    # ------------------------------------------------------------------

    def test_tc_dp_001_exact_match_postfix_replaced(self):
        # UC-CC-DP-1: deployPostfix "core-namespace" == namespace logical name → replaced
        # with folder name "core". userData removed because only useDeployPostfixAsNamespace present.
        env = self._prepare("single-core")
        sd_data, sd_source_type, sd_version, sd_delta, sd_merge_mode = _load_tc(self.test_data_dir, "TC-DP-001")

        handle_sd(env, sd_source_type, sd_version, sd_data, sd_delta, sd_merge_mode)

        self._assert_sd(env, "TC-DP-001")

    # ------------------------------------------------------------------
    # TC-DP-002: UC-CC-DP-2 — BG Domain: origin and peer namespaces both replaced
    # ------------------------------------------------------------------

    def test_tc_dp_002_bg_domain_origin_and_peer_replaced(self):
        # UC-CC-DP-2: SD has two apps — one for origin, one for peer. Both deployPostfixes
        # already match their logical names (folder == logical name for BG domain namespaces).
        env = self._prepare("bg-domain")
        sd_data, sd_source_type, sd_version, sd_delta, sd_merge_mode = _load_tc(self.test_data_dir, "TC-DP-002")

        handle_sd(env, sd_source_type, sd_version, sd_data, sd_delta, sd_merge_mode)

        self._assert_sd(env, "TC-DP-002")

    # ------------------------------------------------------------------
    # TC-DP-003: UC-CC-DP-1 — multiple namespaces, all replaced
    # ------------------------------------------------------------------

    def test_tc_dp_003_multiple_namespaces_all_replaced(self):
        # UC-CC-DP-1: two apps with distinct deployPostfixes — each maps to its folder name.
        env = self._prepare("multi-ns")
        sd_data, sd_source_type, sd_version, sd_delta, sd_merge_mode = _load_tc(self.test_data_dir, "TC-DP-003")

        handle_sd(env, sd_source_type, sd_version, sd_data, sd_delta, sd_merge_mode)

        self._assert_sd(env, "TC-DP-003")

    # ------------------------------------------------------------------
    # TC-DP-004: flag absent — SD passes through unchanged
    # ------------------------------------------------------------------

    def test_tc_dp_004_no_flag_sd_unchanged(self):
        # Backward compat: without useDeployPostfixAsNamespace the deployPostfix values
        # must reach the output sd.yaml exactly as provided.
        env = self._prepare("single-core")
        sd_data, sd_source_type, sd_version, sd_delta, sd_merge_mode = _load_tc(self.test_data_dir, "TC-DP-004")

        handle_sd(env, sd_source_type, sd_version, sd_data, sd_delta, sd_merge_mode)

        self._assert_sd(env, "TC-DP-004")


class TestHandleDeployPostfixNegative(BaseTest):
    """
    UC-CC-DP-3 / UC-CC-DP-4 negative paths: handle_sd() must call exit(1) when
    deployPostfix cannot be matched to any namespace in the environment.
    """

    def setup_method(self):
        self.feature_dir = self.output_dir / FEATURE_TEST_DIR / "negative"
        self.test_data_dir_base = self.test_data_dir / FEATURE_TEST_DIR
        self.ns_prerequisites = self.test_data_dir_base / "prerequisites" / "namespaces"

        TestHelpers.clean_test_dir(self.feature_dir)
        os.environ["CLUSTER_NAME"] = CLUSTER
        os.environ["ENVIRONMENT_NAME"] = ENV_NAME
        os.environ["FULL_ENV_NAME"] = FULL_ENV_NAME
        self.set_ci_project_dir(self.feature_dir)

    def _prepare(self, ns_preset: str) -> Environment:
        env = Environment(str(self.feature_dir), CLUSTER, ENV_NAME)
        _copy_namespaces(self.ns_prerequisites / ns_preset, env)
        return env

    def _sd_data_with_postfix(self, postfix: str) -> str:
        import json
        return json.dumps([{
            "version": 1,
            "type": "solutionDeploy",
            "applications": [{"version": "app:1.0", "deployPostfix": postfix}],
            "userData": {"useDeployPostfixAsNamespace": True},
        }])

    # ------------------------------------------------------------------
    # UC-CC-DP-3: no exact match → exit(1)
    # ------------------------------------------------------------------

    def test_unknown_postfix_exits_with_code_1(self, caplog):
        # UC-CC-DP-3: deployPostfix "unknown-namespace" does not match any namespace
        # logical name → handle_sd must call exit(1).
        env = self._prepare("single-core")
        sd_data = self._sd_data_with_postfix("unknown-namespace")

        with caplog.at_level(logging.ERROR, logger="envgene"):
            with pytest.raises(SystemExit) as exc_info:
                handle_sd(env, "json", "", sd_data, "", "basic-merge")

        assert exc_info.value.code == 1
        assert "No replacement found" in caplog.text
        assert "unknown-namespace" in caplog.text

    def test_case_mismatch_postfix_exits_with_code_1(self, caplog):
        # UC-CC-DP-3: matching is case-sensitive — "Core-Namespace" ≠ "core-namespace".
        env = self._prepare("single-core")
        sd_data = self._sd_data_with_postfix("Core-Namespace")

        with caplog.at_level(logging.ERROR, logger="envgene"):
            with pytest.raises(SystemExit) as exc_info:
                handle_sd(env, "json", "", sd_data, "", "basic-merge")

        assert exc_info.value.code == 1

    # ------------------------------------------------------------------
    # UC-CC-DP-4: BG domain namespaces present but wrong postfix used → exit(1)
    # ------------------------------------------------------------------

    def test_bg_base_name_without_suffix_exits_with_code_1(self, caplog):
        # UC-CC-DP-4: only "bss-origin" and "bss-peer" exist; SD uses bare "bss" → no match.
        import json
        env = self._prepare("bg-domain")
        sd_data = json.dumps([{
            "version": 1,
            "type": "solutionDeploy",
            "applications": [{"version": "bss-app:1.0", "deployPostfix": "bss"}],
            "userData": {"useDeployPostfixAsNamespace": True},
        }])

        with caplog.at_level(logging.ERROR, logger="envgene"):
            with pytest.raises(SystemExit) as exc_info:
                handle_sd(env, "json", "", sd_data, "", "basic-merge")

        assert exc_info.value.code == 1

    def test_missing_peer_side_exits_with_code_1(self, caplog):
        # UC-CC-DP-4: "bss-peer" namespace does not exist; SD references it → exit(1).
        import json
        env = self._prepare("single-core")  # only "core" namespace exists
        sd_data = json.dumps([{
            "version": 1,
            "type": "solutionDeploy",
            "applications": [{"version": "peer-app:1.0", "deployPostfix": "bss-peer"}],
            "userData": {"useDeployPostfixAsNamespace": True},
        }])

        with caplog.at_level(logging.ERROR, logger="envgene"):
            with pytest.raises(SystemExit):
                handle_sd(env, "json", "", sd_data, "", "basic-merge")
