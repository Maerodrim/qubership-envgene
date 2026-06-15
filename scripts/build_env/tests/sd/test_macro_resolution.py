import os

from scripts.build_env.tests.base_test import BaseTest

os.environ.setdefault("ENVIRONMENT_NAME", "env-01")
os.environ.setdefault("CLUSTER_NAME", "cluster-01")

from render_config_env import Context, render_obj_by_context


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ctx(**kwargs) -> Context:
    return Context(**kwargs)


def _render(template: dict, **ctx_vars) -> dict:
    return render_obj_by_context(template, _ctx(**ctx_vars))


# ---------------------------------------------------------------------------
# UC-CC-MR-1: Simple type resolution
# ---------------------------------------------------------------------------

class TestMacroSimpleTypeResolution(BaseTest):
    """UC-CC-MR-1 — macro references preserve the type of the referenced value."""

    def test_integer_type_preserved(self):
        # UC-CC-MR-1: api_port: {{ server_port }} must resolve to int 8080, not string "8080".
        # Risk: Jinja2 renders everything to string by default; YAML re-parse must recover int.
        result = _render({"api_port": "{{ server_port }}"}, server_port=8080)
        assert result["api_port"] == 8080
        assert isinstance(result["api_port"], int)

    def test_boolean_true_not_converted_to_string(self):
        # UC-CC-MR-1: use_ssl: {{ ssl_enabled }} — Jinja2 renders True as "True",
        # but YAML must parse it back to bool, not leave it as the string "True".
        result = _render({"use_ssl": "{{ ssl_enabled }}"}, ssl_enabled=True)
        assert result["use_ssl"] is True
        assert isinstance(result["use_ssl"], bool)

    def test_boolean_false_not_converted_to_string(self):
        result = _render({"debug": "{{ debug_flag }}"}, debug_flag=False)
        assert result["debug"] is False
        assert isinstance(result["debug"], bool)

    def test_string_true_not_coerced_to_bool(self):
        # UC-CC-MR-1: log_level: {{ debug_mode }} where debug_mode = "true" (string).
        # Must stay a string — YAML must NOT auto-coerce "true" string to bool True.
        result = _render({"log_level": "{{ debug_mode }}"}, debug_mode="true")
        assert result["log_level"] == "true"
        assert isinstance(result["log_level"], str)

    def test_all_four_types_resolved_in_one_template(self):
        # UC-CC-MR-1 full scenario from documentation — all parameter kinds together.
        result = _render(
            {
                "api_port": "{{ server_port }}",
                "service_version": "{{ app_version }}",
                "use_ssl": "{{ ssl_enabled }}",
                "log_level": "{{ debug_mode }}",
            },
            server_port=8080,
            app_version="3.0",
            ssl_enabled=True,
            debug_mode="true",
        )
        assert result["api_port"] == 8080
        assert isinstance(result["api_port"], int)
        assert result["service_version"] == "3.0"
        assert result["use_ssl"] is True
        assert result["log_level"] == "true"

    def test_integer_zero_not_collapsed_to_none(self):
        # Edge: integer 0 is falsy in Python — must not become None or empty string.
        result = _render({"timeout": "{{ zero_val }}"}, zero_val=0)
        assert result["timeout"] == 0
        assert isinstance(result["timeout"], int)

    # ------------------------------------------------------------------
    # Negative
    # ------------------------------------------------------------------

    def test_missing_reference_renders_as_empty(self):
        # ChainableUndefined: undefined variable must not raise — renders to empty/None.
        result = _render({"key": "{{ nonexistent_var }}"})
        assert result.get("key") in (None, "", "None")

    def test_partial_string_with_defined_macro_substitutes_only_macro(self):
        # Macro embedded in a larger string — surrounding text must be preserved.
        result = _render({"url": "https://{{ host }}/api"}, host="example.com")
        assert result["url"] == "https://example.com/api"

    def test_partial_string_with_missing_macro_preserves_surrounding_text(self):
        # Undefined macro renders to empty string; the rest of the string stays intact.
        result = _render({"url": "prefix-{{ missing }}-suffix"})
        assert "prefix" in str(result.get("url", ""))
        assert "suffix" in str(result.get("url", ""))


# ---------------------------------------------------------------------------
# UC-CC-MR-2: Complex structure resolution
# ---------------------------------------------------------------------------

class TestMacroComplexStructureResolution(BaseTest):
    """UC-CC-MR-2 — macro references to nested dicts and multiline strings."""

    def test_nested_dict_reference_resolved(self):
        # UC-CC-MR-2: api_config: {{ database_config }} — full nested mapping preserved.
        database_config = {"connection": {"host": "db.example.com", "port": 5432}}
        result = _render({"api_config": "{{ database_config }}"}, database_config=database_config)
        assert result["api_config"]["connection"]["host"] == "db.example.com"
        assert result["api_config"]["connection"]["port"] == 5432

    def test_nested_dict_inner_types_preserved(self):
        # UC-CC-MR-2: integer and boolean inside the nested dict must survive round-trip.
        db_cfg = {"port": 5432, "ssl": True}
        result = _render({"cfg": "{{ db_cfg }}"}, db_cfg=db_cfg)
        assert isinstance(result["cfg"]["port"], int)
        assert result["cfg"]["ssl"] is True

    def test_deeply_nested_dict_all_levels_preserved(self):
        # Three levels of nesting — ensures recursive resolution doesn't drop inner levels.
        deep = {"a": {"b": {"c": 42}}}
        result = _render({"ref": "{{ deep }}"}, deep=deep)
        assert result["ref"]["a"]["b"]["c"] == 42

    def test_list_reference_stays_list_not_string(self):
        # A referenced list must remain a list, not be stringified.
        hosts = ["host1.example.com", "host2.example.com"]
        result = _render({"servers": "{{ hosts }}"}, hosts=hosts)
        assert result["servers"] == hosts
        assert isinstance(result["servers"], list)

    def test_multiline_string_reference_resolved(self):
        # UC-CC-MR-2: rendered_template: {{ yaml_template }} — literal block scalar preserved.
        yaml_template = (
            "services:\n"
            "  api:\n"
            "    image: api:latest\n"
            "    ports:\n"
            "      - 8080:8080\n"
        )
        result = _render({"rendered_template": "{{ yaml_template }}"}, yaml_template=yaml_template)
        assert result["rendered_template"] == yaml_template

    def test_string_concatenation_with_two_macros(self):
        # {{ host }}:{{ port }} — both macros substituted; result is a single string value.
        result = _render({"address": "{{ host }}:{{ port }}"}, host="db.example.com", port=5432)
        assert result["address"] == "db.example.com:5432"

    # ------------------------------------------------------------------
    # Negative
    # ------------------------------------------------------------------

    def test_missing_complex_reference_does_not_raise(self):
        # ChainableUndefined: missing variable in complex template context must not raise.
        result = _render({"cfg": "{{ missing_config }}"})
        assert result.get("cfg") in (None, "", "None", {})


# ---------------------------------------------------------------------------
# Backward compatibility — ansible-style syntax rewriting
# ---------------------------------------------------------------------------

class TestMacroBackwardCompatibility(BaseTest):
    """Backward compat: replace_ansible_stuff rewrites deprecated patterns before rendering."""

    def test_underscore_variable_replaced_with_plain(self):
        # {{ _tenant }} → {{ tenant }} via replace_ansible_stuff.
        # Without the rewrite, _tenant would be undefined and render to empty string.
        result = _render({"label": "{{ _tenant }}"}, tenant="acme-corp")
        assert result["label"] == "acme-corp"

    def test_ansible_to_nice_yaml_filter_replaced_without_error(self):
        # ansible.builtin.to_nice_yaml → to_nice_yaml.
        # Must not raise TemplateError after replacement.
        result = render_obj_by_context(
            {"output": "{{ data | ansible.builtin.to_nice_yaml }}"},
            _ctx(data={"key": "value"}),
        )
        assert "key" in str(result.get("output", ""))
