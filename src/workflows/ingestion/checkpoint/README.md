## Checkpointing (SQLite)

This module provides a SQLite-backed `ScanCheckpointer` used by the discovery
scanners to resume long-running directory scans.

External cache-based ingestion queues and chunk registries have been removed. The SQLite
control plane now owns resumable checkpoints and context checkpoint compaction; it
replaces the external cache for metadata, so continue with the regular ingestion
pipeline or the RabbitMQ-based queue if needed.
