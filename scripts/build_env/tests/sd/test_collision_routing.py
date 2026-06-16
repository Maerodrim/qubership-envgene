import os

from scripts.build_env.tests.base_test import BaseTest

os.environ.setdefault("ENVIRONMENT_NAME", "env-01")
os.environ.setdefault("CLUSTER_NAME", "cluster-01")

# ---------------------------------------------------------------------------
# Python reference implementation of Java collision routing
# (ParametersCalculationServiceV2.getCollisionParams)
# ---------------------------------------------------------------------------

# ApplicationConstants structural keys — never routed even if name matches a service
ENTITY_KEYS = {"services", "configurations", "frontends", "smartplug", "cdn", "sampleRepo"}


def _get_collision_params(parameters: dict) -> dict:
    """
    ParametersCalculationServiceV2.getCollisionParams (lines 259-276):
    - Extract service names from parameters["services"] (populated from SBOM).
    - Move every top-level key that matches a service name (and is not a reserved
      entity key) into the collision map; remove it from parameters in-place.
    - Return the collision map (written to collision-deployment-parameters.yaml).
    """
    service_map = parameters.get("services", {})
    services = set(service_map.keys())
    collision: dict = {}
    keys_to_remove = []
    for key, value in parameters.items():
        if key in services and key not in ENTITY_KEYS:
            collision[key] = value
            keys_to_remove.append(key)
    for key in keys_to_remove:
        del parameters[key]
    return collision


# ---------------------------------------------------------------------------
# UC-ES-DEP-20: Service-name collision routing
# ---------------------------------------------------------------------------

class TestCollisionRouting(BaseTest):
    """
    UC-ES-DEP-20 — A top-level deployment parameter whose name matches a SBOM
    service id is removed from deployment-parameters.yaml and written to
    collision-deployment-parameters.yaml.

    Rule (ParametersCalculationServiceV2.getCollisionParams lines 259-276):
      if services.contains(key) && !entities.contains(key) → collision
    """

    def test_service_named_key_moved_to_collision_and_removed_from_main(self):
        # UC-ES-DEP-20: key matching service id → in collision output, removed from main.
        params = {
            "services": {"orders-api": {}},
            "orders-api": {"replicaCount": 2},
            "CLOUD_API_HOST": "api.example.com",
        }
        collision = _get_collision_params(params)
        assert collision == {"orders-api": {"replicaCount": 2}}
        assert "orders-api" not in params
        assert "CLOUD_API_HOST" in params

    def test_non_service_named_key_stays_in_main_params(self):
        # UC-ES-DEP-20: key not in service names → not moved to collision.
        params = {
            "services": {"orders-api": {}},
            "CLOUD_API_HOST": "api.example.com",
        }
        collision = _get_collision_params(params)
        assert collision == {}
        assert "CLOUD_API_HOST" in params

    def test_multiple_service_keys_all_moved(self):
        # UC-ES-DEP-20: all keys whose names match service ids are moved.
        params = {
            "services": {"orders-api": {}, "inventory-svc": {}},
            "orders-api": {"replicaCount": 2},
            "inventory-svc": {"replicaCount": 1},
            "NAMESPACE": "pl-01",
        }
        collision = _get_collision_params(params)
        assert "orders-api" in collision
        assert "inventory-svc" in collision
        assert "orders-api" not in params
        assert "inventory-svc" not in params
        assert "NAMESPACE" in params

    def test_no_services_map_means_no_collision(self):
        # UC-ES-DEP-20 pre-req: when parameters contain no "services" key (no SBOM
        # services registered), no keys are routed to collision.
        params = {"orders-api": {"replicaCount": 2}, "NAMESPACE": "pl-01"}
        collision = _get_collision_params(params)
        assert collision == {}
        assert "orders-api" in params

    def test_entity_key_not_routed_even_if_it_matches_service_name(self):
        # UC-ES-DEP-20 exclusion: reserved entity keys (services, configurations,
        # frontends, smartplug, cdn, sampleRepo) are never moved to collision.
        # (ParametersCalculationServiceV2 line 269: !entities.contains(key))
        params = {
            "services": {"configurations": {}, "frontends": {}},
            "configurations": {"some": "value"},
            "frontends": {"other": "value"},
        }
        collision = _get_collision_params(params)
        assert collision == {}
        assert "configurations" in params
        assert "frontends" in params
