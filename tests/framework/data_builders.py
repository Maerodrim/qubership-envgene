import os
import time
import yaml

class DataBuilder:
    """A fluent API to emulate user actions and create physical test data on disk."""

    def __init__(self, workspace):
        self.workspace = workspace

    def create_mock_sboms(self, app_name: str, count: int, size_mb: float = 0):
        """Creates dummy SBOM files with different modification times.
        Optionally generates a sparse file to simulate large total size instantly."""
        app_dir = self.workspace.sboms_dir / app_name
        app_dir.mkdir(parents=True, exist_ok=True)

        base_time = time.time() - (count * 100)
        for i in range(count):
            file_path = app_dir / f"{app_name}-v{i}.sbom.json"

            if i == 0 and size_mb > 0:
                with open(file_path, "wb") as f:
                    f.seek(int(size_mb * 1024 * 1024) - 1)
                    f.write(b"\0")
            else:
                file_path.touch()

            mod_time = base_time + (i * 100)
            os.utime(file_path, (mod_time, mod_time))

    def modify_first_sbom_size(self, app_name: str, size_mb: float):
        """Finds the first generated SBOM and inflates it via sparse generation."""
        app_dir = self.workspace.sboms_dir / app_name
        target_file = list(app_dir.glob("*.sbom.json"))[0]

        with open(target_file, "r+b") as f:
            f.seek(int(size_mb * 1024 * 1024) - 1)
            f.write(b"\0")

    def create_regdef(self, app_name: str, content: dict = None):
        """Placeholder for creating RegDef files."""
        pass

    def create_cloud_passport(self, app_name: str, content: dict = None):
        """Placeholder for creating Cloud Passports."""
        pass

    def get_env_dir(self, cluster_name: str, env_name: str):
        """Returns the physical environment directory for a specific cluster and env."""
        d = self.workspace.base_dir / "environments" / cluster_name / env_name
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def env_dir(self):
        """Returns the physical environment directory for the default test cluster/env."""
        return self.get_env_dir("test-cluster", "test-env")

    def set_bg_state_files(self, origin_state: str = None, peer_state: str = None, cluster: str = "test-cluster", env: str = "test-env"):
        """Creates physical state files (.origin-X, .peer-Y) in the environment directory."""
        env_dir = self.get_env_dir(cluster, env)
        if origin_state:
            (env_dir / f".origin-{origin_state}").touch()
        if peer_state:
            (env_dir / f".peer-{peer_state}").touch()

    def create_bg_namespaces(self, origin_ns: str, peer_ns: str, different_content: bool = False, cluster: str = "test-cluster", env: str = "test-env"):
        """Generates namespace folders and definition files for BG copy operations."""
        env_dir = self.get_env_dir(cluster, env)
        ns_dir = env_dir / "Namespaces"
        origin_dir = ns_dir / origin_ns
        peer_dir = ns_dir / peer_ns

        origin_dir.mkdir(parents=True, exist_ok=True)
        peer_dir.mkdir(parents=True, exist_ok=True)

        with open(origin_dir / "namespace.yml", "w") as f:
            yaml.dump({"name": origin_ns}, f)
        with open(peer_dir / "namespace.yml", "w") as f:
            yaml.dump({"name": peer_ns}, f)

        if different_content:
            with open(origin_dir / "manifest.yaml", "w") as f:
                f.write("content: origin-data")
            with open(peer_dir / "manifest.yaml", "w") as f:
                f.write("content: peer-data")

    def create_inventory_file(self, cluster_name: str, env_name: str, content: dict):
        """Creates env_definition.yml for a given environment."""
        inv_dir = self.get_env_dir(cluster_name, env_name) / "Inventory"
        inv_dir.mkdir(parents=True, exist_ok=True)
        with open(inv_dir / "env_definition.yml", "w") as f:
            yaml.dump(content, f)

    def create_paramset_file(self, place: str, name: str, content: dict, cluster: str = "test-cluster", env: str = "test-env"):
        """Creates a paramset file at the specified scope (env, cluster, site)."""
        base_dir = self.workspace.base_dir / "environments"
        if place == "env":
            target = base_dir / cluster / env / "Inventory" / "parameters"
        elif place == "cluster":
            target = base_dir / cluster / "Inventory" / "parameters"
        else:
            target = base_dir / "Inventory" / "parameters"
        target.mkdir(parents=True, exist_ok=True)
        with open(target / f"{name}.yml", "w") as f:
            yaml.dump(content, f)

    def create_credentials_file(self, place: str, name: str, content: dict, cluster: str = "test-cluster", env: str = "test-env"):
        """Creates a credentials file at the specified scope (env, cluster, site)."""
        base_dir = self.workspace.base_dir / "environments"
        if place == "env":
            target = base_dir / cluster / env / "Inventory" / "credentials"
        elif place == "cluster":
            target = base_dir / cluster / "Inventory" / "credentials"
        else:
            target = base_dir / "credentials"
        target.mkdir(parents=True, exist_ok=True)
        with open(target / f"{name}.yml", "w") as f:
            yaml.dump(content, f)

    def create_resource_profile_file(self, place: str, name: str, content: dict, cluster: str = "test-cluster", env: str = "test-env"):
        """Creates a resource profile file at the specified scope."""
        base_dir = self.workspace.base_dir / "environments"
        if place == "env":
            target = base_dir / cluster / env / "Inventory" / "resource_profiles"
        elif place == "cluster":
            target = base_dir / cluster / "resource_profiles"
        else:
            target = base_dir / "resource_profiles"
        target.mkdir(parents=True, exist_ok=True)
        with open(target / f"{name}.yml", "w") as f:
            yaml.dump(content, f)

    def create_shared_template_vars_file(self, place: str, name: str, content: dict, cluster: str = "test-cluster", env: str = "test-env"):
        """Creates a shared template variables file at the specified scope."""
        base_dir = self.workspace.base_dir / "environments"
        if place == "env":
            target = base_dir / cluster / env / "shared-template-variables"
        elif place == "cluster":
            target = base_dir / cluster / "shared-template-variables"
        else:
            target = base_dir / "shared-template-variables"
        target.mkdir(parents=True, exist_ok=True)
        with open(target / f"{name}.yml", "w") as f:
            yaml.dump(content, f)

    def create_template_descriptor(self, cluster: str, env: str, namespaces: list):
        """Creates an env_template.yml descriptor mock for template generation."""
        td_dir = self.workspace.base_dir / "templates"
        td_dir.mkdir(parents=True, exist_ok=True)

        content = {"namespaces": namespaces}
        with open(td_dir / "env_template.yml", "w") as f:
            yaml.dump(content, f)

        self.workspace.config_data["env_templates_dir"] = str(td_dir).replace('\\', '/')

    def create_artifact_def(self, app_name: str, content: dict):
        """Creates an artifact definition file for the given app name."""
        target_dir = self.workspace.config_dir / "artifact_definitions"
        target_dir.mkdir(parents=True, exist_ok=True)
        with open(target_dir / f"{app_name}.yaml", "w") as f:
            yaml.dump(content, f)
