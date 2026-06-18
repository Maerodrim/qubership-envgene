"""
Macro resolution integration tests.

UC-CC-MR-1..2 — Jinja2 macro substitution in paramset templates.

Integration pattern: the parameter template is written to a YAML file in
output_dir (mimicking a namespace paramset file from the rendered template
archive), read back via openYaml, and passed to render_obj_by_context with
a Context loaded from a separate YAML file (mimicking the merged namespace
context).  This mirrors the exact runtime data flow through the Calculator.
"""
import os
import sys
from pathlib import Path

import envgenehelper as helper
import logger
import yaml

from scripts.build_env.tests.base_test import BaseTest

os.environ.setdefault("ENVIRONMENT_NAME", "env-01")
os.environ.setdefault("CLUSTER_NAME", "cluster-01")

_BUILD_ENV = Path(__file__).resolve().parents[2]
if str(_BUILD_ENV) not in sys.path:
    sys.path.insert(0, str(_BUILD_ENV))

from render_config_env import Context, render_obj_by_context

FEATURE_TEST_DIR = "test_macro_resolution"


def _write_yaml(path: Path, content: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(content, default_flow_style=False, allow_unicode=True))


def _render_from_files(template_path: Path, ctx_path: Path) -> dict:
    template = helper.openYaml(template_path)
    ctx_vars = helper.openYaml(ctx_path)
    ctx = Context(**{k: v for k, v in ctx_vars.items() if v is not None})
    return render_obj_by_context(template, ctx)


# ---------------------------------------------------------------------------
# UC-CC-MR-1: Simple type resolution
# ---------------------------------------------------------------------------

class TestMacroSimpleTypeResolution(BaseTest):
    """
    UC-CC-MR-1 — macro references resolve context values into the template.

    Type note: render_obj_by_context works by converting the template dict to a YAML
    string (which quotes string values), substituting via Jinja2, then parsing back.
    Because template values like "{{ server_port }}" are YAML-quoted strings, the
    substituted result is also a YAML-quoted string — int/bool context values become
    their string representations ("8080", "True", "False").
    """

    def setup_method(self):
        self.feature_dir = self.output_dir / FEATURE_TEST_DIR / "simple"
        self.feature_dir.mkdir(parents=True, exist_ok=True)

    def _files(self, name: str, template: dict, ctx: dict) -> tuple[Path, Path]:
        t = self.feature_dir / f"template_{name}.yml"
        c = self.feature_dir / f"ctx_{name}.yml"
        _write_yaml(t, template)
        _write_yaml(c, ctx)
        return t, c

    def test_boolean_false_context_value_becomes_string(self):
        logger.info(f"Starting SD test:\n\tTest case: UC-CC-MR-1")
        t, c = self._files("bool_false", {"debug": "{{ debug_flag }}"}, {"debug_flag": False})
        result = _render_from_files(t, c)
        assert result["debug"] == "False"
        assert isinstance(result["debug"], str)

    def test_all_four_types_resolved_in_one_template(self):
        t, c = self._files(
            "four_types",
            {
                "api_port": "{{ server_port }}",
                "service_version": "{{ app_version }}",
                "use_ssl": "{{ ssl_enabled }}",
                "log_level": "{{ debug_mode }}",
            },
            {
                "server_port": 8080,
                "app_version": "3.0",
                "ssl_enabled": True,
                "debug_mode": "true",
            },
        )
        result = _render_from_files(t, c)
        assert result["api_port"] == "8080"
        assert result["service_version"] == "3.0"
        assert result["use_ssl"] == "True"
        assert result["log_level"] == "true"

    def test_integer_zero_becomes_string_zero(self):
        t, c = self._files("zero", {"timeout": "{{ zero_val }}"}, {"zero_val": 0})
        result = _render_from_files(t, c)
        assert result["timeout"] == "0"
        assert isinstance(result["timeout"], str)

    def test_missing_reference_renders_as_empty(self):
        t, c = self._files("missing", {"key": "{{ nonexistent_var }}"}, {})
        result = _render_from_files(t, c)
        assert result.get("key") in (None, "", "None")

    def test_partial_string_with_defined_macro_substitutes_only_macro(self):
        t, c = self._files(
            "partial_defined",
            {"url": "https://{{ host }}/api"},
            {"host": "example.com"},
        )
        result = _render_from_files(t, c)
        assert result["url"] == "https://example.com/api"

    def test_partial_string_with_missing_macro_preserves_surrounding_text(self):
        t, c = self._files("partial_missing", {"url": "prefix-{{ missing }}-suffix"}, {})
        result = _render_from_files(t, c)
        assert "prefix" in str(result.get("url", ""))
        assert "suffix" in str(result.get("url", ""))


# ---------------------------------------------------------------------------
# UC-CC-MR-2: Complex structure resolution
# ---------------------------------------------------------------------------

class TestMacroComplexStructureResolution(BaseTest):
    """
    UC-CC-MR-2 — macro substitution in nested dict templates with string context values.

    Limitation: passing dict or list objects as context variables does not work because
    Python's str() representation of dicts/lists is not valid YAML.  All context
    variables substituted via "{{ var }}" must be scalar (string, int, bool) values.
    """

    def setup_method(self):
        self.feature_dir = self.output_dir / FEATURE_TEST_DIR / "complex"
        self.feature_dir.mkdir(parents=True, exist_ok=True)

    def _files(self, name: str, template: dict, ctx: dict) -> tuple[Path, Path]:
        t = self.feature_dir / f"template_{name}.yml"
        c = self.feature_dir / f"ctx_{name}.yml"
        _write_yaml(t, template)
        _write_yaml(c, ctx)
        return t, c

    def test_nested_dict_template_all_leaf_macros_resolved(self):
        logger.info(f"Starting SD test:\n\tTest case: UC-CC-MR-2")
        t, c = self._files(
            "nested",
            {"connection": {"host": "{{ db_host }}", "port": "{{ db_port }}", "ssl": "{{ db_ssl }}"}},
            {"db_host": "db.example.com", "db_port": "5432", "db_ssl": "true"},
        )
        result = _render_from_files(t, c)
        assert result["connection"]["host"] == "db.example.com"
        assert result["connection"]["port"] == "5432"
        assert result["connection"]["ssl"] == "true"

    def test_deeply_nested_dict_all_levels_preserved(self):
        t, c = self._files(
            "deep",
            {"a": {"b": {"c": "{{ leaf_val }}"}}},
            {"leaf_val": "42"},
        )
        result = _render_from_files(t, c)
        assert result["a"]["b"]["c"] == "42"

    def test_list_in_template_with_macro_elements_resolved(self):
        t, c = self._files(
            "list",
            {"servers": ["{{ host1 }}", "{{ host2 }}"]},
            {"host1": "host1.example.com", "host2": "host2.example.com"},
        )
        result = _render_from_files(t, c)
        assert isinstance(result["servers"], list)
        assert result["servers"][0] == "host1.example.com"
        assert result["servers"][1] == "host2.example.com"

    def test_multiline_string_in_template_value_collapses_to_single_line(self):
        # UC-CC-MR-2: when a multiline string is injected via {{ var }}, YAML single-quote
        # scalar normalization collapses internal newlines to spaces — multiline is NOT preserved.
        t = self.feature_dir / "template_multiline.yml"
        c = self.feature_dir / "ctx_multiline.yml"
        t.write_text("rendered_template: '{{ yaml_template }}'\n")
        _write_yaml(c, {"yaml_template": "line1\nline2\nline3\n"})
        result = _render_from_files(t, c)
        rendered = result["rendered_template"]
        assert "\n" not in rendered
        assert "line1" in rendered
        assert "line2" in rendered
        assert "line3" in rendered

    def test_string_concatenation_with_two_macros(self):
        t, c = self._files(
            "concat",
            {"address": "{{ host }}:{{ port }}"},
            {"host": "db.example.com", "port": 5432},
        )
        result = _render_from_files(t, c)
        assert result["address"] == "db.example.com:5432"

    def test_missing_complex_reference_does_not_raise(self):
        t, c = self._files(
            "missing_complex",
            {"cfg": "{{ missing_config }}", "host": "{{ db_host }}"},
            {"db_host": "db.example.com"},
        )
        result = _render_from_files(t, c)
        assert result.get("cfg") in (None, "", "None", {})
        assert result["host"] == "db.example.com"


# ---------------------------------------------------------------------------
# Backward compatibility — ansible-style syntax rewriting
# ---------------------------------------------------------------------------

class TestMacroBackwardCompatibility(BaseTest):
    """Backward compat: replace_ansible_stuff rewrites deprecated patterns before rendering."""

    def setup_method(self):
        self.feature_dir = self.output_dir / FEATURE_TEST_DIR / "compat"
        self.feature_dir.mkdir(parents=True, exist_ok=True)

    def test_underscore_variable_replaced_with_plain(self):
        # {{ _tenant }} → {{ tenant }} via replace_ansible_stuff.
        t = self.feature_dir / "template_underscore.yml"
        c = self.feature_dir / "ctx_underscore.yml"
        t.write_text("label: '{{ _tenant }}'\n")
        _write_yaml(c, {"tenant": "acme-corp"})
        result = _render_from_files(t, c)
        assert result["label"] == "acme-corp"

    def test_ansible_to_nice_yaml_filter_replaced_without_error(self):
        # ansible.builtin.to_nice_yaml → to_nice_yaml.
        t = self.feature_dir / "template_ansible.yml"
        c = self.feature_dir / "ctx_ansible.yml"
        t.write_text("output: '{{ data | ansible.builtin.to_nice_yaml }}'\n")
        _write_yaml(c, {"data": {"key": "value"}})
        ctx_vars = helper.openYaml(c)
        ctx = Context(**{k: v for k, v in ctx_vars.items() if v is not None})
        template = helper.openYaml(t)
        result = render_obj_by_context(template, ctx)
        assert "key" in str(result.get("output", ""))
