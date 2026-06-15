import logging
import os
import shutil
from pathlib import Path

import pytest

from envgenehelper.env_helper import Environment
from scripts.build_env.tests.base_test import BaseTest

# Must be set before process_sd import to satisfy module-level getenv_with_error calls
os.environ.setdefault("ENVIRONMENT_NAME", "env-01")
os.environ.setdefault("CLUSTER_NAME", "cluster-01")

from process_sd import build_namespace_dict, handle_deploy_postfix_namespace_transformation

FEATURE_TEST_DIR = "test_deploy_postfix"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _make_env(base: Path, cluster: str = "cluster-01", env_name: str = "env-01") -> Environment:
    env_path = base / "environments" / cluster / env_name
    env_path.mkdir(parents=True, exist_ok=True)
    return Environment(str(base), cluster, env_name)


def _write_namespace(env: Environment, folder: str, name: str) -> None:
    ns_file = Path(env.env_path) / "Namespaces" / folder / "namespace.yml"
    _write(ns_file, f"name: {name}\n")


# ---------------------------------------------------------------------------
# build_namespace_dict
# ---------------------------------------------------------------------------

class TestBuildNamespaceDict(BaseTest):
    """Unit tests for build_namespace_dict: mapping namespace logical names → folder names."""

    def setup_method(self):
        self.feature_dir = self.output_dir / FEATURE_TEST_DIR / "build_ns_dict"
        if self.feature_dir.exists():
            shutil.rmtree(self.feature_dir)
        self.feature_dir.mkdir(parents=True)

    def _env(self, test_name: str) -> Environment:
        return _make_env(self.feature_dir / test_name)

    # ------------------------------------------------------------------
    # Positive
    # ------------------------------------------------------------------

    def test_single_namespace_builds_dict(self, caplog):
        env = self._env("single")
        _write_namespace(env, "core", "core-namespace")

        with caplog.at_level(logging.INFO, logger="envgene"):
            result = build_namespace_dict(env)

        assert result == {"core-namespace": "core"}
        assert "Namespace dict built" in caplog.text

    def test_multiple_namespaces_all_mapped(self):
        env = self._env("multi")
        _write_namespace(env, "core", "core-namespace")
        _write_namespace(env, "bss", "bss-namespace")
        _write_namespace(env, "monitoring", "monitoring-namespace")

        result = build_namespace_dict(env)

        assert result == {
            "core-namespace": "core",
            "bss-namespace": "bss",
            "monitoring-namespace": "monitoring",
        }

    def test_bg_origin_peer_folders_mapped(self):
        # BG Domain environment: origin and peer folders with -origin/-peer suffixes.
        env = self._env("bg-domain")
        _write_namespace(env, "bss-origin", "bss-origin")
        _write_namespace(env, "bss-peer", "bss-peer")

        result = build_namespace_dict(env)

        assert result == {
            "bss-origin": "bss-origin",
            "bss-peer": "bss-peer",
        }

    def test_folder_name_differs_from_logical_name(self):
        # Folder name and namespace logical name can be different strings.
        env = self._env("name-mismatch")
        _write_namespace(env, "folder-abc", "logical-name-xyz")

        result = build_namespace_dict(env)

        assert result == {"logical-name-xyz": "folder-abc"}

    # ------------------------------------------------------------------
    # Missing / empty Namespaces directory
    # ------------------------------------------------------------------

    def test_missing_namespaces_dir_returns_empty_dict(self, caplog):
        # Namespaces directory does not exist at all — must return {} without raising.
        env = self._env("no-ns-dir")

        with caplog.at_level(logging.WARNING, logger="envgene"):
            result = build_namespace_dict(env)

        assert result == {}
        assert "does not exist" in caplog.text

    def test_empty_namespaces_dir_returns_empty_dict(self):
        # Namespaces directory exists but contains no sub-folders.
        env = self._env("empty-ns-dir")
        (Path(env.env_path) / "Namespaces").mkdir(parents=True, exist_ok=True)

        result = build_namespace_dict(env)

        assert result == {}

    # ------------------------------------------------------------------
    # Folders without namespace.yml are silently skipped
    # ------------------------------------------------------------------

    def test_folder_without_namespace_yml_is_skipped(self):
        # A folder exists under Namespaces/ but has no namespace.yml — must be ignored.
        env = self._env("no-ns-yml")
        (Path(env.env_path) / "Namespaces" / "orphan-folder").mkdir(parents=True)
        _write_namespace(env, "valid", "valid-name")

        result = build_namespace_dict(env)

        assert result == {"valid-name": "valid"}
        assert "orphan-folder" not in result.values()

    def test_namespace_yml_missing_name_key_is_skipped(self, caplog):
        # namespace.yml exists but has no 'name' key — must warn and skip.
        env = self._env("ns-yml-no-name")
        ns_file = Path(env.env_path) / "Namespaces" / "broken" / "namespace.yml"
        _write(ns_file, "foo: bar\n")

        with caplog.at_level(logging.WARNING, logger="envgene"):
            result = build_namespace_dict(env)

        assert result == {}
        assert "missing or invalid" in caplog.text

    # ------------------------------------------------------------------
    # Backward compatibility — non-folder entries in Namespaces/ are ignored
    # ------------------------------------------------------------------

    def test_file_at_namespace_level_is_ignored(self):
        # A file directly under Namespaces/ (not a sub-folder) must not be included.
        env = self._env("file-in-ns-dir")
        ns_dir = Path(env.env_path) / "Namespaces"
        ns_dir.mkdir(parents=True, exist_ok=True)
        (ns_dir / "stray-file.yml").write_text("name: stray\n")
        _write_namespace(env, "core", "core-name")

        result = build_namespace_dict(env)

        assert result == {"core-name": "core"}


# ---------------------------------------------------------------------------
# handle_deploy_postfix_namespace_transformation
# ---------------------------------------------------------------------------

class TestHandleDeployPostfixTransformation(BaseTest):
    """UC-CC-DP-1..4: deployPostfix matching and replacement via useDeployPostfixAsNamespace."""

    # ------------------------------------------------------------------
    # UC-CC-DP-1: Exact match — flag absent (pass-through)
    # ------------------------------------------------------------------

    def test_no_flag_sd_is_unchanged(self):
        # useDeployPostfixAsNamespace is absent — SD must be returned unchanged.
        sd = {
            "applications": [
                {"deployPostfix": "core", "version": "app:1.0"},
            ]
        }
        namespace_dict = {"core-namespace": "core"}

        result = handle_deploy_postfix_namespace_transformation(sd, namespace_dict)

        assert result["applications"][0]["deployPostfix"] == "core"

    def test_flag_false_sd_is_unchanged(self):
        # useDeployPostfixAsNamespace is explicitly False — no replacement.
        sd = {
            "userData": {"useDeployPostfixAsNamespace": False},
            "applications": [{"deployPostfix": "core"}],
        }
        namespace_dict = {"core-namespace": "core"}

        result = handle_deploy_postfix_namespace_transformation(sd, namespace_dict)

        assert result["applications"][0]["deployPostfix"] == "core"
        assert "useDeployPostfixAsNamespace" in result.get("userData", {})

    # ------------------------------------------------------------------
    # UC-CC-DP-1: Exact match — flag True, single app
    # ------------------------------------------------------------------

    def test_flag_true_replaces_postfix_with_folder_name(self, caplog):
        # UC-CC-DP-1: deployPostfix == namespace logical name → replaced with folder name.
        sd = {
            "userData": {"useDeployPostfixAsNamespace": True},
            "applications": [{"deployPostfix": "core-namespace", "version": "app:1.0"}],
        }
        namespace_dict = {"core-namespace": "core"}

        with caplog.at_level(logging.INFO, logger="envgene"):
            result = handle_deploy_postfix_namespace_transformation(sd, namespace_dict)

        assert result["applications"][0]["deployPostfix"] == "core"
        assert "core-namespace" in caplog.text  # logged the replacement
        # userData with only useDeployPostfixAsNamespace must be removed entirely
        assert "userData" not in result

    def test_flag_true_multiple_apps_all_replaced(self):
        # UC-CC-DP-1: multiple apps in SD — each deployPostfix is replaced independently.
        sd = {
            "userData": {"useDeployPostfixAsNamespace": True},
            "applications": [
                {"deployPostfix": "core-namespace"},
                {"deployPostfix": "bss-namespace"},
            ],
        }
        namespace_dict = {"core-namespace": "core", "bss-namespace": "bss"}

        result = handle_deploy_postfix_namespace_transformation(sd, namespace_dict)

        postfixes = [app["deployPostfix"] for app in result["applications"]]
        assert postfixes == ["core", "bss"]

    # ------------------------------------------------------------------
    # UC-CC-DP-2: BG Domain match — origin/peer folder names
    # ------------------------------------------------------------------

    def test_bg_both_origin_and_peer_replaced_in_single_sd(self):
        # UC-CC-DP-2: one SD with both origin and peer apps — both replaced correctly.
        sd = {
            "userData": {"useDeployPostfixAsNamespace": True},
            "applications": [
                {"deployPostfix": "bss-origin"},
                {"deployPostfix": "bss-peer"},
            ],
        }
        namespace_dict = {"bss-origin": "bss-origin", "bss-peer": "bss-peer"}

        result = handle_deploy_postfix_namespace_transformation(sd, namespace_dict)

        postfixes = {app["deployPostfix"] for app in result["applications"]}
        assert postfixes == {"bss-origin", "bss-peer"}

    # ------------------------------------------------------------------
    # UC-CC-DP-3 / UC-CC-DP-4: No match found — must call exit(1)
    # ------------------------------------------------------------------

    def test_no_match_for_postfix_calls_exit(self, caplog):
        # UC-CC-DP-3: no exact match exists → must log error and exit(1).
        sd = {
            "userData": {"useDeployPostfixAsNamespace": True},
            "applications": [{"deployPostfix": "unknown-namespace"}],
        }
        namespace_dict = {"core-namespace": "core"}

        with caplog.at_level(logging.ERROR, logger="envgene"):
            with pytest.raises(SystemExit) as exc_info:
                handle_deploy_postfix_namespace_transformation(sd, namespace_dict)

        assert exc_info.value.code == 1
        assert "No replacement found" in caplog.text
        assert "unknown-namespace" in caplog.text

    def test_empty_namespace_dict_calls_exit(self, caplog):
        # No namespaces at all — any deployPostfix must fail.
        sd = {
            "userData": {"useDeployPostfixAsNamespace": True},
            "applications": [{"deployPostfix": "core-namespace"}],
        }

        with caplog.at_level(logging.ERROR, logger="envgene"):
            with pytest.raises(SystemExit):
                handle_deploy_postfix_namespace_transformation(sd, {})

    # ------------------------------------------------------------------
    # userData cleanup behavior
    # ------------------------------------------------------------------

    def test_extra_user_data_keys_preserved(self):
        # userData has other keys besides useDeployPostfixAsNamespace → remove only the flag.
        sd = {
            "userData": {
                "useDeployPostfixAsNamespace": True,
                "otherKey": "some-value",
            },
            "applications": [{"deployPostfix": "core-namespace"}],
        }
        namespace_dict = {"core-namespace": "core"}

        result = handle_deploy_postfix_namespace_transformation(sd, namespace_dict)

        assert "userData" in result
        assert "useDeployPostfixAsNamespace" not in result["userData"]
        assert result["userData"]["otherKey"] == "some-value"

    # ------------------------------------------------------------------
    # Edge cases — structural anomalies
    # ------------------------------------------------------------------

    def test_app_without_deploy_postfix_key_is_unchanged(self):
        # Application dict without deployPostfix key must be left untouched (no KeyError).
        sd = {
            "userData": {"useDeployPostfixAsNamespace": True},
            "applications": [
                {"version": "app:1.0"},  # no deployPostfix
                {"deployPostfix": "core-namespace"},
            ],
        }
        namespace_dict = {"core-namespace": "core"}

        result = handle_deploy_postfix_namespace_transformation(sd, namespace_dict)

        assert result["applications"][0].get("deployPostfix") is None
        assert result["applications"][1]["deployPostfix"] == "core"

    def test_deploy_postfix_non_string_is_unchanged(self):
        # deployPostfix with non-string value (e.g. None) must not be transformed.
        sd = {
            "userData": {"useDeployPostfixAsNamespace": True},
            "applications": [
                {"deployPostfix": None},
                {"deployPostfix": "core-namespace"},
            ],
        }
        namespace_dict = {"core-namespace": "core"}

        result = handle_deploy_postfix_namespace_transformation(sd, namespace_dict)

        assert result["applications"][0]["deployPostfix"] is None
        assert result["applications"][1]["deployPostfix"] == "core"

    def test_empty_applications_list_returns_unchanged(self):
        # No apps in SD — transformation must succeed silently.
        sd = {
            "userData": {"useDeployPostfixAsNamespace": True},
            "applications": [],
        }

        result = handle_deploy_postfix_namespace_transformation(sd, {})

        assert result["applications"] == []
        assert "userData" not in result

    def test_no_applications_key_returns_unchanged(self):
        # SD without applications key — must not raise.
        sd = {"userData": {"useDeployPostfixAsNamespace": True}}

        result = handle_deploy_postfix_namespace_transformation(sd, {})

        assert "applications" not in result

    # ------------------------------------------------------------------
    # Backward compatibility — flag absent in older SDs
    # ------------------------------------------------------------------

    def test_sd_without_user_data_is_unchanged(self):
        # Older SDs have no userData at all — must pass through without modification.
        sd = {
            "applications": [
                {"deployPostfix": "bss", "version": "bss-app:1.2"},
            ]
        }

        result = handle_deploy_postfix_namespace_transformation(sd, {"bss": "bss"})

        assert result["applications"][0]["deployPostfix"] == "bss"
        assert "userData" not in result

    def test_sd_with_non_dict_user_data_is_unchanged(self):
        # userData is not a dict (e.g. null / string from malformed YAML) — must not crash.
        sd = {
            "userData": None,
            "applications": [{"deployPostfix": "core"}],
        }

        result = handle_deploy_postfix_namespace_transformation(sd, {"core": "core"})

        assert result["applications"][0]["deployPostfix"] == "core"


# ---------------------------------------------------------------------------
# Negative scenarios — integration of build_namespace_dict + transformation
# ---------------------------------------------------------------------------

class TestDeployPostfixNegativeScenarios(BaseTest):
    """Negative cases: mismatches, partial failures, and structural errors."""

    def setup_method(self):
        self.feature_dir = self.output_dir / FEATURE_TEST_DIR / "negative"
        if self.feature_dir.exists():
            shutil.rmtree(self.feature_dir)
        self.feature_dir.mkdir(parents=True)

    def _env(self, test_name: str) -> Environment:
        return _make_env(self.feature_dir / test_name)

    # ------------------------------------------------------------------
    # UC-CC-DP-3: exact match not found
    # ------------------------------------------------------------------

    def test_postfix_case_mismatch_not_matched(self, caplog):
        # UC-CC-DP-3: "Core-Namespace" (uppercase) does not match "core-namespace" (lowercase).
        # Matching is case-sensitive — must exit(1).
        sd = {
            "userData": {"useDeployPostfixAsNamespace": True},
            "applications": [{"deployPostfix": "Core-Namespace"}],
        }
        namespace_dict = {"core-namespace": "core"}

        with caplog.at_level(logging.ERROR, logger="envgene"):
            with pytest.raises(SystemExit) as exc_info:
                handle_deploy_postfix_namespace_transformation(sd, namespace_dict)

        assert exc_info.value.code == 1
        assert "Core-Namespace" in caplog.text

    def test_postfix_with_trailing_space_not_matched(self, caplog):
        # Whitespace-padded deployPostfix must not accidentally match real namespace name.
        sd = {
            "userData": {"useDeployPostfixAsNamespace": True},
            "applications": [{"deployPostfix": "core-namespace "}],  # trailing space
        }
        namespace_dict = {"core-namespace": "core"}

        with caplog.at_level(logging.ERROR, logger="envgene"):
            with pytest.raises(SystemExit):
                handle_deploy_postfix_namespace_transformation(sd, namespace_dict)

    def test_first_app_matches_second_does_not_exits(self, caplog):
        # UC-CC-DP-3: first app resolves fine, second fails → exit(1) on the second.
        sd = {
            "userData": {"useDeployPostfixAsNamespace": True},
            "applications": [
                {"deployPostfix": "core-namespace"},   # matches
                {"deployPostfix": "unknown-namespace"},  # does not match
            ],
        }
        namespace_dict = {"core-namespace": "core"}

        with caplog.at_level(logging.ERROR, logger="envgene"):
            with pytest.raises(SystemExit) as exc_info:
                handle_deploy_postfix_namespace_transformation(sd, namespace_dict)

        assert exc_info.value.code == 1
        assert "unknown-namespace" in caplog.text

    # ------------------------------------------------------------------
    # UC-CC-DP-4: BG domain namespaces present but deployPostfix doesn't match any
    # ------------------------------------------------------------------

    def test_bg_postfix_without_suffix_not_matched(self, caplog):
        # UC-CC-DP-4: SD has deployPostfix "bss" but only "bss-origin"/"bss-peer" folders exist.
        # No exact match → exit(1).
        sd = {
            "userData": {"useDeployPostfixAsNamespace": True},
            "applications": [{"deployPostfix": "bss"}],
        }
        namespace_dict = {"bss-origin": "bss-origin", "bss-peer": "bss-peer"}

        with caplog.at_level(logging.ERROR, logger="envgene"):
            with pytest.raises(SystemExit) as exc_info:
                handle_deploy_postfix_namespace_transformation(sd, namespace_dict)

        assert exc_info.value.code == 1
        assert "bss" in caplog.text

    def test_partial_bg_match_wrong_side_not_matched(self, caplog):
        # "bss-origin" exists as folder but SD uses "bss-peer" logical name and
        # there is no "bss-peer" → "bss-peer" key missing from namespace_dict → exit(1).
        sd = {
            "userData": {"useDeployPostfixAsNamespace": True},
            "applications": [{"deployPostfix": "bss-peer"}],
        }
        namespace_dict = {"bss-origin": "bss-origin"}  # peer side missing

        with caplog.at_level(logging.ERROR, logger="envgene"):
            with pytest.raises(SystemExit):
                handle_deploy_postfix_namespace_transformation(sd, namespace_dict)

    # ------------------------------------------------------------------
    # build_namespace_dict — negative
    # ------------------------------------------------------------------

    def test_namespace_yml_with_integer_name_is_skipped(self, caplog):
        # namespace.yml with a non-string 'name' (e.g. integer) must be skipped with warning.
        env = self._env("int-name")
        ns_file = Path(env.env_path) / "Namespaces" / "ns1" / "namespace.yml"
        _write(ns_file, "name: 12345\n")

        with caplog.at_level(logging.WARNING, logger="envgene"):
            result = build_namespace_dict(env)

        assert result == {}
        assert "missing or invalid" in caplog.text

    def test_namespace_yml_empty_name_is_skipped(self, caplog):
        # Empty string name is falsy — same branch as missing name → warning + skip.
        env = self._env("empty-name")
        ns_file = Path(env.env_path) / "Namespaces" / "ns1" / "namespace.yml"
        _write(ns_file, "name: ''\n")

        with caplog.at_level(logging.WARNING, logger="envgene"):
            result = build_namespace_dict(env)

        assert result == {}
        assert "missing or invalid" in caplog.text

    def test_duplicate_logical_names_last_wins(self):
        # Two namespace folders with the same logical name — last processed wins (dict behavior).
        env = self._env("duplicate-name")
        _write_namespace(env, "folder-a", "same-logical-name")
        _write_namespace(env, "folder-b", "same-logical-name")

        result = build_namespace_dict(env)

        # Only one entry survives; the value is one of the two folder names.
        assert "same-logical-name" in result
        assert result["same-logical-name"] in ("folder-a", "folder-b")

    def test_namespace_yml_malformed_yaml_raises(self):
        # Completely malformed YAML in namespace.yml — must raise (no silent skip).
        env = self._env("malformed-yml")
        ns_file = Path(env.env_path) / "Namespaces" / "ns1" / "namespace.yml"
        _write(ns_file, ": :\n  bad: [yaml\n")

        with pytest.raises(Exception):
            build_namespace_dict(env)
