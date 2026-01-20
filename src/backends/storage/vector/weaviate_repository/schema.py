# -*- coding: utf-8 -*-
from typing import Any, Callable, List, Optional

from weaviate.classes.config import Configure, Property
from weaviate.collections.classes.config_vectorizers import VectorDistances

from src import logger


class SchemaManager:
    """Manage Weaviate collection schema and multi-tenancy tenant setup.

    This class supports the Weaviate Python client v4 vector configuration API.
    """

    def __init__(
        self,
        client,
        cfg: Any,
        class_name: str,
        multitenant_enabled: bool,
        default_tenant: Optional[str],
        class_properties_provider: Callable[[], List[Property]],
    ) -> None:
        """Initialize schema manager.

        Args:
            client: Connected Weaviate client instance (v4).
            cfg: Application configuration.
            class_name: Collection name to ensure/create.
            multitenant_enabled: Whether multi-tenancy is enabled for the collection.
            default_tenant: Default tenant to ensure when multi-tenancy is enabled.
            class_properties_provider: Callable returning Weaviate Property definitions.
        """
        self.client = client
        self.cfg = cfg
        self.class_name = class_name
        self.multitenant_enabled = multitenant_enabled
        self.default_tenant = default_tenant
        self._class_properties_provider = class_properties_provider

    def ensure_class(self) -> None:
        """Backward-compatible entry point expected by the repository.

        Ensures the target collection exists; creates it if missing, and ensures
        the default tenant exists when multi-tenancy is enabled.
        """
        self.ensure()

    def ensure(self) -> None:
        """Ensure the target collection exists; create it if missing."""
        schema = self.client.collections
        existing_classes = schema.list_all()
        existing_names = [c.name if hasattr(c, "name") else str(c) for c in existing_classes]

        if self.class_name not in existing_names:
            self._create_class(schema)

        if self.multitenant_enabled and self.default_tenant:
            self._ensure_default_tenant()

    def coll(self, tenant_id: Optional[str]):
        """Get the collection handle, optionally bound to a tenant."""
        collection = self.client.collections.get(self.class_name)
        if not self.multitenant_enabled:
            return collection

        effective_tenant = tenant_id or self.default_tenant
        if not effective_tenant:
            raise RuntimeError(
                "Weaviate multi-tenancy is enabled but no tenant_id was provided. "
                "Set WEAVIATE_DEFAULT_TENANT or pass tenant_id explicitly."
            )
        return collection.with_tenant(str(effective_tenant))

    def _create_class(self, schema) -> None:
        """Create the collection using the updated v4 vector configuration API.

        For 'bring your own vectors' setups (your embeddings come from LM Studio),
        use self-provided vectors to avoid server-side vectorization.
        """
        # Use configurable HNSW parameters from settings (memory optimization)
        hnsw_ef_construction = getattr(self.cfg, 'WEAVIATE_HNSW_EF_CONSTRUCTION', 128)
        hnsw_max_connections = getattr(self.cfg, 'WEAVIATE_HNSW_MAX_CONNECTIONS', 32)
        hnsw_distance_metric = getattr(self.cfg, 'WEAVIATE_HNSW_DISTANCE_METRIC', 'cosine')

        # Convert string distance metric to VectorDistances enum
        distance_metric_map = {
            'cosine': VectorDistances.COSINE,
            'l2': VectorDistances.L2_SQUARED,
            'dot': VectorDistances.DOT,
            'hamming': VectorDistances.HAMMING,
            'manhattan': VectorDistances.MANHATTAN,
        }
        
        # Get the distance metric from config, default to COSINE if not found
        distance_metric = distance_metric_map.get(hnsw_distance_metric.lower(), VectorDistances.COSINE)

        schema.create(
            self.class_name,
            vectorizer_config=None,  # Use None instead of Configure.Vectorizer.none() to avoid named vectors conflict
            vector_index_config=Configure.VectorIndex.hnsw(
                distance_metric=distance_metric,
                ef_construction=hnsw_ef_construction,
                max_connections=hnsw_max_connections,
            ),
            properties=self._class_properties_provider(),
            multi_tenancy_config=Configure.multi_tenancy(enabled=self.multitenant_enabled),
        )
        logger.info(
            "Created Weaviate class '%s' (multitenant=%s, HNSW: ef=%d, max_conn=%d)",
            self.class_name,
            self.multitenant_enabled,
            hnsw_ef_construction,
            hnsw_max_connections,
        )

    def _ensure_default_tenant(self) -> None:
        """Ensure configured default tenant exists when multi-tenancy is enabled."""
        collection = self.client.collections.get(self.class_name)
        tenants_api = collection.tenants

        try:
            tenants_api.create([self.default_tenant])
        except Exception as exc:
            # We do not want to fail if the tenant already exists.
            if "already exist" not in str(exc).lower():
                raise
