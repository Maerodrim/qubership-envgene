import time
from pathlib import Path

import pytest
from pydantic import ValidationError

from build_effective_set_generator.scripts.sboms_retention_policy import sboms_retention_policy
from envgenehelper.test_helpers import TestHelpers
from scripts.build_env.tests.base_test import BaseTest

TEST_CASES_POSITIVE = [
    "UC-SBOM-1",
    "UC-SBOM-2",
    "UC-SBOM-3",
    "UC-SBOM-4",
    "UC-SBOM-5",
]

TEST_CASES_NEGATIVE = {
    "UC-SBOM-NEGATIVE-1": "does not exist",  # sboms directory does not exist
    "UC-SBOM-NEGATIVE-2": ValidationError,  # Invalid config
}

FEATURE_TEST_DIR = "test_handle_sboms"


def create_test_data(base_dir: Path, test_case_name: str):
    """Create test data programmatically based on the use case name."""
    sboms_dir = base_dir / "sboms"
    config_dir = base_dir / "configuration"
    config_dir.mkdir(exist_ok=True)
    config_file = config_dir / "config.yml"

    if test_case_name == "UC-SBOM-1":
        sboms_dir.mkdir(exist_ok=True)
        config_file.write_text("sbom_retention:\n  enabled: false\n")
        app_a_dir = sboms_dir / "app-a"; app_a_dir.mkdir(exist_ok=True)
        TestHelpers.create_file(app_a_dir / "app-a-1.0.sbom.json", size=100)
        TestHelpers.create_file(app_a_dir / "app-a-2.0.sbom.json", size=100)

    elif test_case_name == "UC-SBOM-2":
        sboms_dir.mkdir(exist_ok=True)
        config_file.write_text("sbom_retention:\n  enabled: true\n  keep_versions_per_app: 10\n")
        app_a_dir = sboms_dir / "app-a"; app_a_dir.mkdir(exist_ok=True)
        for i in range(7): TestHelpers.create_file(app_a_dir / f"app-a-{i}.sbom.json", 100, time.time() + i)
        app_b_dir = sboms_dir / "app-b"; app_b_dir.mkdir(exist_ok=True)
        for i in range(4): TestHelpers.create_file(app_b_dir / f"app-b-{i}.sbom.json", 100, time.time() + i)
        app_c_dir = sboms_dir / "app-c"; app_c_dir.mkdir(exist_ok=True)
        for i in range(10): TestHelpers.create_file(app_c_dir / f"app-c-{i}.sbom.json", 100, time.time() + i)

    elif test_case_name == "UC-SBOM-3":
        sboms_dir.mkdir(exist_ok=True)
        config_file.write_text("sbom_retention:\n  enabled: true\n  keep_versions_per_app: 10\n")
        app_a_dir = sboms_dir / "app-a"; app_a_dir.mkdir(exist_ok=True)
        for i in range(15): TestHelpers.create_file(app_a_dir / f"app-a-{i}.sbom.json", 100, time.time() + i)
        app_b_dir = sboms_dir / "app-b"; app_b_dir.mkdir(exist_ok=True)
        for i in range(12): TestHelpers.create_file(app_b_dir / f"app-b-{i}.sbom.json", 100, time.time() + i)
        app_c_dir = sboms_dir / "app-c"; app_c_dir.mkdir(exist_ok=True)
        for i in range(8): TestHelpers.create_file(app_c_dir / f"app-c-{i}.sbom.json", 100, time.time() + i)

    elif test_case_name == "UC-SBOM-4":
        sboms_dir.mkdir(exist_ok=True)
        config_file.write_text("sbom_retention:\n  enabled: true\n  keep_versions_per_app: 3\n")
        postgres_dir = sboms_dir / "postgres"; postgres_dir.mkdir(exist_ok=True)
        for i in range(10): TestHelpers.create_file(postgres_dir / f"postgres-{i}.sbom.json", 100, time.time() + i)

    elif test_case_name == "UC-SBOM-5":
        sboms_dir.mkdir(exist_ok=True)
        config_file.write_text("sbom_retention:\n  enabled: true\n  keep_versions_per_app: 10\n")
        app_a_dir = sboms_dir / "app-a"; app_a_dir.mkdir(exist_ok=True)
        for i in range(5): TestHelpers.create_file(app_a_dir / f"app-a-{i}.sbom.json", 300 * 1024 * 1024, time.time() + i)
        app_b_dir = sboms_dir / "app-b"; app_b_dir.mkdir(exist_ok=True)
        for i in range(5): TestHelpers.create_file(app_b_dir / f"app-b-{i}.sbom.json", 100, time.time() + i)

    elif test_case_name == "UC-SBOM-NEGATIVE-1":
        # No sboms dir
        pass

    elif test_case_name == "UC-SBOM-NEGATIVE-2":
        sboms_dir.mkdir(exist_ok=True)
        config_file.write_text("sbom_retention:\n  enabled: true\n  keep_versions_per_app: 'invalid'\n")


def assert_results(base_dir: Path, test_case_name: str):
    """Assert the state of the sboms directory after the policy runs."""
    sboms_dir = base_dir / "sboms"
    if test_case_name == "UC-SBOM-1":
        assert len(list((sboms_dir / "app-a").iterdir())) == 2
    elif test_case_name == "UC-SBOM-2":
        assert len(list((sboms_dir / "app-a").iterdir())) == 7
        assert len(list((sboms_dir / "app-b").iterdir())) == 4
        assert len(list((sboms_dir / "app-c").iterdir())) == 10
    elif test_case_name == "UC-SBOM-3":
        assert len(list((sboms_dir / "app-a").iterdir())) == 10
        assert len(list((sboms_dir / "app-b").iterdir())) == 10
        assert len(list((sboms_dir / "app-c").iterdir())) == 8
    elif test_case_name == "UC-SBOM-4":
        assert len(list((sboms_dir / "postgres").iterdir())) == 3
    elif test_case_name == "UC-SBOM-5":
        assert len(list((sboms_dir / "app-a").iterdir())) == 1
        assert len(list((sboms_dir / "app-b").iterdir())) == 1


class TestSbomRetention(BaseTest):

    def setup_method(self):
        self.feature_dir = self.output_dir / FEATURE_TEST_DIR
        self.feature_dir.mkdir(parents=True, exist_ok=True)
        self.set_ci_project_dir(self.feature_dir)

    @pytest.mark.parametrize("test_case_name", TEST_CASES_POSITIVE)
    def test_sbom_retention_scenarios_positive(self, test_case_name):
        case_dir = self.feature_dir / test_case_name
        import shutil
        if case_dir.exists(): shutil.rmtree(case_dir)
        case_dir.mkdir(parents=True, exist_ok=True)
        self.set_ci_project_dir(case_dir)
        create_test_data(case_dir, test_case_name)
        sboms_retention_policy()
        assert_results(case_dir, test_case_name)

    @pytest.mark.parametrize("test_case_name,expected", TEST_CASES_NEGATIVE.items())
    def test_sbom_retention_scenarios_negative(self, test_case_name, expected, caplog):
        case_dir = self.feature_dir / test_case_name
        import shutil
        if case_dir.exists(): shutil.rmtree(case_dir)
        case_dir.mkdir(parents=True, exist_ok=True)
        self.set_ci_project_dir(case_dir)
        create_test_data(case_dir, test_case_name)

        if isinstance(expected, str):
            sboms_retention_policy()
            assert expected in caplog.text
        else:
            with pytest.raises(expected):
                sboms_retention_policy()
