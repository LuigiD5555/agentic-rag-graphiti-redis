from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Optional

import weaviate
from weaviate.collections.classes.filters import Filter
from weaviate.exceptions import UnexpectedStatusCodeError

from src import logger
from src.workflows.query.audit.decorators import logged, timed


WeaviateFilter = Any


@dataclass
class ScoredItem:
    id: str
    score: Optional[float]
    payload: Dict[str, Any]


class WeaviateRepository:
    def __init__(self, schema):
        self.schema = schema
        self.client: weaviate.WeaviateClient = schema.client

    def _coll(self, tenant_id: Optional[str]):
        return self.schema.coll(tenant_id)

    @logged("Upserting record into Weaviate")
    @timed()
    def upsert(
        self,
        key: Optional[str],
        vector: List[float],
        metadata: Dict[str, Any],
        tenant_id: Optional[str] = None,
    ) -> None:
        coll = self._coll(tenant_id)

        raw_id = key or metadata.get("hash") or metadata.get("external_id")
        if not raw_id:
            raise ValueError("upsert requires a stable key/external_id/hash")
        uuid_id = self._normalize_uuid(raw_id)

        properties = dict(metadata)
        text_content = properties.pop("content", None) or properties.get("structure_summary") or ""
        properties["external_id"] = key or metadata.get("external_id") or metadata.get("hash") or raw_id

        self._upsert_record(coll, uuid_id, vector, properties, text_content)

    @logged("Batch upserting records into Weaviate")
    @timed()
    def batch_upsert(
        self,
        records: List[Dict[str, Any]],
        tenant_id: Optional[str] = None,
    ) -> None:
        """True batch upsert using Weaviate v4 batch API for maximum performance."""
        if not records:
            return

        coll = self._coll(tenant_id)

        with coll.batch.dynamic() as batch:
            for rec in records:
                key = rec.get("key")
                vector = rec.get("vector")
                metadata = dict(rec.get("metadata") or {})
                raw_id = key or metadata.get("hash") or metadata.get("external_id")

                if not raw_id:
                    logger.warning("Skipping batch record without key/hash/external_id")
                    continue

                uuid_id = self._normalize_uuid(raw_id)
                properties = dict(metadata)
                text_content = properties.pop("content", None) or properties.get("structure_summary") or ""
                properties["external_id"] = key or metadata.get("external_id") or metadata.get("hash") or raw_id
                properties["content"] = text_content

                batch.add_object(
                    properties=properties,
                    uuid=uuid_id,
                    vector=vector,
                )

        if hasattr(coll.batch, "failed_objects") and coll.batch.failed_objects:
            failed_count = len(coll.batch.failed_objects)
            logger.warning("Batch upsert had %d failures", failed_count)
            for i, failure in enumerate(coll.batch.failed_objects[:5]):
                logger.warning("Batch failure %d: %s", i + 1, failure)

    def _upsert_record(
        self,
        coll,
        uuid_id: str,
        vector: List[float],
        properties: Dict[str, Any],
        text: str,
    ) -> None:
        """Optimized upsert for Weaviate collections.

        Strategy:
            1) Check if the object exists first (avoids unnecessary 422 errors)
            2) If exists, use `replace` directly
            3) If not exists, use `insert`
            4) Handle edge cases with fallback logic

        This approach minimizes HTTP errors in logs and improves performance
        by avoiding the INSERT-422-REPLACE pattern.
        """
        payload = {**properties, "content": text}

        # Check if object exists first
        try:
            exists = coll.data.exists(uuid=uuid_id)
        except Exception as check_exc:
            logger.debug("Failed to check existence for uuid=%s: %s, falling back to insert-first", uuid_id, check_exc)
            exists = False

        if exists:
            # Object exists, use replace
            try:
                coll.data.replace(uuid=uuid_id, properties=payload, vector=vector)
                return
            except UnexpectedStatusCodeError as replace_exc:
                dim_mismatch = self._detect_vector_dimension_mismatch(replace_exc)
                if dim_mismatch is not None:
                    raise RuntimeError(self._format_vector_dimension_mismatch_error(*dim_mismatch)) from replace_exc
                if self._is_not_found_error(replace_exc):
                    # Race condition: object was deleted between check and replace
                    logger.debug("Object was deleted during replace for uuid=%s, inserting instead", uuid_id)
                    coll.data.insert(uuid=uuid_id, properties=payload, vector=vector)
                    return
                logger.exception("Replace operation failed for uuid=%s", uuid_id)
                raise
            except Exception as exc:
                logger.exception("Unexpected error during replace for uuid=%s: %s", uuid_id, exc)
                raise
        else:
            # Object doesn't exist, use insert
            try:
                coll.data.insert(uuid=uuid_id, properties=payload, vector=vector)
                return
            except UnexpectedStatusCodeError as insert_exc:
                dim_mismatch = self._detect_vector_dimension_mismatch(insert_exc)
                if dim_mismatch is not None:
                    raise RuntimeError(self._format_vector_dimension_mismatch_error(*dim_mismatch)) from insert_exc
                if self._is_duplicate_insert_error(insert_exc):
                    # Race condition: object was created between check and insert
                    logger.debug("Object was created during insert for uuid=%s, replacing instead", uuid_id)
                    coll.data.replace(uuid=uuid_id, properties=payload, vector=vector)
                    return
                logger.exception("Insert operation failed for uuid=%s", uuid_id)
                raise
            except Exception as exc:
                logger.exception("Unexpected error during insert for uuid=%s: %s", uuid_id, exc)
                raise

    @staticmethod
    def _is_not_found_error(exc: UnexpectedStatusCodeError) -> bool:
        """Return True when Weaviate indicates a missing object/UUID.

        Handles both:
            - status_code == 404
            - status_code == 500 with body/message including "no object with id '<uuid>'"
        """
        status = getattr(exc, "status_code", None)
        if status == 404:
            return True

        # Try to extract a meaningful error text from the exception.
        text = ""
        for attr in ("message", "body", "response", "response_text", "error"):
            value = getattr(exc, attr, None)
            if value:
                text = str(value)
                break
        if not text:
            text = str(exc)

        low = text.lower()
        return ("no object with id" in low) or ("not found" in low)

    @staticmethod
    def _extract_error_text(exc: Exception) -> str:
        for attr in ("message", "body", "response", "response_text", "error"):
            value = getattr(exc, attr, None)
            if value:
                return str(value)
        return str(exc)

    @classmethod
    def _detect_vector_dimension_mismatch(
        cls, exc: UnexpectedStatusCodeError
    ) -> tuple[int, int] | None:
        """Detect Weaviate vector dimension mismatch errors.

        Example message:
            "new node has a vector with length 768. Existing nodes have vectors with length 384"
        Returns:
            (new_dim, existing_dim) or None
        """
        text = cls._extract_error_text(exc)
        low = text.lower()
        if "vector dimensions do not match" not in low:
            return None

        import re

        match = re.search(
            r"new node has a vector with length (\d+)\.\s*existing nodes have vectors with length (\d+)",
            low,
        )
        if not match:
            return None
        return (int(match.group(1)), int(match.group(2)))

    @staticmethod
    def _format_vector_dimension_mismatch_error(new_dim: int, existing_dim: int) -> str:
        return (
            "Weaviate rejected the upsert due to a vector dimension mismatch.\n"
            f"- New vector length: {new_dim}\n"
            f"- Existing index length: {existing_dim}\n\n"
            "Fix options:\n"
            "1) Use the same embedding model/dimension as the existing index "
            f"(set EMBEDDING_DIM={existing_dim} and ensure your embedding provider returns that length).\n"
            "2) Reset/recreate the Weaviate collection/volume (destructive):\n"
            "   - podman-compose down\n"
            "   - podman volume ls | rg weaviate_data\n"
            "   - podman volume rm <your_project>_weaviate_data\n"
            "   - podman-compose up -d\n"
            "3) Use a different WEAVIATE_CLASS (new collection name) for the new embedding dimension.\n"
        )

    @staticmethod
    def _is_duplicate_insert_error(exc: UnexpectedStatusCodeError) -> bool:
        """
        Weaviate can return 409 Conflict for duplicates, and sometimes 422 with a
        duplicate/exists message. Do not treat all 422 as duplicates, because
        they can be schema/tenant validation errors.
        """
        status = getattr(exc, "status_code", None)
        if status == 409:
            return True
        if status != 422:
            return False

        text = ""
        for attr in ("message", "body", "response", "response_text", "error"):
            value = getattr(exc, attr, None)
            if value:
                text = str(value)
                break
        if not text:
            text = str(exc)

        low = text.lower()
        duplicate_markers = (
            "already exists",
            "already present",
            "conflict",
            "duplicate",
            "object exists",
            "id already",
        )
        return any(marker in low for marker in duplicate_markers)

    def _update_existing(self, coll, uuid_id: str, payload: Dict[str, Any], vector: List[float]) -> None:
        try:
            coll.data.update(uuid=uuid_id, properties=payload, vector=vector)
        except UnexpectedStatusCodeError as exc:
            if self._is_not_found_error(exc):
                logger.warning(
                    "Weaviate reported not-found while updating uuid=%s; reinserting payload.",
                    uuid_id,
                )
                coll.data.insert(uuid=uuid_id, properties=payload, vector=vector)
                return
            logger.exception("Weaviate update failed for uuid=%s", uuid_id)
            raise
        except Exception:
            logger.exception("Weaviate update failed for uuid=%s", uuid_id)
            raise

    def _build_where(
        self, filters: Optional[Dict[str, Any]], 
        include_archived: bool = False
    ) -> Optional[WeaviateFilter]:
        """Build a Weaviate filter expression for collection queries.

        Typing note:
            The Weaviate v4 client returns an internal filter chain type (e.g. `_Filters`)
            from methods like `Filter.by_property(...).equal(...)`. That internal type is
            runtime-compatible with the SDK operators (`&`, `|`) but does not match the
            public `Filter` class in type checkers (Pylance/Mypy).

            We therefore expose the return type as `Optional[Any]` via `WeaviateFilter`
            to avoid false positives while preserving correct runtime behavior.
        """
        archive_filter: WeaviateFilter = Filter.by_property("archived").equal(include_archived)
        if not filters:
            return archive_filter

        shoulds: List[WeaviateFilter] = []

        # Keep your existing logic (always filtering to public in current implementation).
        if filters.get("visibility") == "public":
            shoulds.append(Filter.by_property("visibility").equal("public"))
        else:
            shoulds.append(Filter.by_property("visibility").equal("public"))

        owner_id = filters.get("owner_id")
        if owner_id:
            shoulds.append(Filter.by_property("owner_id").equal(owner_id))

        user_id = filters.get("user_id")
        if user_id:
            shoulds.append(Filter.by_property("allowed_user_ids").contains_any([user_id]))
            shoulds.append(Filter.by_property("owner_id").equal(user_id))

        combined: WeaviateFilter = shoulds[0]
        for s in shoulds[1:]:
            combined = combined | s

        return archive_filter & combined

    def exists(self, point_id: str, tenant_id: Optional[str] = None) -> bool:
        """Check whether a record exists in Weaviate."""
        coll = self._coll(tenant_id)
        uuid_id = self._normalize_uuid(point_id)
        return bool(coll.data.exists(uuid=uuid_id))

    @logged("Batch checking existence in Weaviate")
    @timed()
    def batch_exists(
        self,
        point_ids: List[str],
        tenant_id: Optional[str] = None,
    ) -> Dict[str, bool]:
        """
        Check existence of multiple records in batch.
        
        Args:
            point_ids: List of point IDs to check
            tenant_id: Optional tenant ID
            
        Returns:
            Dict mapping point_id -> exists (True/False)
        """
        if not point_ids:
            return {}
        
        coll = self._coll(tenant_id)
        results = {}
        
        # Process in batches to avoid overwhelming Weaviate
        batch_size = 100
        for i in range(0, len(point_ids), batch_size):
            batch = point_ids[i:i + batch_size]
            
            # Check each ID in the batch
            for point_id in batch:
                uuid_id = self._normalize_uuid(point_id)
                try:
                    exists = bool(coll.data.exists(uuid=uuid_id))
                    results[point_id] = exists
                except Exception as e:
                    logger.warning("Error checking existence for %s: %s", point_id, e)
                    results[point_id] = False
        
        return results

    @staticmethod
    def _normalize_uuid(value: Any) -> str:
        import uuid

        try:
            return str(uuid.UUID(str(value)))
        except (ValueError, AttributeError, TypeError):
            return str(uuid.uuid5(uuid.NAMESPACE_URL, str(value)))

    @logged("Executing Weaviate search")
    @timed()
    def search(
        self,
        vector: List[float],
        top_k: int = 5,
        filters: Optional[Dict[str, Any]] = None,
        tenant_id: Optional[str] = None,
    ) -> List[ScoredItem]:
        coll = self._coll(tenant_id)
        where = self._build_where(filters, include_archived=False)

        def _run_query(active_filters: Optional[Filter]):
            return coll.query.near_vector(
                vector=vector,
                limit=top_k,
                filters=active_filters,
            )

        result = _run_query(where)
        objects = getattr(result, "objects", []) or []  # type: ignore[attr-defined]
        if not objects:
            archived_where = self._build_where(filters, include_archived=True)
            result = _run_query(archived_where)
            objects = getattr(result, "objects", []) or []  # type: ignore[attr-defined]

        output: List[ScoredItem] = []
        for obj in objects:
            meta = getattr(obj, "metadata", None)
            distance = getattr(meta, "distance", None)
            # Convert distance to similarity score for cosine distance
            # distance: 0 = identical, 2 = opposite
            # similarity: 1 = identical, -1 = opposite
            if distance is not None:
                # Convert cosine distance to similarity: similarity = 1 - distance
                score = 1.0 - float(distance)
            else:
                score = None
            props = getattr(obj, "properties", {}) or {}
            output.append(ScoredItem(id=str(obj.uuid), score=score, payload=props))
        return output

    def iter_payloads(self, batch_size: int = 256, tenant_id: Optional[str] = None) -> Iterator[Dict[str, Any]]:
        coll = self._coll(tenant_id)
        cursor: Optional[str] = None

        while True:
            result = coll.query.fetch_objects(limit=batch_size, after=cursor)
            objects = getattr(result, "objects", []) or []  # type: ignore[attr-defined]
            if not objects:
                break

            for obj in objects:
                yield getattr(obj, "properties", {}) or {}

            # In the weaviate-client v4, cursor-based pagination uses the UUID
            # of the last returned object as the `after` value for the next page.
            last_uuid = getattr(objects[-1], "uuid", None)
            if last_uuid is None or len(objects) < batch_size:
                break
            cursor = str(last_uuid)

    def archive_file(self, file_id: str, tenant_id: Optional[str] = None) -> None:
        coll = self._coll(tenant_id)
        where = Filter.by_property("file_id").equal(file_id)
        PAGE = 200
        offset = 0

        while True:
            # Weaviate cursor API (after+limit) cannot be combined with filters.
            # Use offset-based pagination instead when a where filter is present.
            result = coll.query.fetch_objects(limit=PAGE, offset=offset, filters=where)
            objects = getattr(result, "objects", []) or []  # type: ignore[attr-defined]
            if not objects:
                break

            for obj in objects:
                uuid_id = getattr(obj, "uuid", None)
                if not uuid_id:
                    continue
                coll.data.update(uuid=uuid_id, properties={"archived": True})

            if len(objects) < PAGE:
                break
            offset += PAGE

    def upsert_failure(self, record: Dict[str, Any]) -> None:
        logger.warning("Failure record: %s", record)

    def __del__(self) -> None:
        try:
            if hasattr(self, "client") and isinstance(self.client, weaviate.WeaviateClient):
                self.client.close()
        except (AttributeError, TypeError, UnexpectedStatusCodeError, OSError, RuntimeError) as exc:
            logger.debug("Ignoring exception while closing Weaviate client: %s", exc)
