"""
Environment Template Artifact Download tests.

UC-AD-ENV-9..24 specify how the pipeline downloads Environment Template
artifacts from registries using GAV notation or app:ver notation.

What is already covered by test_env_template.py (integration tests with
mocked HTTP):
  - test_new_logic_with_dd     — app:ver + ArtDef v1, SNAPSHOT, DD resolves ZIP
  - test_new_logic_with_zip    — app:ver + ArtDef v1, SNAPSHOT, no DD → ZIP direct
  - test_old_logic_with_dd     — GAV (templateArtifact) legacy, SNAPSHOT, DD found
  - test_old_logic_with_zip    — GAV (templateArtifact) legacy, SNAPSHOT, no DD

Integration pattern: every test writes its input data into YAML/JSON files
under output_dir/test_env_template_download/, reads them back via openYaml /
json.loads, and passes the result to the real production function.  This
mirrors the data flow at runtime: env_definition.yml → openYaml →
parse_artifact_appver / getTemplateArtifactName / getAppDefinitionPath →
ArtDef YAML → Application.model_validate.
"""
import base64
import json
import os
import sys
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

import envgenehelper as helper
from scripts.build_env.tests.base_test import BaseTest

os.environ.setdefault("ENVIRONMENT_NAME", "env-01")
os.environ.setdefault("CLUSTER_NAME", "cluster-01")

_BUILD_ENV = Path(__file__).resolve().parents[2]
if str(_BUILD_ENV) not in sys.path:
    sys.path.insert(0, str(_BUILD_ENV))

_ARTIFACT_SEARCHER = Path(__file__).resolve().parents[4] / "python" / "artifact-searcher"
if str(_ARTIFACT_SEARCHER) not in sys.path:
    sys.path.insert(0, str(_ARTIFACT_SEARCHER))

_ENVGENE = Path(__file__).resolve().parents[4] / "python" / "envgene"
if str(_ENVGENE) not in sys.path:
    sys.path.insert(0, str(_ENVGENE))

from artifact_searcher.utils.models import Application, Registry
from env_template.process_env_template import (
    parse_artifact_appver,
    parse_maven_coord_from_dd,
    extract_snapshot_version,
    validate_url,
    get_registry_creds,
)
from envgenehelper.business_helper import getTemplateArtifactName, getAppDefinitionPath

FEATURE_TEST_DIR = "test_env_template_download"

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

_MINIMAL_MAVEN = {
    "targetSnapshot": "snap",
    "targetStaging": "staging",
    "targetRelease": "release",
    "repositoryDomainName": "https://nexus.example.com/repository/maven/",
}

_ARTDEF_V1 = {
    "name": "env-template",
    "groupId": "com.example.templates",
    "artifactId": "env-template",
    "registry": {
        "name": "nexus",
        "credentialsId": "nexus-creds",
        "mavenConfig": _MINIMAL_MAVEN,
    },
}

_CRED_CONFIG = {
    "nexus-creds": {
        "data": {
            "username": "ci-bot",
            "password": "s3cr3t",
        }
    }
}

_DD_JSON = {
    "configurations": [{
        "artifacts": [{
            "id": "com.example.templates:env-template-zip:1.2.3",
            "type": "zip",
            "classifier": "",
        }],
        "maven_repository": "https://nexus.example.com/repository/releases/",
    }]
}

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _write_yaml(path: Path, content: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(content, default_flow_style=False, allow_unicode=True))


def _write_json(path: Path, content: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(content, ensure_ascii=False))


# ---------------------------------------------------------------------------
# parse_artifact_appver
# ---------------------------------------------------------------------------

class TestParseArtifactAppver(BaseTest):
    """
    UC-AD-ENV-13..24 — envTemplate.artifact must be "name:version" format.
    parse_artifact_appver splits it into [name, version].
    """

    def setup_method(self):
        self.feature_dir = self.output_dir / FEATURE_TEST_DIR / "parse_artifact_appver"
        self.feature_dir.mkdir(parents=True, exist_ok=True)

    def _env_def(self, appver) -> dict:
        path = self.feature_dir / f"env_def_{abs(hash(str(appver)))}.yml"
        _write_yaml(path, {"envTemplate": {"artifact": appver}})
        return helper.openYaml(path)

    def test_standard_release_version_split(self):
        result = parse_artifact_appver(self._env_def("env-template:1.2.3"), "envTemplate.artifact")
        assert result == ["env-template", "1.2.3"]

    def test_snapshot_version_split(self):
        # UC-AD-ENV-23: SNAPSHOT is allowed for templates (unlike SD artifacts).
        result = parse_artifact_appver(self._env_def("env-template:1.0.0-SNAPSHOT"), "envTemplate.artifact")
        assert result == ["env-template", "1.0.0-SNAPSHOT"]

    def test_master_snapshot_split(self):
        # Real production value used in test fixtures.
        result = parse_artifact_appver(self._env_def("env-template:master-SNAPSHOT"), "envTemplate.artifact")
        assert result == ["env-template", "master-SNAPSHOT"]

    def test_app_name_with_hyphens_split_correctly(self):
        result = parse_artifact_appver(
            self._env_def("deployment-configuration-env-templates:2.0.0"),
            "envTemplate.artifact"
        )
        assert result == ["deployment-configuration-env-templates", "2.0.0"]

    def test_nested_bg_ns_artifact_origin_split(self):
        # Blue/Green namespace artifact for origin role.
        path = self.feature_dir / "env_def_bg.yml"
        _write_yaml(path, {"envTemplate": {"bgNsArtifacts": {"origin": "bg-template:3.0.0"}}})
        env_def = helper.openYaml(path)
        result = parse_artifact_appver(env_def, "envTemplate.bgNsArtifacts.origin")
        assert result == ["bg-template", "3.0.0"]

    def test_missing_attribute_returns_single_element_list(self):
        # Attribute not present at all → get_or_create returns "" → "".split(":") = [""].
        # Caller guards with `len(appver) >= 2 and bool(appver[0])`, so no crash.
        path = self.feature_dir / "env_def_missing.yml"
        _write_yaml(path, {"envTemplate": {}})
        env_def = helper.openYaml(path)
        result = parse_artifact_appver(env_def, "envTemplate.artifact")
        assert result == [""]

    def test_value_without_colon_returns_single_element_list(self):
        # "app-name" without ":" → [app-name]; caller checks len < 2 and falls back
        # to legacy GAV logic (process_env_template line 191).
        result = parse_artifact_appver(self._env_def("env-template"), "envTemplate.artifact")
        assert result == ["env-template"]
        assert len(result) == 1

    def test_empty_artifact_value_raises(self):
        # Attribute present but empty string → ValueError, not silent empty list.
        path = self.feature_dir / "env_def_empty.yml"
        path.write_text("envTemplate:\n  artifact: ''\n")
        env_def = helper.openYaml(path)
        with pytest.raises(ValueError, match="empty or missing"):
            parse_artifact_appver(env_def, "envTemplate.artifact")

    def test_none_artifact_value_silently_becomes_string_none(self):
        # BUG: artifact=None is coerced to str(None)="None" by get_or_create_nested_yaml_attribute.
        # The function does NOT raise — it returns ["None"] as the app name.
        # process_env_template will then try to open "None.yaml" from artifact_definitions/
        # and fail with FileNotFoundError, not a descriptive ValueError.
        path = self.feature_dir / "env_def_null.yml"
        path.write_text("envTemplate:\n  artifact: null\n")
        env_def = helper.openYaml(path)
        result = parse_artifact_appver(env_def, "envTemplate.artifact")
        assert result == ["None"]


# ---------------------------------------------------------------------------
# parse_maven_coord_from_dd
# ---------------------------------------------------------------------------

class TestParseMavenCoordFromDD(BaseTest):
    """
    UC-AD-ENV-13..20 (new-logic path) — deployment descriptor JSON contains
    Maven GAV in configurations[0].artifacts[0].id as "group:artifact:version".
    """

    def setup_method(self):
        self.feature_dir = self.output_dir / FEATURE_TEST_DIR / "parse_maven_coord"
        self.feature_dir.mkdir(parents=True, exist_ok=True)

    def _dd(self, content: dict) -> dict:
        path = self.feature_dir / f"dd_{abs(hash(str(content)))}.json"
        _write_json(path, content)
        return json.loads(path.read_text())

    def test_standard_gav_extracted_correctly(self):
        g, a, v = parse_maven_coord_from_dd(self._dd(_DD_JSON))
        assert g == "com.example.templates"
        assert a == "env-template-zip"
        assert v == "1.2.3"

    def test_snapshot_version_extracted_from_dd(self):
        # UC-AD-ENV-23: DD may contain timestamped SNAPSHOT version.
        dd = {"configurations": [{"artifacts": [{"id": "org.qubership:templates:master-20251223.070533-16"}]}]}
        g, a, v = parse_maven_coord_from_dd(self._dd(dd))
        assert g == "org.qubership"
        assert a == "templates"
        assert v == "master-20251223.070533-16"

    def test_group_id_with_multiple_dots(self):
        dd = {"configurations": [{"artifacts": [{"id": "com.example.deep.group:my-artifact:2.0.0"}]}]}
        g, a, v = parse_maven_coord_from_dd(self._dd(dd))
        assert g == "com.example.deep.group"
        assert a == "my-artifact"
        assert v == "2.0.0"

    def test_missing_id_field_raises(self):
        # artifact entry has no "id" key → .get() returns None → .split() raises.
        dd = {"configurations": [{"artifacts": [{}]}]}
        with pytest.raises((KeyError, TypeError, AttributeError)):
            parse_maven_coord_from_dd(self._dd(dd))

    def test_id_with_two_parts_only_does_not_raise_inside_function(self):
        # BUG: parse_maven_coord_from_dd uses str.split(':') which returns a list of 2
        # elements for "group:artifact". The function itself does NOT raise — it returns
        # a 2-element list. The caller raises ValueError when it tries to unpack into
        # (g, a, v) = ...; that error message will be "not enough values to unpack",
        # which is unhelpful. This test documents the silent failure mode.
        dd = {"configurations": [{"artifacts": [{"id": "com.example:artifact"}]}]}
        result = parse_maven_coord_from_dd(self._dd(dd))
        assert result == ["com.example", "artifact"]

    def test_empty_configurations_list_raises(self):
        dd = {"configurations": []}
        with pytest.raises((IndexError, KeyError)):
            parse_maven_coord_from_dd(self._dd(dd))

    def test_missing_configurations_key_raises(self):
        with pytest.raises(KeyError):
            parse_maven_coord_from_dd(self._dd({}))

    def test_empty_artifacts_list_raises(self):
        dd = {"configurations": [{"artifacts": []}]}
        with pytest.raises(IndexError):
            parse_maven_coord_from_dd(self._dd(dd))


# ---------------------------------------------------------------------------
# extract_snapshot_version
# ---------------------------------------------------------------------------

class TestExtractSnapshotVersion(BaseTest):
    """
    UC-AD-ENV-23 — SNAPSHOT versions are resolved to timestamped filenames.
    extract_snapshot_version strips the path prefix from the URL and returns
    the versioned filename stem used downstream as resolved_version.

    The URL comes from an HTTP response header; it is stored in a JSON file to
    represent the parsed artifact info object returned by check_artifact_async.
    """

    def setup_method(self):
        self.feature_dir = self.output_dir / FEATURE_TEST_DIR / "extract_snapshot"
        self.feature_dir.mkdir(parents=True, exist_ok=True)

    def _artifact_info(self, url: str, snapshot_version: str) -> tuple[str, str]:
        path = self.feature_dir / f"artifact_info_{abs(hash(url))}.json"
        _write_json(path, {"url": url, "snapshotVersion": snapshot_version})
        data = json.loads(path.read_text())
        return data["url"], data["snapshotVersion"]

    def test_standard_snapshot_version_extracted(self):
        url, ver = self._artifact_info(
            "https://nexus.example.com/repo/org/qubership/templates/1.0.0-SNAPSHOT/templates-1.0.0-20251223.070533-16.json",
            "1.0.0-SNAPSHOT",
        )
        assert extract_snapshot_version(url, ver) == "1.0.0-20251223.070533-16"

    def test_master_snapshot_version_extracted(self):
        url, ver = self._artifact_info(
            "https://artifactory.qubership.org/mvn.snapshot/org/qubership/qubership_envgene_templates/master-SNAPSHOT/qubership_envgene_templates-master-20251223.070533-16.json",
            "master-SNAPSHOT",
        )
        assert extract_snapshot_version(url, ver) == "master-20251223.070533-16"

    def test_result_starts_with_base_version(self):
        url, ver = self._artifact_info(
            "https://nexus.example.com/repo/org/q/t/2.3.4-SNAPSHOT/t-2.3.4-20240101.120000-5.json",
            "2.3.4-SNAPSHOT",
        )
        assert extract_snapshot_version(url, ver).startswith("2.3.4-")

    def test_result_contains_timestamp(self):
        url, ver = self._artifact_info(
            "https://nexus.example.com/repo/t/t/1.0-SNAPSHOT/t-1.0-20240615.093000-3.json",
            "1.0-SNAPSHOT",
        )
        assert "20240615.093000" in extract_snapshot_version(url, ver)

    def test_base_not_found_in_filename_returns_whole_stem(self):
        # find() returns -1 when base is absent → name[-1:] = last char (silent wrong result).
        # This test documents the current (silent failure) behaviour so regressions are visible.
        url, ver = self._artifact_info(
            "https://nexus.example.com/repo/completely-different-name.json",
            "1.0.0-SNAPSHOT",
        )
        result = extract_snapshot_version(url, ver)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# validate_url
# ---------------------------------------------------------------------------

class TestValidateUrl(BaseTest):
    """
    UC-AD-ERR-3 / UC-AD-ERR-4 — when artifact URL cannot be resolved,
    validate_url must raise ValueError with coordinates in the message.

    Coordinates come from the DD JSON; they are stored in a file to represent
    the parsed deployment descriptor returned by check_artifact_async.
    """

    def setup_method(self):
        self.feature_dir = self.output_dir / FEATURE_TEST_DIR / "validate_url"
        self.feature_dir.mkdir(parents=True, exist_ok=True)

    def _coords(self, url, group_id: str, artifact_id: str, version: str) -> tuple:
        path = self.feature_dir / "coords.json"
        _write_json(path, {"url": url, "groupId": group_id, "artifactId": artifact_id, "version": version})
        d = json.loads(path.read_text())
        return d["url"], d["groupId"], d["artifactId"], d["version"]

    def test_none_url_raises_value_error(self):
        # url=null is stored as JSON null → parsed back as None
        path = self.feature_dir / "coords_null.json"
        _write_json(path, {"url": None, "groupId": "com.example", "artifactId": "my-artifact", "version": "1.0.0"})
        d = json.loads(path.read_text())
        with pytest.raises(ValueError, match="artifact not found"):
            validate_url(d["url"], d["groupId"], d["artifactId"], d["version"])

    def test_empty_string_url_raises_value_error(self):
        url, g, a, v = self._coords("", "com.example", "my-artifact", "1.0.0")
        with pytest.raises(ValueError, match="artifact not found"):
            validate_url(url, g, a, v)

    def test_error_message_contains_all_coordinates(self):
        # All three coordinates must be present so operators can locate the artifact.
        path = self.feature_dir / "coords_null2.json"
        _write_json(path, {"url": None, "groupId": "com.example", "artifactId": "my-artifact", "version": "1.0.0"})
        d = json.loads(path.read_text())
        with pytest.raises(ValueError) as exc_info:
            validate_url(d["url"], d["groupId"], d["artifactId"], d["version"])
        msg = str(exc_info.value)
        assert "com.example" in msg
        assert "my-artifact" in msg
        assert "1.0.0" in msg

    def test_valid_url_does_not_raise(self):
        url, g, a, v = self._coords("https://nexus.example.com/repo/artifact.zip", "g", "a", "v")
        validate_url(url, g, a, v)


# ---------------------------------------------------------------------------
# getTemplateArtifactName
# ---------------------------------------------------------------------------

class TestGetTemplateArtifactName(BaseTest):
    """
    getTemplateArtifactName extracts the artifact application name from
    env_definition for both new (app:ver) and legacy (GAV templateArtifact) formats.
    """

    def setup_method(self):
        self.feature_dir = self.output_dir / FEATURE_TEST_DIR / "get_template_artifact_name"
        self.feature_dir.mkdir(parents=True, exist_ok=True)

    def _env_def(self, content: dict, filename: str) -> dict:
        path = self.feature_dir / filename
        _write_yaml(path, content)
        return helper.openYaml(path)

    def test_new_format_returns_app_name(self):
        # UC-AD-ENV-13..24: "app:version" → returns "app".
        env_def = self._env_def(
            {"envTemplate": {"artifact": "deployment-configuration-env-templates:1.0.0"}},
            "env_def_new.yml",
        )
        assert getTemplateArtifactName(env_def) == "deployment-configuration-env-templates"

    def test_new_format_takes_precedence_over_legacy(self):
        env_def = self._env_def(
            {
                "envTemplate": {
                    "artifact": "new-template:2.0.0",
                    "templateArtifact": {
                        "artifact": {"artifact_id": "old-template", "group_id": "g", "version": "1.0.0"}
                    },
                }
            },
            "env_def_both.yml",
        )
        assert getTemplateArtifactName(env_def) == "new-template"

    def test_legacy_format_returns_artifact_id(self):
        # UC-AD-ENV-9..12: templateArtifact.artifact.artifact_id used.
        env_def = self._env_def(
            {
                "envTemplate": {
                    "templateArtifact": {
                        "artifact": {
                            "group_id": "org.qubership",
                            "artifact_id": "qubership_envgene_templates",
                            "version": "1.0.0",
                        }
                    }
                }
            },
            "env_def_legacy.yml",
        )
        assert getTemplateArtifactName(env_def) == "qubership_envgene_templates"

    def test_missing_env_template_key_raises(self):
        env_def = self._env_def({}, "env_def_empty.yml")
        with pytest.raises(KeyError):
            getTemplateArtifactName(env_def)

    def test_legacy_missing_artifact_id_raises(self):
        env_def = self._env_def(
            {
                "envTemplate": {
                    "templateArtifact": {
                        "artifact": {"group_id": "org.qubership", "version": "1.0.0"}
                    }
                }
            },
            "env_def_no_artifact_id.yml",
        )
        with pytest.raises(KeyError):
            getTemplateArtifactName(env_def)


# ---------------------------------------------------------------------------
# getAppDefinitionPath
# ---------------------------------------------------------------------------

class TestGetAppDefinitionPath(BaseTest):
    """
    UC-AD-ENV-13..24 — ArtDef file must be found at
    {base}/configuration/artifact_definitions/{name}.yaml or .yml.
    UC-AD-ERR-4 — missing ArtDef → FileNotFoundError in process_env_template.
    """

    def setup_method(self):
        self.feature_dir = self.output_dir / FEATURE_TEST_DIR / "get_app_def_path"
        self.feature_dir.mkdir(parents=True, exist_ok=True)

    def test_returns_yaml_path_when_no_files_exist(self):
        # Neither .yaml nor .yml exist → returns .yaml candidate;
        # caller raises FileNotFoundError when it tries to open it.
        result = getAppDefinitionPath(str(self.feature_dir / "empty_project"), "env-template")
        assert result.endswith(".yaml")
        assert "configuration/artifact_definitions/env-template" in result.replace("\\", "/")

    def test_prefers_yml_over_yaml(self):
        project_dir = self.feature_dir / "project_yml"
        artdef_dir = project_dir / "configuration" / "artifact_definitions"
        artdef_dir.mkdir(parents=True, exist_ok=True)
        yml_file = artdef_dir / "env-template.yml"
        _write_yaml(yml_file, {"name": "env-template", "groupId": "g", "artifactId": "a"})
        assert Path(getAppDefinitionPath(str(project_dir), "env-template")) == yml_file

    def test_falls_back_to_yaml_when_only_yaml_exists(self):
        project_dir = self.feature_dir / "project_yaml"
        artdef_dir = project_dir / "configuration" / "artifact_definitions"
        artdef_dir.mkdir(parents=True, exist_ok=True)
        yaml_file = artdef_dir / "env-template.yaml"
        _write_yaml(yaml_file, {"name": "env-template", "groupId": "g", "artifactId": "a"})
        assert Path(getAppDefinitionPath(str(project_dir), "env-template")) == yaml_file

    def test_when_both_extensions_exist_yml_wins(self):
        project_dir = self.feature_dir / "project_both"
        artdef_dir = project_dir / "configuration" / "artifact_definitions"
        artdef_dir.mkdir(parents=True, exist_ok=True)
        yml_file = artdef_dir / "env-template.yml"
        yaml_file = artdef_dir / "env-template.yaml"
        _write_yaml(yml_file, {"name": "env-template-yml"})
        _write_yaml(yaml_file, {"name": "env-template-yaml"})
        assert Path(getAppDefinitionPath(str(project_dir), "env-template")) == yml_file


# ---------------------------------------------------------------------------
# Application (ArtDef v1) model_validate + resolve_auth
# ---------------------------------------------------------------------------

class TestArtDefV1Application(BaseTest):
    """
    UC-AD-ENV-13..16 — ArtDef v1.0 is an Application model with inline registry.
    The ArtDef YAML is read via openYaml, then passed to Application.model_validate
    — the same path as in process_env_template().
    """

    def setup_method(self):
        self.feature_dir = self.output_dir / FEATURE_TEST_DIR / "artdef_v1"
        self.feature_dir.mkdir(parents=True, exist_ok=True)

    def _artdef(self, content: dict, filename: str = "artdef.yml") -> Application:
        path = self.feature_dir / filename
        _write_yaml(path, content)
        return Application.model_validate(helper.openYaml(path))

    def test_artdef_v1_parses_correctly(self):
        app = self._artdef(_ARTDEF_V1)
        assert app.name == "env-template"
        assert app.artifact_id == "env-template"
        assert app.group_id == "com.example.templates"
        assert isinstance(app.registry, Registry)

    def test_artdef_v1_registry_domain_name_normalised(self):
        # Trailing slash added even if absent — downstream URL construction depends on it.
        artdef = dict(_ARTDEF_V1)
        artdef["registry"] = dict(_ARTDEF_V1["registry"])
        artdef["registry"]["mavenConfig"] = {
            **_MINIMAL_MAVEN,
            "repositoryDomainName": "https://nexus.example.com/repository/maven",
        }
        app = self._artdef(artdef, "artdef_no_slash.yml")
        assert app.registry.maven_config.repository_domain_name.endswith("/")

    def test_artdef_v1_anonymous_resolve_auth_returns_none(self):
        # UC-AD-ENV-14/16: no credentialsId → anonymous download, no auth header.
        artdef = dict(_ARTDEF_V1)
        artdef["registry"] = {**_ARTDEF_V1["registry"], "credentialsId": ""}
        app = self._artdef(artdef, "artdef_anon.yml")
        assert app.registry.resolve_auth({}) is None

    def test_artdef_v1_user_pass_resolve_auth_returns_basic(self):
        # UC-AD-ENV-13/15: credentialsId + matching env_creds → Basic auth.
        app = self._artdef(_ARTDEF_V1, "artdef_auth.yml")
        headers = app.registry.resolve_auth(_CRED_CONFIG)
        token = base64.b64encode(b"ci-bot:s3cr3t").decode()
        assert headers == {"Authorization": f"Basic {token}"}

    def test_missing_group_id_raises_validation_error(self):
        artdef = {k: v for k, v in _ARTDEF_V1.items() if k != "groupId"}
        path = self.feature_dir / "artdef_no_group.yml"
        _write_yaml(path, artdef)
        with pytest.raises(ValidationError):
            Application.model_validate(helper.openYaml(path))

    def test_missing_artifact_id_raises_validation_error(self):
        artdef = {k: v for k, v in _ARTDEF_V1.items() if k != "artifactId"}
        path = self.feature_dir / "artdef_no_artifact.yml"
        _write_yaml(path, artdef)
        with pytest.raises(ValidationError):
            Application.model_validate(helper.openYaml(path))

    def test_missing_registry_raises_validation_error(self):
        artdef = {k: v for k, v in _ARTDEF_V1.items() if k != "registry"}
        path = self.feature_dir / "artdef_no_registry.yml"
        _write_yaml(path, artdef)
        with pytest.raises(ValidationError):
            Application.model_validate(helper.openYaml(path))


# ---------------------------------------------------------------------------
# get_registry_creds
# ---------------------------------------------------------------------------

class TestGetRegistryCreds(BaseTest):
    """
    get_registry_creds extracts Credentials from registry + cred_config.
    Used in resolve_artifact_old_logic (GAV / legacy path).

    RegDef is read from a YAML file; cred_config is read from a credentials
    YAML — the same files that render_creds() decrypts at runtime.
    """

    def setup_method(self):
        self.feature_dir = self.output_dir / FEATURE_TEST_DIR / "get_registry_creds"
        self.feature_dir.mkdir(parents=True, exist_ok=True)

    def _make_registry(self, credentials_id: str = "nexus-creds") -> Registry:
        data = {
            "name": "nexus",
            "credentialsId": credentials_id,
            "mavenConfig": _MINIMAL_MAVEN,
        }
        path = self.feature_dir / f"regdef_{credentials_id or 'anon'}.yml"
        _write_yaml(path, data)
        return Registry.model_validate(helper.openYaml(path))

    def _creds(self, content: dict, filename: str = "credentials.yml") -> dict:
        path = self.feature_dir / filename
        _write_yaml(path, content)
        return helper.openYaml(path)

    def test_valid_creds_returns_credentials_object(self):
        reg = self._make_registry("nexus-creds")
        creds = get_registry_creds(reg, self._creds(_CRED_CONFIG))
        assert creds is not None
        assert creds.username == "ci-bot"
        assert creds.password == "s3cr3t"

    def test_no_credentials_id_returns_none(self):
        # UC-AD-ENV-10/12: anonymous registry → None, no auth header sent.
        reg = self._make_registry(credentials_id="")
        assert get_registry_creds(reg, self._creds(_CRED_CONFIG)) is None

    def test_credential_key_not_in_cred_config_raises(self):
        # credentialsId references "nexus-creds" but it's absent from cred_config → KeyError.
        reg = self._make_registry("nexus-creds")
        other_creds = self._creds(
            {"other-creds": {"data": {"username": "u", "password": "p"}}},
            "credentials_other.yml",
        )
        with pytest.raises(KeyError):
            get_registry_creds(reg, other_creds)

    def test_missing_data_key_in_cred_entry_raises(self):
        # Credential entry exists but has no "data" sub-dict → KeyError/TypeError.
        reg = self._make_registry("nexus-creds")
        bad_creds = self._creds({"nexus-creds": {}}, "credentials_no_data.yml")
        with pytest.raises((KeyError, TypeError)):
            get_registry_creds(reg, bad_creds)

    def test_missing_username_raises(self):
        reg = self._make_registry("nexus-creds")
        creds = self._creds(
            {"nexus-creds": {"data": {"password": "s3cr3t"}}},
            "credentials_no_user.yml",
        )
        with pytest.raises(ValueError, match="credentials incomplete"):
            get_registry_creds(reg, creds)

    def test_missing_password_raises(self):
        reg = self._make_registry("nexus-creds")
        creds = self._creds(
            {"nexus-creds": {"data": {"username": "ci-bot"}}},
            "credentials_no_pass.yml",
        )
        with pytest.raises(ValueError, match="credentials incomplete"):
            get_registry_creds(reg, creds)
