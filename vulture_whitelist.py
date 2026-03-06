# vulture whitelist — false positives suppression
# Format: assign to a dummy object so vulture sees the names as "used".
# See: https://github.com/jendrikseipp/vulture#whitelists

from vulture.whitelist_utils import Whitelist

whitelist = Whitelist()

# --- __exit__ protocol (exc_type, exc_val, exc_tb) ---
# Python requires the full 3-argument signature even when not referenced.
whitelist.exc_value   # api/runtime.py
whitelist.exc_val     # searxng_client.py, resource_pools.py, watermark_cleanup.py, weaviate_retriever.py
whitelist.exc_tb      # searxng_client.py, resource_pools.py, watermark_cleanup.py, weaviate_retriever.py
whitelist.tb          # stage_reporting.py

# --- Abstract / interface method parameters (contract for subclasses) ---
whitelist.vector_size   # knowledge_source_interface.py — abstract method signature
whitelist.new_versions  # checkpointer.py — LangGraph override signature
whitelist.embedded      # wave_planner.py — abstract upsert_phase(embedded, wave_id)
whitelist.ids           # contracts.py — abstract delete(ids)

# --- FastAPI path parameters in stub endpoints (501 Not Implemented) ---
# The parameter name is dictated by the HTTP route pattern.
whitelist.response_id   # openai/responses.py — GET/DELETE /responses/{response_id}
