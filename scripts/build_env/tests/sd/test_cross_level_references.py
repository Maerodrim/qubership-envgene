"""
Cross-level parameter reference integration tests.

UC-CC-HR-1..6 — parameters at one hierarchy level reference values from another.

Integration pattern: the parameter template is written to a YAML file in
output_dir (mimicking a paramset file for a Cloud, Tenant, or Namespace),
read back via openYaml, and passed to render_obj_by_context with a Context
loaded from a YAML file (mimicking the merged context built by the Calculator).
This mirrors the exact data flow at runtime.

render_obj_by_context receives a flat Context whose fields hold the already-merged
parameter maps from every level. Cross-level resolution is the same Jinja2 mechanism
as same-level resolution; what makes it cross-level is that the source variable
originates from a different hierarchy object than the template being rendered.
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

FEATURE_TEST_DIR = "test_cross_level_references"


def _write_yaml(path: Path, content: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(content, default_flow_style=False, allow_unicode=True))


def _render_from_files(template_path: Path, ctx_path: Path) -> dict:
    template = helper.openYaml(template_path)
    ctx_vars = helper.openYaml(ctx_path)
    ctx = Context(**{k: v for k, v in ctx_vars.items() if v is not None})
    return render_obj_by_context(template, ctx)


class TestCrossLevelReferences(BaseTest):
    """
    UC-CC-HR-1..6 — parameters at one hierarchy level reference values from another.
    """
    logger.info(f"Starting SD test:\n\tTest case: UC-CC-HR-1..6")

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
    # UC-CC-HR-1: Namespace → Cloud
    # ------------------------------------------------------------------

    def test_uc_hr_1_namespace_deploy_resolves_cloud_api_url(self):
        t, c = self._files(
            "hr1_deploy",
            {"service_url": "{{ cloud_api_url }}"},
            {"cloud_api_url": "https://api.example.com"},
        )
        result = _render_from_files(t, c)
        assert result["service_url"] == "https://api.example.com"

    def test_uc_hr_1_namespace_technical_resolves_cloud_config_url(self):
        t, c = self._files(
            "hr1_technical",
            {"config_endpoint": "{{ cloud_config_url }}"},
            {"cloud_config_url": "https://config.example.com"},
        )
        result = _render_from_files(t, c)
        assert result["config_endpoint"] == "https://config.example.com"

    def test_uc_hr_1_namespace_e2e_reference_resolves_at_jinja2_level(self):
        t, c = self._files(
            "hr1_e2e",
            {"test_endpoint": "{{ cloud_test_url }}"},
            {"cloud_test_url": "https://test.example.com"},
        )
        result = _render_from_files(t, c)
        assert result["test_endpoint"] == "https://test.example.com"

    # ------------------------------------------------------------------
    # UC-CC-HR-2: Namespace → Tenant
    # ------------------------------------------------------------------

    def test_uc_hr_2_namespace_deploy_resolves_tenant_id(self):
        t, c = self._files(
            "hr2_deploy",
            {"organization": "{{ tenant_id }}"},
            {"tenant_id": "acme-corp"},
        )
        result = _render_from_files(t, c)
        assert result["organization"] == "acme-corp"

    def test_uc_hr_2_namespace_technical_resolves_tenant_config_id(self):
        t, c = self._files(
            "hr2_technical",
            {"config_org": "{{ tenant_config_id }}"},
            {"tenant_config_id": "acme-config"},
        )
        result = _render_from_files(t, c)
        assert result["config_org"] == "acme-config"

    # ------------------------------------------------------------------
    # UC-CC-HR-3: Cloud → Tenant
    # ------------------------------------------------------------------

    def test_uc_hr_3_cloud_deploy_resolves_tenant_name(self):
        t, c = self._files(
            "hr3_deploy",
            {"cloud_label": "{{ tenant_name }}"},
            {"tenant_name": "acme-corp"},
        )
        result = _render_from_files(t, c)
        assert result["cloud_label"] == "acme-corp"

    def test_uc_hr_3_cloud_technical_resolves_tenant_config_name(self):
        t, c = self._files(
            "hr3_technical",
            {"cloud_config_label": "{{ tenant_config_name }}"},
            {"tenant_config_name": "acme-config"},
        )
        result = _render_from_files(t, c)
        assert result["cloud_config_label"] == "acme-config"

    def test_uc_hr_3_cloud_e2e_resolves_tenant_test_name(self):
        t, c = self._files(
            "hr3_e2e",
            {"cloud_test_label": "{{ tenant_test_name }}"},
            {"tenant_test_name": "acme-test"},
        )
        result = _render_from_files(t, c)
        assert result["cloud_test_label"] == "acme-test"

    def test_uc_hr_3_all_three_contexts_resolved_in_one_template(self):
        t, c = self._files(
            "hr3_all",
            {
                "cloud_label": "{{ tenant_name }}",
                "cloud_test_label": "{{ tenant_test_name }}",
                "cloud_config_label": "{{ tenant_config_name }}",
            },
            {
                "tenant_name": "acme-corp",
                "tenant_test_name": "acme-test",
                "tenant_config_name": "acme-config",
            },
        )
        result = _render_from_files(t, c)
        assert result["cloud_label"] == "acme-corp"
        assert result["cloud_test_label"] == "acme-test"
        assert result["cloud_config_label"] == "acme-config"

    # ------------------------------------------------------------------
    # UC-CC-HR-4: Cloud → Namespace (downward reference)
    # ------------------------------------------------------------------

    def test_uc_hr_4_cloud_deploy_resolves_namespace_db_url(self):
        t, c = self._files(
            "hr4_deploy",
            {"cloud_config": "{{ namespace_db_url }}"},
            {"namespace_db_url": "postgres://db.local"},
        )
        result = _render_from_files(t, c)
        assert result["cloud_config"] == "postgres://db.local"

    def test_uc_hr_4_cloud_technical_resolves_namespace_config_url(self):
        t, c = self._files(
            "hr4_technical",
            {"cloud_config_param": "{{ namespace_config_url }}"},
            {"namespace_config_url": "https://config.local"},
        )
        result = _render_from_files(t, c)
        assert result["cloud_config_param"] == "https://config.local"

    # ------------------------------------------------------------------
    # UC-CC-HR-5: Tenant → Cloud (downward reference)
    # ------------------------------------------------------------------

    def test_uc_hr_5_tenant_deploy_resolves_cloud_region(self):
        t, c = self._files(
            "hr5_deploy",
            {"tenant_config": "{{ cloud_region }}"},
            {"cloud_region": "us-east-1"},
        )
        result = _render_from_files(t, c)
        assert result["tenant_config"] == "us-east-1"

    def test_uc_hr_5_tenant_technical_resolves_cloud_config_region(self):
        t, c = self._files(
            "hr5_technical",
            {"tenant_config_param": "{{ cloud_config_region }}"},
            {"cloud_config_region": "eu-central-1"},
        )
        result = _render_from_files(t, c)
        assert result["tenant_config_param"] == "eu-central-1"

    # ------------------------------------------------------------------
    # UC-CC-HR-6: Tenant → Namespace (downward reference)
    # ------------------------------------------------------------------

    def test_uc_hr_6_tenant_deploy_resolves_namespace_name(self):
        t, c = self._files(
            "hr6_deploy",
            {"tenant_label": "{{ namespace_name }}"},
            {"namespace_name": "core"},
        )
        result = _render_from_files(t, c)
        assert result["tenant_label"] == "core"

    def test_uc_hr_6_tenant_technical_resolves_namespace_config_name(self):
        t, c = self._files(
            "hr6_technical",
            {"tenant_config_label": "{{ namespace_config_name }}"},
            {"namespace_config_name": "config-core"},
        )
        result = _render_from_files(t, c)
        assert result["tenant_config_label"] == "config-core"

    # ------------------------------------------------------------------
    # Negative
    # ------------------------------------------------------------------

    def test_missing_cross_level_var_renders_empty_without_exception(self):
        t, c = self._files("hr_missing", {"service_url": "{{ cloud_api_url }}"}, {})
        result = _render_from_files(t, c)
        assert result.get("service_url") in (None, "", "None")

    def test_all_three_hierarchy_levels_in_one_template(self):
        t, c = self._files(
            "hr_all",
            {
                "ns_from_cloud": "{{ cloud_api_url }}",
                "ns_from_tenant": "{{ tenant_id }}",
                "cloud_from_tenant": "{{ tenant_name }}",
            },
            {
                "cloud_api_url": "https://api.example.com",
                "tenant_id": "acme-corp",
                "tenant_name": "acme-corp",
            },
        )
        result = _render_from_files(t, c)
        assert result["ns_from_cloud"] == "https://api.example.com"
        assert result["ns_from_tenant"] == "acme-corp"
        assert result["cloud_from_tenant"] == "acme-corp"
