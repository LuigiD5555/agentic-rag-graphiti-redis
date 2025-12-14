# -*- coding: utf-8 -*-
from typing import Callable, List, Optional

from weaviate.classes.config import Configure, Property

from src.rag.conf import Config
from src import logger


class SchemaManager:
    """Encapsulates schema creation and tenant lifecycle concerns for Weaviate."""

    def __init__(
        self,
        client,
        cfg: Config,
        class_name: str,
        multitenant_enabled: bool,
        default_tenant: Optional[str],
        class_properties_provider: Callable[[], List[Property]],
    ) -> None:
        self.client = client
        self.cfg = cfg
        self.class_name = class_name
        self.multitenant_enabled = multitenant_enabled
        self.default_tenant = default_tenant
        self._class_properties_provider = class_properties_provider

    def ensure_class(self) -> None:
        """Ensure the target collection exists; create it if missing."""
        schema = self.client.collections
        existing_classes = schema.list_all()
        names = [c.name if hasattr(c, "name") else str(c) for c in existing_classes]
        if self.class_name not in names:
            self._create_class(schema)
        if self.multitenant_enabled and self.default_tenant:
            self._ensure_default_tenant()

    def coll(self, tenant_id: Optional[str]):
        """Get the collection handle, optionally bound to a tenant."""
        coll = self.client.collections.get(self.class_name)
        if not self.multitenant_enabled:
            return coll

        effective_tenant = tenant_id or self.default_tenant
        if not effective_tenant:
            raise RuntimeError(
                "Weaviate multi-tenancy is enabled but no tenant_id was provided. "
                "Set WEAVIATE_DEFAULT_TENANT or pass tenant_id explicitly."
            )
        return coll.with_tenant(str(effective_tenant))

    def _create_class(self, schema) -> None:
        """Create the collection with modern vector configuration."""
        schema.create(
            self.class_name,
            vectorizer_config=Configure.Vectorizer.none(),
            properties=self._class_properties_provider(),
            multi_tenancy_config=Configure.multi_tenancy(enabled=self.multitenant_enabled),
        )
        logger.info(
            "Created Weaviate class '%s' (multitenant=%s)",
            self.class_name,
            self.multitenant_enabled,
        )

    def _ensure_default_tenant(self) -> None:
        """Ensure configured default tenant exists when multi-tenancy is enabled."""
        collection = self.client.collections.get(self.class_name)
        tenants_api = collection.tenants
        try:
            tenants_api.create([self.default_tenant])
        except Exception as exc:
            if "already exist" not in str(exc).lower():
                raise
