import os
import subprocess
import yaml
from pathlib import Path
from .data_builders import DataBuilder

class EnvGeneWorkspace:
    """Encapsulates the CI_PROJECT_DIR and handles execution of envgene modules in subprocess."""

    def __init__(self, tmp_path):
        self.base_dir = tmp_path
        self.config_dir = self.base_dir / "configuration"
        self.config_file = self.config_dir / "config.yml"
        self.config_data = {}

        # Standard EnvGene directories
        self.sboms_dir = self.base_dir / "sboms"
        self.inventory_dir = self.base_dir / "inventory"
        self.regdefs_dir = self.base_dir / "regdefs"
        self.blueprints_dir = self.base_dir / "blueprints"

        # Setup structure
        for d in [self.config_dir, self.sboms_dir, self.inventory_dir, self.regdefs_dir, self.blueprints_dir]:
            d.mkdir(parents=True, exist_ok=True)

        # Execution State
        self.stdout = ""
        self.stderr = ""

        # User Action Simulator
        self.builder = DataBuilder(self)

    def write_config(self):
        """Commits the current config_data to the physical config.yml"""
        with open(self.config_file, 'w') as f:
            yaml.dump(self.config_data, f)

    def run_module(self, module_name: str, extra_env: dict = None):
        """Executes a target python module with the correct envvars and pythonpath."""
        self.write_config()

        env = os.environ.copy()
        # Default E2E Variables
        env["CI_PROJECT_DIR"] = str(self.base_dir)
        env["SECRET_KEY"] = "test-secret"

        if extra_env:
            env.update(extra_env)

        # Setup PYTHONPATH to include project root, python modules, and scripts dir
        project_root = str(Path(__file__).parent.parent.parent.resolve())
        python_root = str(Path(project_root) / "python" / "envgene")
        artifact_searcher = str(Path(project_root) / "python" / "artifact-searcher")
        integration = str(Path(project_root) / "python" / "integration")
        jschon_sort = str(Path(project_root) / "python" / "jschon-sort")
        scripts_root = str(Path(project_root) / "scripts")
        env["PYTHONPATH"] = f"{project_root}{os.pathsep}{python_root}{os.pathsep}{artifact_searcher}{os.pathsep}{integration}{os.pathsep}{jschon_sort}{os.pathsep}{scripts_root}"

        import sys
        python_exe = sys.executable

        result = subprocess.run(
            [python_exe, "-m", module_name],
            env=env,
            capture_output=True,
            text=True,
            cwd=project_root
        )

        self.stdout = result.stdout
        self.stderr = result.stderr
        self.returncode = result.returncode
        return result

    def run_pipeline(self, extra_env: dict = None):
        """Executes the full EnvGene pipeline orchestrator, simulating a complete CI pipeline run."""
        env = {
            # Orchestrator requires ENV_NAMES to parse cluster and environment
            "ENV_NAMES": "test-cluster/test-env",
            "CLUSTER_NAME": "test-cluster",
            "ENVIRONMENT_NAME": "test-env",
            "FULL_ENV_NAME": "test-cluster/test-env"
        }
        if extra_env:
            env.update(extra_env)

        return self.run_module("scripts.pipeline.orchestrator", extra_env=env)
