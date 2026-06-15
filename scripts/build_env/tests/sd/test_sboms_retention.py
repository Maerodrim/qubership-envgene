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


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _files(directory: Path) -> list[str]:
    return [f.name for f in directory.iterdir() if f.is_file()]


def _files_by_mtime(app_dir: Path) -> list[str]:
    """Return filenames sorted oldest→newest by mtime."""
    files = [f for f in app_dir.iterdir() if f.is_file()]
    files.sort(key=lambda f: f.stat().st_mtime)
    return [f.name for f in files]


def _dump_dir(directory: Path) -> str:
    """Return a formatted directory listing with mtime for each file, for assertion messages."""
    if not directory.exists():
        return f"{directory} — does not exist"
    entries = sorted(directory.iterdir(), key=lambda f: f.stat().st_mtime)
    if not entries:
        return f"{directory} — empty"
    lines = [f"  {e.name} (mtime={e.stat().st_mtime:.3f}, {'dir' if e.is_dir() else f'{e.stat().st_size}B'})"
             for e in entries]
    return f"{directory}:\n" + "\n".join(lines)


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
        assert len(app_a_files) == 10, _dump_dir(sboms_dir / "app-a")
        assert app_a_files[-1] == "app-a-14.sbom.json", f"newest must be retained; got {app_a_files}"
        assert app_a_files[0] == "app-a-5.sbom.json", f"oldest retained must be app-a-5; got {app_a_files}"

        app_b_files = _files_by_mtime(sboms_dir / "app-b")
        assert len(app_b_files) == 10, _dump_dir(sboms_dir / "app-b")
        assert app_b_files[-1] == "app-b-11.sbom.json", f"newest must be retained; got {app_b_files}"
        assert app_b_files[0] == "app-b-2.sbom.json", f"oldest retained must be app-b-2; got {app_b_files}"

        app_c_files = _files_by_mtime(sboms_dir / "app-c")
        assert len(app_c_files) == 8, _dump_dir(sboms_dir / "app-c")

    elif test_case_name == "UC-SBOM-4":
        postgres_files = _files_by_mtime(sboms_dir / "postgres")
        assert len(postgres_files) == 3, _dump_dir(sboms_dir / "postgres")
        assert postgres_files[-1] == "postgres-9.sbom.json", f"newest must be retained; got {postgres_files}"
        assert postgres_files[0] == "postgres-7.sbom.json", f"oldest retained must be postgres-7; got {postgres_files}"

    elif test_case_name == "UC-SBOM-5":
        # Per-app retention skipped (5 < 10). Total size > limit → all app dirs trimmed to 1 newest file.
        app_a_files = _files_by_mtime(sboms_dir / "app-a")
        assert len(app_a_files) == 1, _dump_dir(sboms_dir / "app-a")
        assert app_a_files[0] == "app-a-4.sbom.json", f"only newest app-a must survive; got {app_a_files}"

        app_b_files = _files_by_mtime(sboms_dir / "app-b")
        assert len(app_b_files) == 1, _dump_dir(sboms_dir / "app-b")
        assert app_b_files[0] == "app-b-4.sbom.json", f"only newest app-b must survive; got {app_b_files}"


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
        with caplog.at_level(logging.WARNING, logger="envgene"):
            sboms_retention_policy()
        assert "does not exist" in caplog.text

    def test_sbom_retention_invalid_config_raises(self):
        # UC-SBOM-NEGATIVE-2: invalid keep_versions_per_app type must raise ValidationError
        case_dir = self._prepare_case_dir("UC-SBOM-NEGATIVE-2")
        create_test_data(case_dir, "UC-SBOM-NEGATIVE-2")
        with pytest.raises(ValidationError):
            sboms_retention_policy()


class TestSbomMigration(BaseTest):
    """Tests for UC-SBOM-MIG: migration from flat to per-application SBOM layout."""

    def setup_method(self):
        self.feature_dir = self.output_dir / "test_handle_sboms"
        self.feature_dir.mkdir(parents=True, exist_ok=True)
        self.set_ci_project_dir(self.feature_dir)

    def _prepare_case_dir(self, test_case_name: str) -> Path:
        case_dir = self.feature_dir / test_case_name
        if case_dir.exists():
            shutil.rmtree(case_dir)
        case_dir.mkdir(parents=True, exist_ok=True)
        self.set_ci_project_dir(case_dir)
        return case_dir

    def test_flat_legacy_files_are_removed_on_first_run(self, caplog):
        # UC-SBOM-MIG-1: on first run after upgrade, flat SBOM files directly under /sboms/
        # are deleted by the retention policy. Per-application subdirectory files are untouched.
        # The regeneration of SBOMs in the new per-app layout is handled by the effective set
        # generation pipeline and is outside the scope of sboms_retention_policy.
        case_dir = self._prepare_case_dir("UC-SBOM-MIG-1")
        sboms_dir = case_dir / "sboms"
        sboms_dir.mkdir()
        config_dir = case_dir / "configuration"
        config_dir.mkdir()
        (config_dir / "config.yml").write_text("sbom_retention:\n  enabled: true\n  keep_versions_per_app: 10\n")

        # Legacy flat layout: files directly under /sboms/
        flat_app_a = sboms_dir / "app-a-1.0.sbom.json"
        flat_app_b = sboms_dir / "app-b-2.3.sbom.json"
        TestHelpers.create_file(flat_app_a, size=100)
        TestHelpers.create_file(flat_app_b, size=100)

        # New per-app layout already partially populated (e.g. from a prior partial run)
        app_a_dir = sboms_dir / "app-a"
        app_a_dir.mkdir()
        existing_new_layout_file = app_a_dir / "app-a-1.0.sbom.json"
        TestHelpers.create_file(existing_new_layout_file, size=100)

        with caplog.at_level(logging.INFO, logger="envgene"):
            sboms_retention_policy()

        # Flat legacy files must be deleted
        assert not flat_app_a.exists(), f"flat app-a SBOM must be removed;\n{_dump_dir(sboms_dir)}"
        assert not flat_app_b.exists(), f"flat app-b SBOM must be removed;\n{_dump_dir(sboms_dir)}"

        # No flat files remain directly under /sboms/
        remaining_flat = [f for f in sboms_dir.iterdir() if f.is_file()]
        assert remaining_flat == [], f"unexpected flat files remain:\n{_dump_dir(sboms_dir)}"

        # Per-app subdirectory files must be untouched
        assert existing_new_layout_file.exists(), \
            f"per-app layout file must not be deleted;\n{_dump_dir(app_a_dir)}"

        # Policy must log removal of legacy files
        assert "legacy" in caplog.text.lower() or "Removing" in caplog.text, \
            f"expected removal log entry; captured log:\n{caplog.text}"

    def test_empty_sboms_dir_does_not_raise(self):
        # Migration negative: /sboms/ exists but is completely empty — policy must exit cleanly
        case_dir = self._prepare_case_dir("UC-SBOM-MIG-NEGATIVE-1")
        sboms_dir = case_dir / "sboms"
        sboms_dir.mkdir()
        config_dir = case_dir / "configuration"
        config_dir.mkdir()
        (config_dir / "config.yml").write_text("sbom_retention:\n  enabled: true\n  keep_versions_per_app: 10\n")

        sboms_retention_policy()  # must not raise

        assert list(sboms_dir.iterdir()) == [], \
            f"sboms dir must remain empty;\n{_dump_dir(sboms_dir)}"

    def test_already_migrated_per_app_files_untouched(self):
        # Migration negative: /sboms/ contains only per-app subdirectories (already migrated) —
        # no flat files to delete, per-app files must survive intact.
        case_dir = self._prepare_case_dir("UC-SBOM-MIG-NEGATIVE-2")
        sboms_dir = case_dir / "sboms"
        sboms_dir.mkdir()
        config_dir = case_dir / "configuration"
        config_dir.mkdir()
        (config_dir / "config.yml").write_text("sbom_retention:\n  enabled: true\n  keep_versions_per_app: 10\n")

        app_a_dir = sboms_dir / "app-a"
        app_a_dir.mkdir()
        for i in range(3):
            TestHelpers.create_file(app_a_dir / f"app-a-{i}.sbom.json", size=100)

        sboms_retention_policy()

        remaining = list(app_a_dir.iterdir())
        assert len(remaining) == 3, \
            f"per-app files must not be deleted when already in new layout;\n{_dump_dir(app_a_dir)}"


class TestSbomRetentionBackwardCompat(BaseTest):
    """Backward compatibility: old/incomplete config shapes must not crash the policy."""

    def setup_method(self):
        self.feature_dir = self.output_dir / FEATURE_TEST_DIR / "backward_compat"
        self.feature_dir.mkdir(parents=True, exist_ok=True)
        self.set_ci_project_dir(self.feature_dir)

    def _prepare(self, name: str) -> tuple[Path, Path]:
        case_dir = self.feature_dir / name
        if case_dir.exists():
            shutil.rmtree(case_dir)
        case_dir.mkdir(parents=True)
        self.set_ci_project_dir(case_dir)
        sboms_dir = case_dir / "sboms"
        sboms_dir.mkdir()
        return case_dir, sboms_dir

    def test_no_config_file_disables_policy(self, caplog):
        # Old repos may have no configuration/config.yml at all.
        # get_envgene_config_yaml returns an empty map on FileNotFoundError →
        # sbom_retention section absent → disabled branch fires, no files deleted.
        case_dir, sboms_dir = self._prepare("no-config-file")
        app_dir = sboms_dir / "app-a"
        app_dir.mkdir()
        TestHelpers.create_file(app_dir / "app-a-1.0.sbom.json", size=100)

        with caplog.at_level(logging.INFO, logger="envgene"):
            sboms_retention_policy()

        assert "disabled" in caplog.text.lower(), \
            f"expected 'disabled' log; got:\n{caplog.text}"
        assert len(_files(app_dir)) == 1, \
            f"files must be untouched when config is absent;\n{_dump_dir(app_dir)}"

    def test_no_sbom_retention_section_disables_policy(self, caplog):
        # config.yml exists but has no sbom_retention key (common in older deployments).
        case_dir, sboms_dir = self._prepare("no-sbom-retention-section")
        _write(case_dir / "configuration" / "config.yml", "some_other_key: value\n")
        app_dir = sboms_dir / "app-a"
        app_dir.mkdir()
        TestHelpers.create_file(app_dir / "app-a-1.0.sbom.json", size=100)

        with caplog.at_level(logging.INFO, logger="envgene"):
            sboms_retention_policy()

        assert "disabled" in caplog.text.lower(), \
            f"expected 'disabled' log; got:\n{caplog.text}"
        assert len(_files(app_dir)) == 1, \
            f"files must be untouched when section is absent;\n{_dump_dir(app_dir)}"

    def test_enabled_without_keep_versions_skips_per_app_pruning(self, caplog):
        # keep_versions_per_app is optional (defaults to None in SbomRetentionConfig).
        # Per-app version pruning must be skipped; size check still runs but won't
        # trigger here (total size is tiny, well below the limit).
        case_dir, sboms_dir = self._prepare("enabled-no-keep-versions")
        _write(case_dir / "configuration" / "config.yml",
               "sbom_retention:\n  enabled: true\n")
        app_dir = sboms_dir / "app-a"
        app_dir.mkdir()
        for i in range(5):
            TestHelpers.create_file(app_dir / f"app-a-{i}.sbom.json", size=100)

        with caplog.at_level(logging.INFO, logger="envgene"):
            sboms_retention_policy()

        assert len(_files(app_dir)) == 5, \
            f"all files must survive when keep_versions_per_app is absent;\n{_dump_dir(app_dir)}"

    def test_keep_versions_zero_raises_validation_error(self):
        # keep_versions_per_app: 0 is invalid — gt=0 constraint in SbomRetentionConfig.
        # Zero would silently wipe all SBOM files, so it is explicitly disallowed.
        case_dir, sboms_dir = self._prepare("keep-versions-zero")
        _write(case_dir / "configuration" / "config.yml",
               "sbom_retention:\n  enabled: true\n  keep_versions_per_app: 0\n")
        app_dir = sboms_dir / "app-a"
        app_dir.mkdir()
        for i in range(3):
            TestHelpers.create_file(app_dir / f"app-a-{i}.sbom.json", size=100)

        with pytest.raises(ValidationError):
            sboms_retention_policy()
