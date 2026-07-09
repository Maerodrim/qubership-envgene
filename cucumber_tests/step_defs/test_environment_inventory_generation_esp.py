from pytest_bdd import scenarios
from cucumber_tests.step_defs.common_steps import *
from cucumber_tests.step_defs.esp_steps import *
from cucumber_tests.step_defs.inventory_gen_steps import *

scenarios('../features/environment-inventory-generation-esp.feature')
