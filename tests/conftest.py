import pytest
from tests.framework.workspace import EnvGeneWorkspace
from tests.step_defs.common_steps import *

@pytest.fixture
def workspace(tmp_path):
    """
    Provides an isolated EnvGene E2E test workspace instance.
    This fixture abstracts the CI_PROJECT_DIR and handles test data generation.
    """
    return EnvGeneWorkspace(tmp_path)
