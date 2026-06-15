import json
import os

import pytest

from scripts.build_env.tests.base_test import BaseTest

os.environ.setdefault("ENVIRONMENT_NAME", "env-01")
os.environ.setdefault("CLUSTER_NAME", "cluster-01")

from build_effective_set_generator.scripts.handle_effective_set_config import handle_effective_set_config


# ---------------------------------------------------------------------------
# UC-ES-DEP-A16 / UC-ES-DEP-A18: app_chart_validation config flag
# ---------------------------------------------------------------------------

class TestHandleEffectiveSetConfigAppChart(BaseTest):
    """
    UC-ES-DEP-A16 — app chart validation enabled (default).
    UC-ES-DEP-A18 — app chart validation disabled via EFFECTIVE_SET_CONFIG.

    handle_effective_set_config() is the Python layer that parses the
    EFFECTIVE_SET_CONFIG JSON and emits CLI arguments consumed by the Java
    effective-set-generator CLI.  These tests verify the flag is wired
    correctly without invoking the Java CLI itself.
    """

    # ------------------------------------------------------------------
    # UC-ES-DEP-A16: validation enabled — default and explicit true
    # ------------------------------------------------------------------

    def test_app_chart_validation_explicit_true_emits_true_flag(self):
        # UC-ES-DEP-A16: explicit true → --app_chart_validation=true.
        result = handle_effective_set_config('{"app_chart_validation": true}')
        assert "--app_chart_validation=true" in result["extra_args"]

    def test_app_chart_validation_true_version_flag_also_present(self):
        # UC-ES-DEP-A16: app chart flag and version flag both emitted.
        result = handle_effective_set_config(
            '{"version": "v2.0", "app_chart_validation": true}'
        )
        flags = result["extra_args"]
        assert any("app_chart_validation=true" in f for f in flags)
        assert any("effective-set-version=v2.0" in f for f in flags), (
            "version flag must always be present"
        )

    def test_empty_config_defaults_app_chart_validation_to_true(self):
        # UC-ES-DEP-A16: An empty JSON object has no override → default True applied.
        result = handle_effective_set_config("{}")
        assert "--app_chart_validation=true" in result["extra_args"]

    def test_app_chart_validation_true_does_not_emit_false(self):
        # UC-ES-DEP-A16: when enabled, --app_chart_validation=false must NOT appear.
        result = handle_effective_set_config('{"app_chart_validation": true}')
        assert "--app_chart_validation=false" not in result["extra_args"]

    # ------------------------------------------------------------------
    # UC-ES-DEP-A18: validation disabled via false flag
    # ------------------------------------------------------------------

    def test_app_chart_validation_false_emits_false_flag(self):
        # UC-ES-DEP-A18: EFFECTIVE_SET_CONFIG includes "app_chart_validation": false →
        # --app_chart_validation=false; Java CLI skips app chart validation.
        result = handle_effective_set_config('{"app_chart_validation": false}')
        assert "--app_chart_validation=false" in result["extra_args"], (
            f"expected --app_chart_validation=false in extra_args; got: {result['extra_args']}"
        )

    def test_app_chart_validation_false_does_not_emit_true(self):
        # UC-ES-DEP-A18: when disabled, --app_chart_validation=true must NOT appear.
        result = handle_effective_set_config('{"app_chart_validation": false}')
        assert "--app_chart_validation=true" not in result["extra_args"]

    def test_app_chart_validation_false_with_version(self):
        # UC-ES-DEP-A18: both version and app_chart_validation=false together.
        result = handle_effective_set_config(
            '{"version": "v2.0", "app_chart_validation": false}'
        )
        flags = result["extra_args"]
        assert "--app_chart_validation=false" in flags
        assert any("effective-set-version=v2.0" in f for f in flags)

    def test_app_chart_validation_false_generation_would_succeed(self):
        # UC-ES-DEP-A18: the config call itself must complete without error;
        # the resulting CLI arg is what causes the Java CLI to skip validation.
        try:
            result = handle_effective_set_config('{"app_chart_validation": false}')
        except Exception as exc:
            raise AssertionError(
                f"handle_effective_set_config raised unexpectedly: {exc!r}"
            )
        assert isinstance(result, dict)
        assert "extra_args" in result

    # ------------------------------------------------------------------
    # UC-ES-DEP-14: version flag is always emitted
    # ------------------------------------------------------------------

    def test_version_default_applied_when_absent(self):
        # UC-ES-DEP-14: no version key → default v2.0 → --effective-set-version=v2.0.
        result = handle_effective_set_config('{"app_chart_validation": true}')
        assert any("effective-set-version=v2.0" in f for f in result["extra_args"]), (
            f"default version v2.0 expected; got: {result['extra_args']}"
        )

    def test_custom_version_forwarded_to_cli(self):
        # UC-ES-DEP-14: custom version string is preserved verbatim.
        result = handle_effective_set_config('{"version": "v3.1"}')
        assert any("effective-set-version=v3.1" in f for f in result["extra_args"])

    # ------------------------------------------------------------------
    # Negative
    # ------------------------------------------------------------------

    def test_invalid_json_raises_json_decode_error(self):
        # Malformed EFFECTIVE_SET_CONFIG must raise JSONDecodeError, not silently ignore.
        with pytest.raises(json.JSONDecodeError):
            handle_effective_set_config("not-json-{")

    def test_extra_args_is_a_list(self):
        # extra_args must be a list so the caller can extend the CLI command list.
        result = handle_effective_set_config('{}')
        assert isinstance(result["extra_args"], list), (
            f"extra_args must be a list; got: {type(result['extra_args'])}"
        )
