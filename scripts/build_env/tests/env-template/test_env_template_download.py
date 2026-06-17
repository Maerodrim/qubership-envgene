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

Python-level contracts tested here (no HTTP calls):
  parse_artifact_appver         — app:ver splitting + edge cases (UC-AD-ENV-13..24)
  parse_maven_coord_from_dd     — coordinates extraction from DD JSON (all new-logic UCs)
  extract_snapshot_version      — SNAPSHOT → timestamped version (UC-AD-ENV-23)
  validate_url                  — missing URL raises ValueError (UC-AD-ERR-3)
  getTemplateArtifactName       — artifact name extraction from env_definition (UC-AD-ENV-9..24)
  getAppDefinitionPath          — ArtDef file resolution (UC-AD-ERR-4)
  Application.model_validate    — ArtDef v1 parsing; resolve_auth plumbing (UC-AD-ENV-13..22)
  get_registry_creds            — credential extraction from cred_config (UC-AD-ENV-13..22)

AWS/GCP token exchange (UC-AD-ENV-21/22) requires cloud SDK calls —
not testable in pure Python unit tests. Verified by integration tests.
"""
import base64
import os
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

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

# ---------------------------------------------------------------------------
# Shared helpers
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
# parse_artifact_appver
# ---------------------------------------------------------------------------

class TestParseArtifactAppver(BaseTest):
    """
    UC-AD-ENV-13..24 — envTemplate.artifact must be "name:version" format.
    parse_artifact_appver splits it into [name, version].
    """

    def _env_def(self, appver: str) -> dict:
        return {"envTemplate": {"artifact": appver}}

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
        env_def = {"envTemplate": {"bgNsArtifacts": {"origin": "bg-template:3.0.0"}}}
        result = parse_artifact_appver(env_def, "envTemplate.bgNsArtifacts.origin")
        assert result == ["bg-template", "3.0.0"]

    def test_missing_attribute_returns_single_element_list(self):
        # Attribute not present at all → get_or_create returns "" → "".split(":") = [""].
        # Caller guards with `len(appver) >= 2 and bool(appver[0])`, so no crash.
        env_def = {"envTemplate": {}}
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
        env_def = {"envTemplate": {"artifact": ""}}
        with pytest.raises(ValueError, match="empty or missing"):
            parse_artifact_appver(env_def, "envTemplate.artifact")

    def test_none_artifact_value_silently_becomes_string_none(self):
        # BUG: artifact=None is coerced to str(None)="None" by get_or_create_nested_yaml_attribute.
        # The function does NOT raise — it returns ["None"] as the app name.
        # process_env_template will then try to open "None.yaml" from artifact_definitions/
        # and fail with FileNotFoundError, not a descriptive ValueError.
        env_def = {"envTemplate": {"artifact": None}}
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

    def test_standard_gav_extracted_correctly(self):
        g, a, v = parse_maven_coord_from_dd(_DD_JSON)
        assert g == "com.example.templates"
        assert a == "env-template-zip"
        assert v == "1.2.3"

    def test_snapshot_version_extracted_from_dd(self):
        # UC-AD-ENV-23: DD may contain timestamped SNAPSHOT version.
        dd = {
            "configurations": [{
                "artifacts": [{
                    "id": "org.qubership:templates:master-20251223.070533-16",
                }]
            }]
        }
        g, a, v = parse_maven_coord_from_dd(dd)
        assert g == "org.qubership"
        assert a == "templates"
        assert v == "master-20251223.070533-16"

    def test_group_id_with_multiple_dots(self):
        # group_id dots must not be confused with field separators.
        dd = {
            "configurations": [{
                "artifacts": [{
                    "id": "com.example.deep.group:my-artifact:2.0.0",
                }]
            }]
        }
        g, a, v = parse_maven_coord_from_dd(dd)
        assert g == "com.example.deep.group"
        assert a == "my-artifact"
        assert v == "2.0.0"

    def test_missing_id_field_raises(self):
        # artifact entry has no "id" key → .get() returns None → .split() raises.
        dd = {"configurations": [{"artifacts": [{}]}]}
        with pytest.raises((KeyError, TypeError, AttributeError)):
            parse_maven_coord_from_dd(dd)

    def test_id_with_two_parts_only_does_not_raise_inside_function(self):
        # BUG: parse_maven_coord_from_dd uses str.split(':') which returns a list of 2
        # elements for "group:artifact". The function itself does NOT raise — it returns
        # a 2-element list. The caller raises ValueError when it tries to unpack into
        # (g, a, v) = ...; that error message will be "not enough values to unpack",
        # which is unhelpful. This test documents the silent failure mode.
        dd = {"configurations": [{"artifacts": [{"id": "com.example:artifact"}]}]}
        result = parse_maven_coord_from_dd(dd)
        assert result == ["com.example", "artifact"]

    def test_empty_configurations_list_raises(self):
        dd = {"configurations": []}
        with pytest.raises((IndexError, KeyError)):
            parse_maven_coord_from_dd(dd)

    def test_missing_configurations_key_raises(self):
        # DD missing the "configurations" key entirely → KeyError.
        with pytest.raises(KeyError):
            parse_maven_coord_from_dd({})

    def test_empty_artifacts_list_raises(self):
        dd = {"configurations": [{"artifacts": []}]}
        with pytest.raises(IndexError):
            parse_maven_coord_from_dd(dd)


# ---------------------------------------------------------------------------
# extract_snapshot_version
# ---------------------------------------------------------------------------

class TestExtractSnapshotVersion(BaseTest):
    """
    UC-AD-ENV-23 — SNAPSHOT versions are resolved to timestamped filenames.
    extract_snapshot_version strips the path prefix from the URL and returns
    the versioned filename stem used downstream as resolved_version.
    """

    def test_standard_snapshot_version_extracted(self):
        url = "https://nexus.example.com/repo/org/qubership/templates/1.0.0-SNAPSHOT/templates-1.0.0-20251223.070533-16.json"
        result = extract_snapshot_version(url, "1.0.0-SNAPSHOT")
        assert result == "1.0.0-20251223.070533-16"

    def test_master_snapshot_version_extracted(self):
        # Real production URL shape from test fixtures.
        url = "https://artifactory.qubership.org/mvn.snapshot/org/qubership/qubership_envgene_templates/master-SNAPSHOT/qubership_envgene_templates-master-20251223.070533-16.json"
        result = extract_snapshot_version(url, "master-SNAPSHOT")
        assert result == "master-20251223.070533-16"

    def test_result_starts_with_base_version(self):
        # Resolved version always begins with the numeric part of the SNAPSHOT base.
        url = "https://nexus.example.com/repo/org/q/t/2.3.4-SNAPSHOT/t-2.3.4-20240101.120000-5.json"
        result = extract_snapshot_version(url, "2.3.4-SNAPSHOT")
        assert result.startswith("2.3.4-")

    def test_result_contains_timestamp(self):
        # The timestamp portion must be preserved verbatim.
        url = "https://nexus.example.com/repo/t/t/1.0-SNAPSHOT/t-1.0-20240615.093000-3.json"
        result = extract_snapshot_version(url, "1.0-SNAPSHOT")
        assert "20240615.093000" in result

    def test_base_not_found_in_filename_returns_whole_stem(self):
        # find() returns -1 when base is absent → name[-1:] = last char (silent wrong result).
        # This test documents the current (silent failure) behaviour so regressions are visible.
        url = "https://nexus.example.com/repo/completely-different-name.json"
        result = extract_snapshot_version(url, "1.0.0-SNAPSHOT")
        # Does NOT raise — but returns a nonsensical single character.
        assert len(result) == 1


# ---------------------------------------------------------------------------
# validate_url
# ---------------------------------------------------------------------------

class TestValidateUrl(BaseTest):
    """
    UC-AD-ERR-3 / UC-AD-ERR-4 — when artifact URL cannot be resolved,
    validate_url must raise ValueError with coordinates in the message.
    """

    def test_none_url_raises_value_error(self):
        with pytest.raises(ValueError, match="artifact not found"):
            validate_url(None, "com.example", "my-artifact", "1.0.0")

    def test_empty_string_url_raises_value_error(self):
        with pytest.raises(ValueError, match="artifact not found"):
            validate_url("", "com.example", "my-artifact", "1.0.0")

    def test_error_message_contains_all_coordinates(self):
        # All three coordinates must be present so operators can locate the artifact.
        with pytest.raises(ValueError) as exc_info:
            validate_url(None, "com.example", "my-artifact", "1.0.0")
        msg = str(exc_info.value)
        assert "com.example" in msg
        assert "my-artifact" in msg
        assert "1.0.0" in msg

    def test_valid_url_does_not_raise(self):
        validate_url("https://nexus.example.com/repo/artifact.zip", "g", "a", "v")


# ---------------------------------------------------------------------------
# getTemplateArtifactName
# ---------------------------------------------------------------------------

class TestGetTemplateArtifactName(BaseTest):
    """
    getTemplateArtifactName extracts the artifact application name from
    env_definition for both new (app:ver) and legacy (GAV templateArtifact) formats.
    """

    def test_new_format_returns_app_name(self):
        # UC-AD-ENV-13..24: "app:version" → returns "app".
        env_def = {"envTemplate": {"artifact": "deployment-configuration-env-templates:1.0.0"}}
        assert getTemplateArtifactName(env_def) == "deployment-configuration-env-templates"

    def test_new_format_takes_precedence_over_legacy(self):
        # "artifact" key present → use new logic; templateArtifact block is ignored.
        env_def = {
            "envTemplate": {
                "artifact": "new-template:2.0.0",
                "templateArtifact": {
                    "artifact": {"artifact_id": "old-template", "group_id": "g", "version": "1.0.0"}
                },
            }
        }
        assert getTemplateArtifactName(env_def) == "new-template"

    def test_legacy_format_returns_artifact_id(self):
        # UC-AD-ENV-9..12: templateArtifact.artifact.artifact_id used.
        env_def = {
            "envTemplate": {
                "templateArtifact": {
                    "artifact": {
                        "group_id": "org.qubership",
                        "artifact_id": "qubership_envgene_templates",
                        "version": "1.0.0",
                    }
                }
            }
        }
        assert getTemplateArtifactName(env_def) == "qubership_envgene_templates"

    def test_missing_env_template_key_raises(self):
        # envTemplate absent entirely → KeyError before any artifact logic runs.
        with pytest.raises(KeyError):
            getTemplateArtifactName({})

    def test_legacy_missing_artifact_id_raises(self):
        # artifact_id absent from GAV block → KeyError.
        env_def = {
            "envTemplate": {
                "templateArtifact": {
                    "artifact": {"group_id": "org.qubership", "version": "1.0.0"}
                }
            }
        }
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

    def test_returns_yaml_path_when_no_files_exist(self):
        # Neither .yaml nor .yml exist → returns .yaml candidate;
        # caller raises FileNotFoundError when it tries to open it.
        result = getAppDefinitionPath("/nonexistent/project", "env-template")
        assert result.endswith(".yaml")
        assert "configuration/artifact_definitions/env-template" in result.replace("\\", "/")

    def test_prefers_yml_over_yaml(self, tmp_path):
        artdef_dir = tmp_path / "configuration" / "artifact_definitions"
        artdef_dir.mkdir(parents=True)
        yml_file = artdef_dir / "env-template.yml"
        yml_file.write_text("name: env-template\n")
        assert Path(getAppDefinitionPath(str(tmp_path), "env-template")) == yml_file

    def test_falls_back_to_yaml_when_only_yaml_exists(self, tmp_path):
        artdef_dir = tmp_path / "configuration" / "artifact_definitions"
        artdef_dir.mkdir(parents=True)
        yaml_file = artdef_dir / "env-template.yaml"
        yaml_file.write_text("name: env-template\n")
        assert Path(getAppDefinitionPath(str(tmp_path), "env-template")) == yaml_file

    def test_different_template_names_produce_different_paths(self):
        path_a = getAppDefinitionPath("/base", "template-a")
        path_b = getAppDefinitionPath("/base", "template-b")
        assert path_a != path_b
        assert "template-a" in path_a
        assert "template-b" in path_b


# ---------------------------------------------------------------------------
# Application (ArtDef v1) model_validate + resolve_auth
# ---------------------------------------------------------------------------

class TestArtDefV1Application(BaseTest):
    """
    UC-AD-ENV-13..16 — ArtDef v1.0 is an Application model with inline registry.
    """

    def test_artdef_v1_parses_correctly(self):
        app = Application.model_validate(_ARTDEF_V1)
        assert app.name == "env-template"
        assert app.artifact_id == "env-template"
        assert app.group_id == "com.example.templates"
        assert isinstance(app.registry, Registry)

    def test_artdef_v1_registry_domain_name_normalised(self):
        # Trailing slash added even if absent — downstream URL construction depends on it.
        app = Application.model_validate(_ARTDEF_V1)
        assert app.registry.maven_config.repository_domain_name.endswith("/")

    def test_artdef_v1_anonymous_resolve_auth_returns_none(self):
        # UC-AD-ENV-14/16: no credentialsId → anonymous download, no auth header.
        artdef = {**_ARTDEF_V1, "registry": {**_ARTDEF_V1["registry"], "credentialsId": ""}}
        app = Application.model_validate(artdef)
        assert app.registry.resolve_auth({}) is None

    def test_artdef_v1_user_pass_resolve_auth_returns_basic(self):
        # UC-AD-ENV-13/15: credentialsId + matching env_creds → Basic auth.
        app = Application.model_validate(_ARTDEF_V1)
        headers = app.registry.resolve_auth(_CRED_CONFIG)
        token = base64.b64encode(b"ci-bot:s3cr3t").decode()
        assert headers == {"Authorization": f"Basic {token}"}

    def test_missing_group_id_raises_validation_error(self):
        artdef = {k: v for k, v in _ARTDEF_V1.items() if k != "groupId"}
        with pytest.raises(ValidationError):
            Application.model_validate(artdef)

    def test_missing_artifact_id_raises_validation_error(self):
        artdef = {k: v for k, v in _ARTDEF_V1.items() if k != "artifactId"}
        with pytest.raises(ValidationError):
            Application.model_validate(artdef)

    def test_missing_registry_raises_validation_error(self):
        artdef = {k: v for k, v in _ARTDEF_V1.items() if k != "registry"}
        with pytest.raises(ValidationError):
            Application.model_validate(artdef)


# ---------------------------------------------------------------------------
# get_registry_creds
# ---------------------------------------------------------------------------

class TestGetRegistryCreds(BaseTest):
    """
    get_registry_creds extracts Credentials from registry + cred_config.
    Used in resolve_artifact_old_logic (GAV / legacy path).
    """

    def _make_registry(self, credentials_id: str = "nexus-creds") -> Registry:
        return Registry.model_validate({
            "name": "nexus",
            "credentialsId": credentials_id,
            "mavenConfig": _MINIMAL_MAVEN,
        })

    def test_valid_creds_returns_credentials_object(self):
        reg = self._make_registry("nexus-creds")
        creds = get_registry_creds(reg, _CRED_CONFIG)
        assert creds is not None
        assert creds.username == "ci-bot"
        assert creds.password == "s3cr3t"

    def test_no_credentials_id_returns_none(self):
        # UC-AD-ENV-10/12: anonymous registry → None, no auth header sent.
        reg = self._make_registry(credentials_id="")
        assert get_registry_creds(reg, _CRED_CONFIG) is None

    def test_credential_key_not_in_cred_config_raises(self):
        # credentialsId references "nexus-creds" but it's absent from cred_config → KeyError.
        reg = self._make_registry("nexus-creds")
        with pytest.raises(KeyError):
            get_registry_creds(reg, {"other-creds": {"data": {"username": "u", "password": "p"}}})

    def test_missing_data_key_in_cred_entry_raises(self):
        # Credential entry exists but has no "data" sub-dict → KeyError/TypeError.
        reg = self._make_registry("nexus-creds")
        with pytest.raises((KeyError, TypeError)):
            get_registry_creds(reg, {"nexus-creds": {}})

    def test_missing_username_raises(self):
        reg = self._make_registry("nexus-creds")
        with pytest.raises(ValueError, match="credentials incomplete"):
            get_registry_creds(reg, {"nexus-creds": {"data": {"password": "s3cr3t"}}})

    def test_missing_password_raises(self):
        reg = self._make_registry("nexus-creds")
        with pytest.raises(ValueError, match="credentials incomplete"):
            get_registry_creds(reg, {"nexus-creds": {"data": {"username": "ci-bot"}}})
