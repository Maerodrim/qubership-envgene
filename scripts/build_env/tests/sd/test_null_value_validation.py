import logging
import os
import shutil
from pathlib import Path

import pytest

from envgenehelper import validate_parameters
from envgenehelper.creds_helper import validate_creds
from envgenehelper.errors import ValidationError
from envgenehelper.test_helpers import TestHelpers
from scripts.build_env.tests.base_test import BaseTest

FEATURE_TEST_DIR = "test_null_value_validation"


def _prepare_case(output_dir: Path, fixtures_dir: Path, case_name: str) -> Path:
    """Copy fixture files from fixtures_dir/case_name to a fresh output directory and return it."""
    case_dir = output_dir / case_name
    if case_dir.exists():
        shutil.rmtree(case_dir)
    shutil.copytree(fixtures_dir / case_name, case_dir)
    return case_dir


class TestNullValueValidationParameters(BaseTest):
    """UC-NVV-1 / UC-NVV-3 — parameter scope."""

    def setup_method(self):
        self.feature_dir = self.output_dir / FEATURE_TEST_DIR / "params"
        self.feature_dir.mkdir(parents=True, exist_ok=True)
        self.params_data = self.test_data_dir / FEATURE_TEST_DIR / "params"

    def _prepare(self, case_name: str) -> Path:
        return _prepare_case(self.feature_dir, self.params_data, case_name)

    # ------------------------------------------------------------------
    # Positive — UC-NVV-3
    # ------------------------------------------------------------------

    def test_all_parameters_resolved_passes(self, caplog):
        # UC-NVV-3: no envgeneNullValue anywhere — validation must pass and log completion.
        env_dir = self._prepare("TC-NVV-3-params")
        with caplog.at_level(logging.INFO, logger="envgene"):
            validate_parameters(env_dir=str(env_dir))
        assert "Starting validation of parameters" in caplog.text
        assert "Validation of parameters is completed" in caplog.text

    # ------------------------------------------------------------------
    # Negative — UC-NVV-1
    # ------------------------------------------------------------------

    def test_unresolved_deploy_parameter_in_tenant_raises(self, caplog):
        # UC-NVV-1: envgeneNullValue in tenant.yml deployParameters.
        env_dir = self._prepare("TC-NVV-1-tenant-deploy")
        with caplog.at_level(logging.INFO, logger="envgene"):
            with pytest.raises(ValidationError) as exc_info:
                validate_parameters(env_dir=str(env_dir))
        error = str(exc_info.value)
        assert "Error while validating parameters" in error
        assert "my-tenant.deployParameters.API_URL - is not set" in error
        assert "Starting validation of parameters" in caplog.text
        assert "Validation of parameters is completed" not in caplog.text, \
            "completion log must not appear when validation fails"

    def test_unresolved_e2e_parameter_in_cloud_raises(self):
        # UC-NVV-1: envgeneNullValue in cloud.yml e2eParameters.
        env_dir = self._prepare("TC-NVV-1-cloud-e2e")
        with pytest.raises(ValidationError) as exc_info:
            validate_parameters(env_dir=str(env_dir))
        error = str(exc_info.value)
        assert "Error while validating parameters" in error
        assert "my-cloud.e2eParameters.BASE_URL - is not set" in error

    def test_unresolved_technical_parameter_in_namespace_raises(self):
        # UC-NVV-1: envgeneNullValue in a namespace technicalConfigurationParameters.
        env_dir = self._prepare("TC-NVV-1-ns-technical")
        with pytest.raises(ValidationError) as exc_info:
            validate_parameters(env_dir=str(env_dir))
        error = str(exc_info.value)
        assert "Error while validating parameters" in error
        assert "namespace.monitoring.technicalConfigurationParameters.LOG_LEVEL - is not set" in error

    def test_multiple_unresolved_parameters_all_reported(self):
        # UC-NVV-4: all violations must appear in a single error.
        env_dir = self._prepare("TC-NVV-4-params")
        with pytest.raises(ValidationError) as exc_info:
            validate_parameters(env_dir=str(env_dir))
        error = str(exc_info.value)
        assert "my-tenant.deployParameters.API_URL - is not set" in error
        assert "my-tenant.deployParameters.DB_HOST - is not set" in error

    def test_case_insensitive_null_value_raises(self):
        # envgeneNullValue check is case-insensitive per is_envgenenullvalue().
        env_dir = self._prepare("TC-NVV-1-case-insensitive")
        with pytest.raises(ValidationError):
            validate_parameters(env_dir=str(env_dir))

    def test_non_string_parameter_value_does_not_raise(self):
        # is_envgenenullvalue returns False for non-string values — integers/booleans pass.
        env_dir = self._prepare("TC-NVV-3-non-string")
        validate_parameters(env_dir=str(env_dir))

    def test_null_value_as_substring_in_parameter_does_not_raise(self):
        # is_envgenenullvalue checks exact equality — "prefix-envgeneNullValue" must pass.
        env_dir = self._prepare("edge-null-substring-param")
        validate_parameters(env_dir=str(env_dir))

    def test_empty_string_parameter_does_not_raise(self):
        # Empty string is not envgeneNullValue.
        env_dir = self._prepare("edge-empty-string-param")
        validate_parameters(env_dir=str(env_dir))

    def test_missing_tenant_yml_raises(self):
        # openYaml without allow_default raises FileNotFoundError when tenant.yml is absent.
        env_dir = self._prepare("edge-missing-tenant")
        with pytest.raises(FileNotFoundError):
            validate_parameters(env_dir=str(env_dir))

    def test_missing_cloud_yml_raises(self):
        # Same for cloud.yml.
        env_dir = self._prepare("edge-missing-cloud")
        with pytest.raises(FileNotFoundError):
            validate_parameters(env_dir=str(env_dir))


class TestNullValueValidationCredentials(BaseTest):
    """UC-NVV-2 / UC-NVV-3 / UC-NVV-4 — credentials scope."""

    def setup_method(self):
        self.feature_dir = self.output_dir / FEATURE_TEST_DIR / "creds"
        self.feature_dir.mkdir(parents=True, exist_ok=True)
        self.creds_data = self.test_data_dir / FEATURE_TEST_DIR / "creds"

    def _prepare(self, case_name: str) -> Path:
        return _prepare_case(self.feature_dir, self.creds_data, case_name)

    # ------------------------------------------------------------------
    # Positive — UC-NVV-3
    # ------------------------------------------------------------------

    def test_all_credentials_resolved_passes(self, caplog):
        # UC-NVV-3: all credential values are real — validation must pass and log completion.
        creds_dir = self._prepare("TC-NVV-3-creds")
        with caplog.at_level(logging.INFO, logger="envgene"):
            validate_creds(creds_path=str(creds_dir))
        assert "Starting validation of credentials" in caplog.text
        assert "Validation of credentials is completed" in caplog.text

    # ------------------------------------------------------------------
    # Negative — UC-NVV-2
    # ------------------------------------------------------------------

    def test_unresolved_username_password_raises(self, caplog):
        # UC-NVV-2: envgeneNullValue in usernamePassword credential.
        creds_dir = self._prepare("TC-NVV-2-userpass")
        with caplog.at_level(logging.INFO, logger="envgene"):
            with pytest.raises(ValidationError) as exc_info:
                validate_creds(creds_path=str(creds_dir))
        error = str(exc_info.value)
        assert "Error while validating credentials" in error
        assert "credId: dbaas-cluster-dba-cred - username or password is not set" in error
        assert "Starting validation of credentials" in caplog.text
        assert "Validation of credentials is completed" not in caplog.text, \
            "completion log must not appear when validation fails"

    def test_unresolved_secret_raises(self):
        # UC-NVV-2: envgeneNullValue in secret credential.
        creds_dir = self._prepare("TC-NVV-2-secret")
        with pytest.raises(ValidationError) as exc_info:
            validate_creds(creds_path=str(creds_dir))
        error = str(exc_info.value)
        assert "Error while validating credentials" in error
        assert "credId: consul-admin-cred - secret is not set" in error

    def test_unresolved_vault_approle_raises(self):
        # UC-NVV-2: envgeneNullValue in vaultAppRole credential.
        creds_dir = self._prepare("TC-NVV-2-vault")
        with pytest.raises(ValidationError) as exc_info:
            validate_creds(creds_path=str(creds_dir))
        error = str(exc_info.value)
        assert "Error while validating credentials" in error
        assert "credId: vault-role-cred - secretId is not set" in error

    def test_only_username_unresolved_raises(self):
        # UC-NVV-2: only username is envgeneNullValue while password is set — must still fail.
        creds_dir = self._prepare("TC-NVV-2-userpass-partial")
        with pytest.raises(ValidationError) as exc_info:
            validate_creds(creds_path=str(creds_dir))
        assert "credId: db-cred - username or password is not set" in str(exc_info.value)

    # ------------------------------------------------------------------
    # Negative — UC-NVV-4 (aggregated errors)
    # ------------------------------------------------------------------

    def test_multiple_unresolved_credentials_all_reported(self):
        # UC-NVV-4: every violation across all creds must appear in a single error message.
        creds_dir = self._prepare("TC-NVV-4-creds")
        with pytest.raises(ValidationError) as exc_info:
            validate_creds(creds_path=str(creds_dir))
        error = str(exc_info.value)
        assert "credId: dbaas-cluster-dba-cred - username or password is not set" in error
        assert "credId: consul-admin-cred - secret is not set" in error

    def test_multiple_unresolved_across_files_all_reported(self):
        # UC-NVV-4: violations spread across two separate credential files — all must appear.
        creds_dir = self._prepare("TC-NVV-4-multi-file")
        with pytest.raises(ValidationError) as exc_info:
            validate_creds(creds_path=str(creds_dir))
        error = str(exc_info.value)
        assert "credId: db-cred - username or password is not set" in error
        assert "credId: consul-cred - secret is not set" in error

    def test_resolved_and_unresolved_mixed_reports_only_unresolved(self):
        # UC-NVV-4: valid credential must not appear in the error, invalid ones must.
        creds_dir = self._prepare("TC-NVV-4-mixed")
        with pytest.raises(ValidationError) as exc_info:
            validate_creds(creds_path=str(creds_dir))
        error = str(exc_info.value)
        assert "credId: bad-cred - secret is not set" in error
        assert "good-cred" not in error

    # ------------------------------------------------------------------
    # Edge cases
    # ------------------------------------------------------------------

    def test_null_value_as_substring_in_credential_does_not_raise(self):
        # is_envgenenullvalue checks exact equality — substring must not trigger validation error.
        creds_dir = self._prepare("edge-null-substring-cred")
        validate_creds(creds_path=str(creds_dir))

    def test_empty_string_credential_does_not_raise(self):
        # Empty string password is not envgeneNullValue — structural check only.
        creds_dir = self._prepare("edge-empty-string-cred")
        validate_creds(creds_path=str(creds_dir))

    def test_empty_credentials_file_does_not_raise(self):
        # credentials.yml exists but is empty — iteration over .items() yields nothing.
        creds_dir = self._prepare("edge-empty-creds-file")
        validate_creds(creds_path=str(creds_dir))

    def test_credential_missing_data_key_raises_key_error(self):
        # check_cred_value does credValue["data"] without guard — documents current behavior.
        # If fixed to raise ValidationError in the future, update this test accordingly.
        creds_dir = self._prepare("edge-missing-data-key")
        with pytest.raises(KeyError):
            validate_creds(creds_path=str(creds_dir))
