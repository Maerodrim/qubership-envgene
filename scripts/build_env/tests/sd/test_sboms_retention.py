import logging
import shutil
import time
from pathlib import Path

import pytest
from pydantic import ValidationError

from build_effective_set_generator.scripts.sboms_retention_policy import sboms_retention_policy
from envgenehelper.test_helpers import TestHelpers
from scripts.build_env.tests.base_test import BaseTest

FEATURE_TEST_DIR = "test_handle_sboms"


def _files_by_mtime(app_dir: Path) -> list[str]:
    """Return filenames sorted oldest→newest by mtime."""
    files = [f for f in app_dir.iterdir() if f.is_file()]
    files.sort(key=lambda f: f.stat().st_mtime)
    return [f.name for f in files]


def create_test_data(base_dir: Path, test_case_name: str):
    sboms_dir = base_dir / "sboms"
    config_dir = base_dir / "configuration"
    config_dir.mkdir(exist_ok=True)
    config_file = config_dir / "config.yml"

    if test_case_name == "UC-SBOM-1":
        # Retention disabled — no files should be removed
        sboms_dir.mkdir(exist_ok=True)
        config_file.write_text("sbom_retention:\n  enabled: false\n")
        app_a_dir = sboms_dir / "app-a"
        app_a_dir.mkdir(exist_ok=True)
        TestHelpers.create_file(app_a_dir / "app-a-1.0.sbom.json", size=100)
        TestHelpers.create_file(app_a_dir / "app-a-2.0.sbom.json", size=100)

    elif test_case_name == "UC-SBOM-2":
        # All apps have fewer versions than the limit — no files should be removed
        sboms_dir.mkdir(exist_ok=True)
        config_file.write_text("sbom_retention:\n  enabled: true\n  keep_versions_per_app: 10\n")
        app_a_dir = sboms_dir / "app-a"
        app_a_dir.mkdir(exist_ok=True)
        for i in range(7):
            TestHelpers.create_file(app_a_dir / f"app-a-{i}.sbom.json", 100, time.time() + i)
        app_b_dir = sboms_dir / "app-b"
        app_b_dir.mkdir(exist_ok=True)
        for i in range(4):
            TestHelpers.create_file(app_b_dir / f"app-b-{i}.sbom.json", 100, time.time() + i)
        app_c_dir = sboms_dir / "app-c"
        app_c_dir.mkdir(exist_ok=True)
        for i in range(10):
            TestHelpers.create_file(app_c_dir / f"app-c-{i}.sbom.json", 100, time.time() + i)

    elif test_case_name == "UC-SBOM-3":
        # Some apps exceed the limit — only the newest 10 should survive per app
        sboms_dir.mkdir(exist_ok=True)
        config_file.write_text("sbom_retention:\n  enabled: true\n  keep_versions_per_app: 10\n")
        app_a_dir = sboms_dir / "app-a"
        app_a_dir.mkdir(exist_ok=True)
        for i in range(15):
            TestHelpers.create_file(app_a_dir / f"app-a-{i}.sbom.json", 100, time.time() + i)
        app_b_dir = sboms_dir / "app-b"
        app_b_dir.mkdir(exist_ok=True)
        for i in range(12):
            TestHelpers.create_file(app_b_dir / f"app-b-{i}.sbom.json", 100, time.time() + i)
        app_c_dir = sboms_dir / "app-c"
        app_c_dir.mkdir(exist_ok=True)
        for i in range(8):
            TestHelpers.create_file(app_c_dir / f"app-c-{i}.sbom.json", 100, time.time() + i)

    elif test_case_name == "UC-SBOM-4":
        # Strict limit — only 3 newest versions should survive
        sboms_dir.mkdir(exist_ok=True)
        config_file.write_text("sbom_retention:\n  enabled: true\n  keep_versions_per_app: 3\n")
        postgres_dir = sboms_dir / "postgres"
        postgres_dir.mkdir(exist_ok=True)
        for i in range(10):
            TestHelpers.create_file(postgres_dir / f"postgres-{i}.sbom.json", 100, time.time() + i)

    elif test_case_name == "UC-SBOM-5":
        # Size-based cleanup: no app exceeds keep_versions_per_app (5 < 10), so per-app
        # retention deletes nothing. The total size (5×300 MB = 1500 MB) then exceeds
        # CI_JOB_ARTIFACT_MAX_SIZE_MB (currently 600 MB; docs spec 1200 MB — see constants.py),
        # which triggers the size limit branch and trims ALL app dirs down to 1 newest file.
        sboms_dir.mkdir(exist_ok=True)
        config_file.write_text("sbom_retention:\n  enabled: true\n  keep_versions_per_app: 10\n")
        app_a_dir = sboms_dir / "app-a"
        app_a_dir.mkdir(exist_ok=True)
        for i in range(5):
            TestHelpers.create_file(app_a_dir / f"app-a-{i}.sbom.json", 300 * 1024 * 1024, time.time() + i)
        app_b_dir = sboms_dir / "app-b"
        app_b_dir.mkdir(exist_ok=True)
        for i in range(5):
            TestHelpers.create_file(app_b_dir / f"app-b-{i}.sbom.json", 100, time.time() + i)

    elif test_case_name == "UC-SBOM-NEGATIVE-1":
        # sboms directory intentionally absent
        pass

    elif test_case_name == "UC-SBOM-NEGATIVE-2":
        sboms_dir.mkdir(exist_ok=True)
        config_file.write_text("sbom_retention:\n  enabled: true\n  keep_versions_per_app: 'invalid'\n")


def assert_results(base_dir: Path, test_case_name: str):
    sboms_dir = base_dir / "sboms"

    if test_case_name == "UC-SBOM-1":
        # Retention disabled — both files must still be present
        files = _files_by_mtime(sboms_dir / "app-a")
        assert len(files) == 2

    elif test_case_name == "UC-SBOM-2":
        # Nothing exceeds the limit — all files survive
        assert len(_files_by_mtime(sboms_dir / "app-a")) == 7
        assert len(_files_by_mtime(sboms_dir / "app-b")) == 4
        assert len(_files_by_mtime(sboms_dir / "app-c")) == 10

    elif test_case_name == "UC-SBOM-3":
        # app-a: 15→10, app-b: 12→10, app-c: 8 (untouched)
        app_a_files = _files_by_mtime(sboms_dir / "app-a")
        assert len(app_a_files) == 10
        assert app_a_files[-1] == "app-a-14.sbom.json", "newest file must be retained"
        assert app_a_files[0] == "app-a-5.sbom.json", "oldest retained must be app-a-5"

        app_b_files = _files_by_mtime(sboms_dir / "app-b")
        assert len(app_b_files) == 10
        assert app_b_files[-1] == "app-b-11.sbom.json"
        assert app_b_files[0] == "app-b-2.sbom.json"

        assert len(_files_by_mtime(sboms_dir / "app-c")) == 8

    elif test_case_name == "UC-SBOM-4":
        postgres_files = _files_by_mtime(sboms_dir / "postgres")
        assert len(postgres_files) == 3
        assert postgres_files[-1] == "postgres-9.sbom.json", "newest file must be retained"
        assert postgres_files[0] == "postgres-7.sbom.json", "oldest retained must be postgres-7"

    elif test_case_name == "UC-SBOM-5":
        # Per-app retention skipped (5 < 10). Total size > limit → all app dirs trimmed to 1 newest file.
        app_a_files = _files_by_mtime(sboms_dir / "app-a")
        assert len(app_a_files) == 1
        assert app_a_files[0] == "app-a-4.sbom.json", "only newest app-a version must survive"

        app_b_files = _files_by_mtime(sboms_dir / "app-b")
        assert len(app_b_files) == 1
        assert app_b_files[0] == "app-b-4.sbom.json", "only newest app-b version must survive"


class TestSbomRetention(BaseTest):

    def setup_method(self):
        self.feature_dir = self.output_dir / FEATURE_TEST_DIR
        self.feature_dir.mkdir(parents=True, exist_ok=True)
        self.set_ci_project_dir(self.feature_dir)

    def _prepare_case_dir(self, test_case_name: str) -> Path:
        case_dir = self.feature_dir / test_case_name
        if case_dir.exists():
            shutil.rmtree(case_dir)
        case_dir.mkdir(parents=True, exist_ok=True)
        self.set_ci_project_dir(case_dir)
        return case_dir

    @pytest.mark.parametrize("test_case_name", [
        "UC-SBOM-1",
        "UC-SBOM-2",
        "UC-SBOM-3",
        "UC-SBOM-4",
        "UC-SBOM-5",
    ])
    def test_sbom_retention_scenarios_positive(self, test_case_name):
        case_dir = self._prepare_case_dir(test_case_name)
        create_test_data(case_dir, test_case_name)
        sboms_retention_policy()
        assert_results(case_dir, test_case_name)

    def test_sbom_retention_disabled_no_sboms_dir(self, caplog):
        # UC-SBOM-NEGATIVE-1: missing sboms directory logs a warning and exits cleanly
        case_dir = self._prepare_case_dir("UC-SBOM-NEGATIVE-1")
        create_test_data(case_dir, "UC-SBOM-NEGATIVE-1")
        with caplog.at_level(logging.WARNING):
            sboms_retention_policy()
        assert "does not exist" in caplog.text

    def test_sbom_retention_invalid_config_raises(self):
        # UC-SBOM-NEGATIVE-2: invalid keep_versions_per_app type must raise ValidationError
        case_dir = self._prepare_case_dir("UC-SBOM-NEGATIVE-2")
        create_test_data(case_dir, "UC-SBOM-NEGATIVE-2")
        with pytest.raises(ValidationError):
            sboms_retention_policy()
