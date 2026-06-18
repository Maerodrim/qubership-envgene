"""
Cross-context parameter reference integration tests.

UC-CC-CR-3..6 — cross-parameter-type references within the same Namespace.

Integration pattern: the parameter template is written to a YAML file in
output_dir (mimicking a namespace paramset file), read back via openYaml,
and passed to render_obj_by_context.  Context variables are loaded from a
separate YAML file (mimicking a merged namespace.yml) so the full file-based
data flow is exercised.

Scoping rules:
- deployParameters → Deployment context (deployment-parameters.yaml)
- technicalConfigurationParameters → Runtime context (runtime/parameters.yaml)
- e2eParameters → Pipeline context only; NOT included in deployment or runtime scope

UC-CC-CR-3 / UC-CC-CR-4: e2eParameters reference deploy or technical vars.
The Jinja2 substitution works in pipeline scope (all vars present), but
e2eParameters values are never written to deployment/runtime output — "silent drop".

UC-CC-CR-5: technicalConfigurationParameters reference deployParameters.
The runtime context merges both types, so the reference resolves successfully.

UC-CC-CR-6: technicalConfigurationParameters reference e2eParameters.
e2eParameters are NOT in runtime context; the reference is unresolvable.
At the Python rendering level this renders empty (ChainableUndefined); the
Effective Set generator (Java CLI) raises "Could not process expression for
parameter <name> with value: ${e2e_endpoint}" in this scenario.
"""
import os
import sys
from pathlib import Path

import envgenehelper as helper,logger
import yaml

from scripts.build_env.tests.base_test import BaseTest

os.environ.setdefault("ENVIRONMENT_NAME", "env-01")
os.environ.setdefault("CLUSTER_NAME", "cluster-01")

_BUILD_ENV = Path(__file__).resolve().parents[2]
if str(_BUILD_ENV) not in sys.path:
    sys.path.insert(0, str(_BUILD_ENV))

from render_config_env import Context, render_obj_by_context

FEATURE_TEST_DIR = "test_cross_context_references"


def _write_yaml(path: Path, content: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(content, default_flow_style=False, allow_unicode=True))


def _render_from_files(template_path: Path, ctx_path: Path) -> dict:
    template = helper.openYaml(template_path)
    ctx_vars = helper.openYaml(ctx_path)
    ctx = Context(**{k: v for k, v in ctx_vars.items() if v is not None})
    return render_obj_by_context(template, ctx)


class TestCrossContextReferences(BaseTest):
    """
    UC-CC-CR-3..6 — cross-parameter-type references within the same Namespace.
    """
    logger.info(f"Starting SD test:\n\tTest case: UC-CC-CR-3..6")

    def setup_method(self):
        self.feature_dir = self.output_dir / FEATURE_TEST_DIR
        self.feature_dir.mkdir(parents=True, exist_ok=True)

    def _files(self, name: str, template: dict, ctx: dict) -> tuple[Path, Path]:
        t = self.feature_dir / f"template_{name}.yml"
        c = self.feature_dir / f"ctx_{name}.yml"
        _write_yaml(t, template)
        _write_yaml(c, ctx)
        return t, c

    # ------------------------------------------------------------------
    # UC-CC-CR-3: E2EParameters → DeployParameters — silent drop
    # ------------------------------------------------------------------

    def test_uc_cr_3_e2e_referencing_deploy_resolves_in_pipeline_context(self):
        t, c = self._files(
            "cr3_pipeline",
            {"test_endpoint": "{{ api_url }}"},
            {"api_url": "https://api.example.com"},
        )
        result = _render_from_files(t, c)
        assert result["test_endpoint"] == "https://api.example.com"

    def test_uc_cr_3_e2e_variable_absent_from_deployment_context_renders_empty(self):
        t, c = self._files("cr3_deploy", {"test_endpoint": "{{ e2e_only_var }}"}, {})
        result = _render_from_files(t, c)
        assert result.get("test_endpoint") in (None, "", "None")

    # ------------------------------------------------------------------
    # UC-CC-CR-4: E2EParameters → TechnicalConfigurationParameters — silent drop
    # ------------------------------------------------------------------

    def test_uc_cr_4_valid_technical_param_unaffected_by_absent_e2e_ref(self):
        t, c = self._files(
            "cr4",
            {"config_endpoint": "{{ config_endpoint }}", "test_config": "{{ e2e_test_config }}"},
            {"config_endpoint": "https://config.example.com"},
        )
        result = _render_from_files(t, c)
        assert result["config_endpoint"] == "https://config.example.com"
        assert result.get("test_config") in (None, "", "None")

    # ------------------------------------------------------------------
    # UC-CC-CR-5: TechnicalConfigurationParameters → DeployParameters — resolves
    # ------------------------------------------------------------------

    def test_uc_cr_5_technical_referencing_deploy_resolves_successfully(self):
        t, c = self._files(
            "cr5_resolve",
            {"runtime_config": "{{ deploy_url }}"},
            {"deploy_url": "https://deploy.example.com"},
        )
        result = _render_from_files(t, c)
        assert result["runtime_config"] == "https://deploy.example.com"

    def test_uc_cr_5_both_runtime_and_deploy_outputs_populated(self):
        t, c = self._files(
            "cr5_both",
            {"deploy_url": "{{ deploy_url }}", "runtime_config": "{{ deploy_url }}"},
            {"deploy_url": "https://deploy.example.com"},
        )
        result = _render_from_files(t, c)
        assert result["deploy_url"] == "https://deploy.example.com"
        assert result["runtime_config"] == "https://deploy.example.com"

    # ------------------------------------------------------------------
    # UC-CC-CR-6: TechnicalConfigurationParameters → E2EParameters — not resolved
    # ------------------------------------------------------------------

    def test_uc_cr_6_technical_referencing_e2e_renders_empty_in_runtime_context(self):
        t, c = self._files("cr6_empty", {"runtime_endpoint": "{{ e2e_endpoint }}"}, {})
        result = _render_from_files(t, c)
        assert result.get("runtime_endpoint") in (None, "", "None")

    def test_uc_cr_6_other_technical_params_resolve_even_when_e2e_missing(self):
        t, c = self._files(
            "cr6_mixed",
            {"valid_runtime_config": "{{ deploy_url }}", "broken_e2e_ref": "{{ e2e_endpoint }}"},
            {"deploy_url": "https://deploy.example.com"},
        )
        result = _render_from_files(t, c)
        assert result["valid_runtime_config"] == "https://deploy.example.com"
        assert result.get("broken_e2e_ref") in (None, "", "None")

    def test_uc_cr_6_e2e_endpoint_source_value_in_pipeline_context(self):
        t_pipeline, c_pipeline = self._files(
            "cr6_pipeline",
            {"runtime_endpoint": "{{ e2e_endpoint }}"},
            {"e2e_endpoint": "https://e2e.example.com"},
        )
        t_runtime, c_runtime = self._files(
            "cr6_runtime",
            {"runtime_endpoint": "{{ e2e_endpoint }}"},
            {},
        )
        pipeline_result = _render_from_files(t_pipeline, c_pipeline)
        runtime_result = _render_from_files(t_runtime, c_runtime)
        assert pipeline_result["runtime_endpoint"] == "https://e2e.example.com"
        assert runtime_result.get("runtime_endpoint") in (None, "", "None")
