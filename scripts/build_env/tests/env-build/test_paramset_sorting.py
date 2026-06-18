"""
Paramset sorting integration tests.

sort_paramsets_with_same_name receives a list of paramset records whose
filePath values are real on-disk paths.  At runtime these files are discovered
by walking the render directory tree; the sort order determines merge
precedence.  Integration pattern: each test creates the actual YAML files
referenced by filePath entries so the test mirrors the exact runtime data flow.
"""
import os
import sys
from pathlib import Path

import yaml

from scripts.build_env.tests.base_test import BaseTest

os.environ.setdefault("ENVIRONMENT_NAME", "env-01")
os.environ.setdefault("CLUSTER_NAME", "cluster-01")

_BUILD_ENV = Path(__file__).resolve().parents[2]
if str(_BUILD_ENV) not in sys.path:
    sys.path.insert(0, str(_BUILD_ENV))

from build_env import sort_paramsets_with_same_name

FEATURE_TEST_DIR = "test_paramset_sorting"


def _write_paramset(path: Path, content: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(content, default_flow_style=False, allow_unicode=True))


def _entry(path: Path, env_specific: bool) -> dict:
    return {"filePath": str(path), "envSpecific": env_specific}


class TestSortParamsetsWithSameName(BaseTest):

    def setup_method(self):
        self.feature_dir = self.output_dir / FEATURE_TEST_DIR
        self.feature_dir.mkdir(parents=True, exist_ok=True)
        self.render_dir = self.feature_dir / "render" / "parameters"

    def test_all_three_levels(self):
        from_template = self.render_dir / "from_template" / "test.yml"
        plain = self.render_dir / "test.yml"
        from_instance = self.render_dir / "from_instance" / "test.yml"

        _write_paramset(from_template, {"param": "template-value"})
        _write_paramset(plain, {"param": "plain-value"})
        _write_paramset(from_instance, {"param": "instance-value"})

        entries = [
            _entry(from_instance, env_specific=True),
            _entry(plain, env_specific=False),
            _entry(from_template, env_specific=False),
        ]
        sorted_entries = sort_paramsets_with_same_name(entries)
        assert "from_template" in sorted_entries[0]["filePath"]
        assert "from_instance" not in sorted_entries[1]["filePath"]
        assert "from_instance" in sorted_entries[2]["filePath"]

    def test_template_and_instance(self):
        from_template = self.render_dir / "from_template" / "test.yml"
        from_instance = self.render_dir / "from_instance" / "test.yml"

        _write_paramset(from_template, {"param": "template-value"})
        _write_paramset(from_instance, {"param": "instance-value"})

        entries = [
            _entry(from_instance, env_specific=True),
            _entry(from_template, env_specific=False),
        ]
        sorted_entries = sort_paramsets_with_same_name(entries)
        assert "from_template" in sorted_entries[0]["filePath"]
        assert "from_instance" in sorted_entries[1]["filePath"]

    def test_origin_peer_templates(self):
        from_instance = self.render_dir / "from_instance" / "test.yml"
        from_template = self.render_dir / "from_template" / "test.yml"
        from_peer = self.render_dir / "from_peer_template" / "test.yml"
        from_origin = self.render_dir / "from_origin_template" / "test.yml"

        for p in [from_instance, from_template, from_peer, from_origin]:
            _write_paramset(p, {"param": p.parent.name})

        entries = [
            _entry(from_instance, env_specific=True),
            _entry(from_template, env_specific=False),
            _entry(from_peer, env_specific=False),
            _entry(from_origin, env_specific=False),
        ]
        sorted_entries = sort_paramsets_with_same_name(entries)
        assert "from_origin_template" in sorted_entries[0]["filePath"]
        assert "from_peer_template" in sorted_entries[1]["filePath"]
        assert "from_template" in sorted_entries[2]["filePath"]
        assert "from_instance" in sorted_entries[3]["filePath"]

    def test_multiple_files_sorted_alphabetically(self):
        files = [
            self.render_dir / "from_template" / "z_params.yml",
            self.render_dir / "from_template" / "a_params.yml",
            self.render_dir / "from_template" / "m_params.yml",
        ]
        for f in files:
            _write_paramset(f, {"param": f.stem})

        entries = [_entry(f, env_specific=False) for f in files]
        sorted_entries = sort_paramsets_with_same_name(entries)
        paths = [e["filePath"] for e in sorted_entries]
        assert paths == sorted(paths)

    def test_real_world_dcl_e2e(self):
        from_instance = self.render_dir / "from_instance" / "DCL_E2E_parameters.yaml"
        from_template = self.render_dir / "from_template" / "e2e" / "dcl.yaml"

        _write_paramset(from_instance, {"DCL_ENDPOINT": "https://dcl.instance.com"})
        _write_paramset(from_template, {"DCL_ENDPOINT": "https://dcl.template.com"})

        entries = [
            _entry(from_instance, env_specific=True),
            _entry(from_template, env_specific=False),
        ]
        sorted_entries = sort_paramsets_with_same_name(entries)
        assert "from_template" in sorted_entries[0]["filePath"]
        assert "from_instance" in sorted_entries[1]["filePath"]

    def test_empty_list(self):
        assert len(sort_paramsets_with_same_name([])) == 0
