"""
Error Handling integration tests.

UC-AD-ERR-1  Missing AppDef  — get_appdef_for_app raises FileNotFoundError when
             AppDefs/{app}.yml/.yaml is absent.

UC-AD-ERR-2  Missing RegDef  — get_appdef_for_app raises FileNotFoundError when
             RegDefs/{registry}.yml/.yaml is absent (AppDef found but RegDef gone).

Tests call real production code (process_sd.get_appdef_for_app) with a real
temporary filesystem.  APP_DEFS_PATH and REG_DEFS_PATH are module-level globals
that are frozen at import time; they are patched per-test to point to the per-test
tmp directory so each test gets an isolated, predictable filesystem state.

PluginEngine is pointed at a nonexistent plugins directory so it returns an empty
result set and falls through to the file-based AppDef/RegDef lookup — the same
code path taken at runtime when no plugins are installed.
"""
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.build_env.tests.base_test import BaseTest

os.environ.setdefault("ENVIRONMENT_NAME", "env-01")
os.environ.setdefault("CLUSTER_NAME", "cluster-01")

_BUILD_ENV = Path(__file__).resolve().parents[2]
if str(_BUILD_ENV) not in sys.path:
    sys.path.insert(0, str(_BUILD_ENV))

from envgenehelper.plugin_engine import PluginEngine
import process_sd
from process_sd import get_appdef_for_app

FEATURE_TEST_DIR = "test_error_handling"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _no_op_plugins(base_dir: Path) -> PluginEngine:
    """Return a PluginEngine that discovers no plugins (nonexistent dir → empty)."""
    return PluginEngine(plugins_dir=str(base_dir / "_no_plugins"))


# ---------------------------------------------------------------------------
# UC-AD-ERR-1: Missing AppDef
# ---------------------------------------------------------------------------

class TestMissingAppDef(BaseTest):
    """
    UC-AD-ERR-1 — when AppDefs/{app}.yml/.yaml is missing, get_appdef_for_app
    must raise FileNotFoundError so the pipeline can report a meaningful error
    instead of silently continuing with an empty config.
    """

    def setup_method(self):
        self.feature_dir = self.output_dir / FEATURE_TEST_DIR / "err1"
        self.feature_dir.mkdir(parents=True, exist_ok=True)
        self.appdef_dir = self.feature_dir / "AppDefs"
        self.regdef_dir = self.feature_dir / "RegDefs"

    def test_missing_appdef_directory_raises_file_not_found(self):
        # AppDefs/ does not exist at all → FileNotFoundError from identify_yaml_extension.
        plugins = _no_op_plugins(self.feature_dir)
        with patch.object(process_sd, "APP_DEFS_PATH", str(self.appdef_dir)), \
             patch.object(process_sd, "REG_DEFS_PATH", str(self.regdef_dir)):
            with pytest.raises(FileNotFoundError):
                get_appdef_for_app("my-app:1.0.0", "my-app", plugins)

    def test_missing_appdef_file_raises_file_not_found(self):
        # AppDefs/ directory exists but app.yml/app.yaml are absent.
        self.appdef_dir.mkdir(parents=True, exist_ok=True)

        plugins = _no_op_plugins(self.feature_dir)
        with patch.object(process_sd, "APP_DEFS_PATH", str(self.appdef_dir)), \
             patch.object(process_sd, "REG_DEFS_PATH", str(self.regdef_dir)):
            with pytest.raises(FileNotFoundError):
                get_appdef_for_app("missing-app:2.0.0", "missing-app", plugins)

    def test_error_message_contains_app_name(self):
        # FileNotFoundError message must mention attempted file paths so
        # operators can locate the problem without reading source code.
        self.appdef_dir.mkdir(parents=True, exist_ok=True)

        plugins = _no_op_plugins(self.feature_dir)
        with patch.object(process_sd, "APP_DEFS_PATH", str(self.appdef_dir)), \
             patch.object(process_sd, "REG_DEFS_PATH", str(self.regdef_dir)):
            with pytest.raises(FileNotFoundError) as exc_info:
                get_appdef_for_app("my-service:3.1.0", "my-service", plugins)
        assert "my-service" in str(exc_info.value)

    def test_other_appdef_present_does_not_satisfy_missing_app(self):
        # Other AppDef files present, but the requested app is absent.
        _write(self.appdef_dir / "other-app.yml", "name: other-app\nregistryName: reg-1\n")

        plugins = _no_op_plugins(self.feature_dir)
        with patch.object(process_sd, "APP_DEFS_PATH", str(self.appdef_dir)), \
             patch.object(process_sd, "REG_DEFS_PATH", str(self.regdef_dir)):
            with pytest.raises(FileNotFoundError):
                get_appdef_for_app("missing-app:1.0.0", "missing-app", plugins)


# ---------------------------------------------------------------------------
# UC-AD-ERR-2: Missing RegDef
# ---------------------------------------------------------------------------

class TestMissingRegDef(BaseTest):
    """
    UC-AD-ERR-2 — AppDef is present and points to a registry, but RegDefs/{registry}
    .yml/.yaml is absent.  get_appdef_for_app must raise FileNotFoundError so the
    pipeline reports a missing registry definition rather than crashing on a KeyError.
    """

    def setup_method(self):
        self.feature_dir = self.output_dir / FEATURE_TEST_DIR / "err2"
        self.feature_dir.mkdir(parents=True, exist_ok=True)
        self.appdef_dir = self.feature_dir / "AppDefs"
        self.regdef_dir = self.feature_dir / "RegDefs"

    def _make_appdef(self, name: str = "my-app", registry_name: str = "nexus-registry") -> None:
        content = (
            f"name: {name}\n"
            f"registryName: {registry_name}\n"
            "groupId: com.example\n"
            f"artifactId: {name}\n"
        )
        _write(self.appdef_dir / f"{name}.yml", content)

    def test_missing_regdef_directory_raises_file_not_found(self):
        # AppDef present, RegDefs/ directory absent entirely.
        self._make_appdef("my-app", "nexus-registry")

        plugins = _no_op_plugins(self.feature_dir)
        with patch.object(process_sd, "APP_DEFS_PATH", str(self.appdef_dir)), \
             patch.object(process_sd, "REG_DEFS_PATH", str(self.regdef_dir)):
            with pytest.raises(FileNotFoundError):
                get_appdef_for_app("my-app:1.0.0", "my-app", plugins)

    def test_missing_regdef_file_raises_file_not_found(self):
        # AppDef present and RegDefs/ directory exists, but the referenced registry file is absent.
        self._make_appdef("my-app", "nexus-registry")
        self.regdef_dir.mkdir(parents=True, exist_ok=True)

        plugins = _no_op_plugins(self.feature_dir)
        with patch.object(process_sd, "APP_DEFS_PATH", str(self.appdef_dir)), \
             patch.object(process_sd, "REG_DEFS_PATH", str(self.regdef_dir)):
            with pytest.raises(FileNotFoundError):
                get_appdef_for_app("my-app:1.0.0", "my-app", plugins)

    def test_wrong_registry_name_raises_file_not_found(self):
        # AppDef references "nexus-registry" but only "other-registry" exists.
        self._make_appdef("my-app", "nexus-registry")
        _write(
            self.regdef_dir / "other-registry.yml",
            "name: other-registry\nmavenConfig:\n  repositoryDomainName: https://other.example.com/\n",
        )

        plugins = _no_op_plugins(self.feature_dir)
        with patch.object(process_sd, "APP_DEFS_PATH", str(self.appdef_dir)), \
             patch.object(process_sd, "REG_DEFS_PATH", str(self.regdef_dir)):
            with pytest.raises(FileNotFoundError):
                get_appdef_for_app("my-app:1.0.0", "my-app", plugins)

    def test_error_message_contains_registry_name(self):
        # Error must mention the registry name so operators can trace the missing file.
        self._make_appdef("my-app", "nexus-registry")
        self.regdef_dir.mkdir(parents=True, exist_ok=True)

        plugins = _no_op_plugins(self.feature_dir)
        with patch.object(process_sd, "APP_DEFS_PATH", str(self.appdef_dir)), \
             patch.object(process_sd, "REG_DEFS_PATH", str(self.regdef_dir)):
            with pytest.raises(FileNotFoundError) as exc_info:
                get_appdef_for_app("my-app:1.0.0", "my-app", plugins)
        assert "nexus-registry" in str(exc_info.value)

    def test_appdef_with_yaml_extension_also_resolves(self):
        # AppDef stored as .yaml (not .yml) — identify_yaml_extension must find it too.
        _write(
            self.appdef_dir / "yaml-app.yaml",
            "name: yaml-app\nregistryName: nexus-registry\ngroupId: g\nartifactId: yaml-app\n",
        )
        # RegDef absent → FileNotFoundError (proves AppDef was found and parsed).
        plugins = _no_op_plugins(self.feature_dir)
        with patch.object(process_sd, "APP_DEFS_PATH", str(self.appdef_dir)), \
             patch.object(process_sd, "REG_DEFS_PATH", str(self.regdef_dir)):
            with pytest.raises(FileNotFoundError) as exc_info:
                get_appdef_for_app("yaml-app:1.0.0", "yaml-app", plugins)
        # The error must be about the registry, not the app — proves AppDef resolved.
        assert "nexus-registry" in str(exc_info.value)

    def test_full_happy_path_with_real_files(self):
        # Both AppDef and RegDef present — get_appdef_for_app must return an Application.
        from artifact_searcher.utils.models import Application

        self._make_appdef("my-app", "nexus-registry")
        _write(
            self.regdef_dir / "nexus-registry.yml",
            (
                "name: nexus-registry\n"
                "mavenConfig:\n"
                "  repositoryDomainName: https://nexus.example.com/repository/maven/\n"
                "  targetSnapshot: snapshots\n"
                "  targetStaging: staging\n"
                "  targetRelease: releases\n"
            ),
        )

        plugins = _no_op_plugins(self.feature_dir)
        with patch.object(process_sd, "APP_DEFS_PATH", str(self.appdef_dir)), \
             patch.object(process_sd, "REG_DEFS_PATH", str(self.regdef_dir)):
            app_def = get_appdef_for_app("my-app:1.0.0", "my-app", plugins)
        assert isinstance(app_def, Application)
        assert app_def.name == "my-app"
        assert app_def.registry.name == "nexus-registry"
