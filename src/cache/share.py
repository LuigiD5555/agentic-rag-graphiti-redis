"""
CLI to share/unshare documents in Weaviate by updating payload fields.

Usage:
  python -m src.cache.share --id <hash_or_external_id> --visibility public|private [--tenant TENANT]
  python -m src.cache.share --id <hash_or_external_id> --grant user1,user2      [--tenant TENANT]
"""

import argparse
import weaviate
from weaviate.classes.init import AdditionalConfig, Timeout
from weaviate.classes.query import Filter
from src.config.settings import Config
from src.audit.logger import audit  # keep your existing audit hook


def _get_client(cfg: Config) -> weaviate.WeaviateClient:
    additional = AdditionalConfig(timeout=Timeout(init=cfg.WEAVIATE_TIMEOUT, query=cfg.WEAVIATE_TIMEOUT))
    if cfg.WEAVIATE_API_KEY:
        return weaviate.WeaviateClient(
            url=cfg.WEAVIATE_URL,
            auth_client_secret=weaviate.auth.AuthApiKey(api_key=cfg.WEAVIATE_API_KEY),
            additional_config=additional,
        )
    return weaviate.WeaviateClient(url=cfg.WEAVIATE_URL, additional_config=additional)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True, help="Document external_id or hash")
    ap.add_argument("--visibility", choices=["public", "private"], help="Set new visibility")
    ap.add_argument("--grant", help="Comma-separated user IDs to add to allowed_user_ids")
    ap.add_argument("--tenant", help="Tenant/namespace (if multitenancy enabled)")
    args = ap.parse_args()

    cfg = Config()
    client = _get_client(cfg)
    coll = client.collections.get(cfg.WEAVIATE_CLASS)
    if cfg.WEAVIATE_MULTI_TENANCY and args.tenant:
        coll = coll.with_tenant(args.tenant)

    # Find object by external_id or hash
    where = Filter.by_property("external_id").equal(args.id) | Filter.by_property("hash").equal(args.id)
    res = coll.query.fetch_objects(where=where, limit=2)
    objs = getattr(res, "objects", []) or []  # type: ignore
    if not objs:
        print("No object found with that id/hash")
        return
    if len(objs) > 1:
        print("Warning: multiple objects matched; updating the first one.")

    obj = objs[0]
    props = getattr(obj, "properties", {}) or {}
    changed = False

    if args.visibility:
        props["visibility"] = args.visibility
        changed = True

    if args.grant:
        users = [u.strip() for u in args.grant.split(",") if u.strip()]
        allow = set(props.get("allowed_user_ids") or [])
        allow.update(users)
        props["allowed_user_ids"] = sorted(allow)
        changed = True

    if changed:
        coll.data.update(uuid=str(obj.uuid), properties=props)
        audit("share_update", {"doc_id": str(obj.uuid), "properties": props})
        print("Updated sharing settings for", obj.uuid)
    else:
        print("Nothing to change.")


if __name__ == "__main__":
    main()
