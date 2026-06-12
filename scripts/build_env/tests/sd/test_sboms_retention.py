import time
from pathlib import Path

import pytest

from build_effective_set_generator.scripts.sboms_retention_policy import sboms_retention_policy
from envgenehelper.test_helpers import TestHelpers
from scripts.build_env.tests.base_test import BaseTest

TEST_CASES = [
    "UC-SBOM-1",
    "UC-SBOM-2",
    "UC-SBOM-3",
    "UC-SBOM-4",
    "UC-SBOM-5",
]

FEATURE_TEST_DIR = "test_handle_sboms"


def create_test_data(base_dir: Path, test_case_name: str):
    """Create test data programmatically based on the use case name."""
    sboms_dir = base_dir / "sboms"
    sboms_dir.mkdir(exist_ok=True)
    config_dir = base_dir / "configuration"
    config_dir.mkdir(exist_ok=True)
    config_file = config_dir / "config.yml"

    if test_case_name == "UC-SBOM-1":
        config_file.write_text("sbom_retention:\n  enabled: false\n")
        app_a_dir = sboms_dir / "app-a"
        app_a_dir.mkdir(exist_ok=True)
        TestHelpers.create_file(app_a_dir / "app-a-1.0.sbom.json", size=100)
        TestHelpers.create_file(app_a_dir / "app-a-2.0.sbom.json", size=100)

    elif test_case_name == "UC-SBOM-2":
        config_file.write_text("sbom_retention:\n  enabled: true\n  keep_versions_per_app: 10\n")
        # app-a with 7 versions
        app_a_dir = sboms_dir / "app-a";
        app_a_dir.mkdir(exist_ok=True)
        for i in range(7): TestHelpers.create_file(app_a_dir / f"app-a-{i}.sbom.json", 100, time.time() + i)
        # app-b with 4 versions
        app_b_dir = sboms_dir / "app-b";
        app_b_dir.mkdir(exist_ok=True)
        for i in range(4): TestHelpers.create_file(app_b_dir / f"app-b-{i}.sbom.json", 100, time.time() + i)
        # app-c with 10 versions
        app_c_dir = sboms_dir / "app-c";
        app_c_dir.mkdir(exist_ok=True)
        for i in range(10): TestHelpers.create_file(app_c_dir / f"app-c-{i}.sbom.json", 100, time.time() + i)

    elif test_case_name == "UC-SBOM-3":
        config_file.write_text("sbom_retention:\n  enabled: true\n  keep_versions_per_app: 10\n")
        # app-a with 15 versions
        app_a_dir = sboms_dir / "app-a";
        app_a_dir.mkdir(exist_ok=True)
        for i in range(15): TestHelpers.create_file(app_a_dir / f"app-a-{i}.sbom.json", 100, time.time() + i)
        # app-b with 12 versions
        app_b_dir = sboms_dir / "app-b";
        app_b_dir.mkdir(exist_ok=True)
        for i in range(12): TestHelpers.create_file(app_b_dir / f"app-b-{i}.sbom.json", 100, time.time() + i)
        # app-c with 8 versions
        app_c_dir = sboms_dir / "app-c";
        app_c_dir.mkdir(exist_ok=True)
        for i in range(8): TestHelpers.create_file(app_c_dir / f"app-c-{i}.sbom.json", 100, time.time() + i)

    elif test_case_name == "UC-SBOM-4":
        config_file.write_text("sbom_retention:\n  enabled: true\n  keep_versions_per_app: 3\n")
        postgres_dir = sboms_dir / "postgres";
        postgres_dir.mkdir(exist_ok=True)
        for i in range(10): TestHelpers.create_file(postgres_dir / f"postgres-{i}.sbom.json", 100, time.time() + i)

    elif test_case_name == "UC-SBOM-5":
        config_file.write_text("sbom_retention:\n  enabled: true\n  keep_versions_per_app: 10\n")
        app_a_dir = sboms_dir / "app-a";
        app_a_dir.mkdir(exist_ok=True)
        for i in range(5): TestHelpers.create_file(app_a_dir / f"app-a-{i}.sbom.json", 300 * 1024 * 1024,
                                                   time.time() + i)
        app_b_dir = sboms_dir / "app-b";
        app_b_dir.mkdir(exist_ok=True)
        for i in range(5): TestHelpers.create_file(app_b_dir / f"app-b-{i}.sbom.json", 100, time.time() + i)


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

    @pytest.mark.parametrize("test_case_name", TEST_CASES)
    def test_sbom_retention_scenarios(self, test_case_name):
        # 1. Arrange: Create test data in the temp output dir
        # Provide clean directory for each test case
        case_dir = self.feature_dir / test_case_name
        import shutil
        if case_dir.exists():
            shutil.rmtree(case_dir)
        case_dir.mkdir(parents=True, exist_ok=True)

        # update CI_PROJECT_DIR to be case specific
        self.set_ci_project_dir(case_dir)

        create_test_data(case_dir, test_case_name)

        # 2. Act: Run the retention policy
        sboms_retention_policy()

        # 3. Assert: Check the results
        assert_results(case_dir, test_case_name)
