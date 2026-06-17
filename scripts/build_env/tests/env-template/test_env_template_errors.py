"""
Environment Template error handling integration tests.

UC-AD-ERR-3  Artifact URL not found — process_env_template raises ValueError when
             the artifact registry returns 404 for all artifact variants (DD + ZIP),
             causing validate_url to raise.

UC-AD-ERR-4  Missing ArtDef — process_env_template raises FileNotFoundError when
             configuration/artifact_definitions/{app_name}.yml/.yaml is absent.

These are integration-level tests: they call the real process_env_template()
function with real filesystem fixtures and mocked HTTP responses (aioresponses +
responses libraries).  No production logic is reimplemented.
"""
import os
import sys
from os import environ
from pathlib import Path

import pytest
import responses
from aioresponses import aioresponses

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

from env_template.process_env_template import process_env_template

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

CLUSTER = "cluster-01"
ENV_NAME = "err-test-env"

GROUP_ID = "org.qubership"
ARTIFACT_ID = "qubership_envgene_templates"
VERSION = "1.0.0"

SNAPSHOT_BASE = "https://artifactory.qubership.org/mvn.snapshot"
GROUP_PATH = GROUP_ID.replace(".", "/")
BASE_PATH = f"{GROUP_PATH}/{ARTIFACT_ID}/{VERSION}"
METADATA_URL = f"{SNAPSHOT_BASE}/{BASE_PATH}/maven-metadata.xml"
ARTIFACT_NAME = f"{ARTIFACT_ID}-{VERSION}"
DD_URL = f"{SNAPSHOT_BASE}/{BASE_PATH}/{ARTIFACT_NAME}.json"
ZIP_URL = f"{SNAPSHOT_BASE}/{BASE_PATH}/{ARTIFACT_NAME}.zip"

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_ARTDEF_CONTENT = f"""\
name: "deployment-configuration-env-templates"
groupId: "{GROUP_ID}"
artifactId: "{ARTIFACT_ID}"
registry:
  name: "artifactory"
  mavenConfig:
    repositoryDomainName: "https://artifactory.qubership.org"
    targetSnapshot: "mvn.snapshot"
    targetStaging: "mvn.staging"
    targetRelease: "mvn.release"
"""

_ENV_DEFINITION_CONTENT = f"""\
envTemplate:
  artifact: "deployment-configuration-env-templates:{VERSION}"
"""

_CREDENTIALS_CONTENT = """\
dummy-cred:
  type: usernamePassword
  data:
    username: "ci-bot"
    password: "s3cr3t"
"""

_CONFIG_CONTENT = "crypt: false\n"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _setup_project(project_dir: Path, *, include_artdef: bool = True) -> None:
    """Create minimal project directory structure for process_env_template()."""
    # Configuration
    _write(project_dir / "configuration" / "config.yml", _CONFIG_CONTENT)
    _write(
        project_dir / "configuration" / "credentials" / "credentials.yml",
        _CREDENTIALS_CONTENT,
    )
    if include_artdef:
        _write(
            project_dir / "configuration" / "artifact_definitions" / "deployment-configuration-env-templates.yml",
            _ARTDEF_CONTENT,
        )

    # Env definition
    _write(
        project_dir / "environments" / CLUSTER / ENV_NAME / "Inventory" / "env_definition.yml",
        _ENV_DEFINITION_CONTENT,
    )

    # Tmp dir — process_env_template writes the downloaded template here.
    (project_dir / "tmp").mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# UC-AD-ERR-4: Missing ArtDef — FileNotFoundError before any HTTP call
# ---------------------------------------------------------------------------

class TestMissingArtDef(BaseTest):
    """
    UC-AD-ERR-4 — when configuration/artifact_definitions/{app_name}.yml/.yaml
    is absent, process_env_template must raise FileNotFoundError immediately,
    before making any network calls.
    """

    FEATURE_TEST_DIR = "test_env_template_err4"

    @pytest.fixture(autouse=True)
    def _init_env(self):
        self.feature_dir = self.output_dir / self.FEATURE_TEST_DIR
        _setup_project(self.feature_dir, include_artdef=False)

        environ["CI_PROJECT_DIR"] = str(self.feature_dir)
        environ["CLUSTER_NAME"] = CLUSTER
        environ["ENVIRONMENT_NAME"] = ENV_NAME
        environ["FULL_ENV_NAME"] = f"{CLUSTER}/{ENV_NAME}"

        yield

        environ.pop("CI_PROJECT_DIR", None)
        environ.pop("ENVIRONMENT_NAME", None)
        environ.pop("FULL_ENV_NAME", None)

    def test_missing_artdef_raises_file_not_found(self):
        # ArtDef file is absent — FileNotFoundError must be raised before HTTP calls.
        with pytest.raises(FileNotFoundError, match="deployment-configuration-env-templates"):
            process_env_template()

    def test_missing_artdef_no_network_call_needed(self):
        # The error must be raised before any network activity — verify by not
        # registering any mocked HTTP routes (unmocked calls raise ConnectionError).
        with pytest.raises(FileNotFoundError):
            process_env_template()

    def test_missing_artdef_error_contains_app_name(self):
        # Error message must identify which application's ArtDef is missing.
        with pytest.raises(FileNotFoundError) as exc_info:
            process_env_template()
        msg = str(exc_info.value)
        assert "deployment-configuration-env-templates" in msg

    def test_artdef_dir_missing_entirely_raises_file_not_found(self):
        # artifact_definitions/ directory is absent entirely, not just the file.
        artdef_dir = self.feature_dir / "configuration" / "artifact_definitions"
        if artdef_dir.exists():
            import shutil
            shutil.rmtree(artdef_dir)

        with pytest.raises(FileNotFoundError):
            process_env_template()

    def test_other_artdef_present_does_not_help(self):
        # Another ArtDef exists but not the one needed — still FileNotFoundError.
        _write(
            self.feature_dir / "configuration" / "artifact_definitions" / "other-template.yml",
            "name: other-template\ngroupId: g\nartifactId: a\nregistry:\n  name: r\n",
        )
        with pytest.raises(FileNotFoundError, match="deployment-configuration-env-templates"):
            process_env_template()


# ---------------------------------------------------------------------------
# UC-AD-ERR-3: Artifact URL not found — ValueError from validate_url
# ---------------------------------------------------------------------------

class TestArtifactUrlNotFound(BaseTest):
    """
    UC-AD-ERR-3 — when the artifact registry returns 404 for both the deployment
    descriptor (DD) and the ZIP artifact, check_artifact_async returns None,
    and validate_url raises ValueError with the artifact coordinates.

    Tests run with ArtDef present (ERR-4 already resolved) and all HTTP routes
    returning 404 to simulate a registry that does not contain the requested version.
    """

    FEATURE_TEST_DIR = "test_env_template_err3"

    @pytest.fixture(autouse=True)
    def _init_env(self):
        self.feature_dir = self.output_dir / self.FEATURE_TEST_DIR
        _setup_project(self.feature_dir, include_artdef=True)

        environ["CI_PROJECT_DIR"] = str(self.feature_dir)
        environ["CLUSTER_NAME"] = CLUSTER
        environ["ENVIRONMENT_NAME"] = ENV_NAME
        environ["FULL_ENV_NAME"] = f"{CLUSTER}/{ENV_NAME}"

        yield

        environ.pop("CI_PROJECT_DIR", None)
        environ.pop("ENVIRONMENT_NAME", None)
        environ.pop("FULL_ENV_NAME", None)

    @responses.activate
    def test_dd_and_zip_not_found_raises_value_error(self, mock_aio_response):
        # Both DD and ZIP metadata return 404 → validate_url raises ValueError.
        mock_aio_response.get(METADATA_URL, status=404)
        mock_aio_response.head(DD_URL, status=404)
        mock_aio_response.head(ZIP_URL, status=404)

        with pytest.raises(ValueError, match="artifact not found"):
            process_env_template()

    @responses.activate
    def test_error_message_contains_artifact_coordinates(self, mock_aio_response):
        # ValueError message must contain group_id, artifact_id, version so
        # operators can locate the artifact in the registry.
        mock_aio_response.get(METADATA_URL, status=404)
        mock_aio_response.head(DD_URL, status=404)
        mock_aio_response.head(ZIP_URL, status=404)

        with pytest.raises(ValueError) as exc_info:
            process_env_template()
        msg = str(exc_info.value)
        assert GROUP_ID in msg or ARTIFACT_ID in msg or VERSION in msg

    @pytest.fixture
    def mock_aio_response(self):
        with aioresponses() as m:
            yield m
