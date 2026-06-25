# TODO List


- [ ] Generate 5 possible names for this solution. Should be clever, catchy, and relevant to the functionality of the solution. After renaming, update all references in the codebase, documentation, and configuration files to reflect the new name.
- [ ] Fix naming inconsistencies in the codebase, ensuring that all variables, functions, and files follow a consistent naming convention that is clear and descriptive.
- [ ] Mesh rollout phase 1 (MVP replication on LAN/VM networks)
    - [ ] During installation, configure each instance as a mesh node (node ID, listen address, peer seed list, startup registration).
    - [ ] Generate and persist a mesh network identifier (user-specified mesh name plus auto-generated 8-character GUID suffix) during initial setup.
    - [ ] Require exact mesh network identifier match during peer handshake before any replication begins.
    - [ ] Allow the user to specify a custom replication port and advertise address.
    - [ ] Restrict supported deployment scope to LAN/VM networks only (explicitly out of scope: public internet/WAN).
    - [ ] Implement concurrent peer synchronization so each node can communicate with multiple peers and process updates safely without local DB conflicts.
    - [ ] Define replication identity and idempotency rules so every change has a globally unique event ID and can be safely applied multiple times.
    - [ ] Implement anti-entropy reconciliation so nodes periodically compare state summaries and request missing history until convergence.
    - [ ] Add bootstrap and recovery workflows so new or stale nodes can perform full snapshot sync followed by incremental catch-up.
- [ ] Mesh rollout phase 2 (safety, compatibility, and operations)
    - [ ] Implement a logging mechanism for mesh replication to log outgoing/incoming sync batches, conflicts, dedupe actions, retries, errors, and replication latency.
    - [ ] Implement a configuration file for mesh nodes, allowing users to customize settings such as node ID, listen address, peer list, replication interval, retry/backoff policy, and logging level.
    - [ ] Implement schema versioning and migration support for mesh replication. Nodes should reject incompatible replication payloads, advertise schema version during handshake, and provide a migration workflow to rejoin healthy sync state.
    - [ ] Define conflict resolution semantics (for example, per-table merge rules, deterministic tie-breakers, and tombstone handling) and document behavior.
    - [ ] Add retention and compaction policies for replicated history and tombstones, including safeguards that prevent premature deletion before cluster convergence.
    - [ ] Add mesh health metrics and alerts (peer reachability, replication lag, dedupe rate, conflict rate, and failed sync attempts) with operational runbooks.
- [ ] Mesh rollout phase 3 (performance tuning)
    - [ ] Implement replication performance optimization (batching, compression, checkpoints/high-water marks, and optional query/result caching where applicable).
- [ ] Update documentation for phased mesh installation and usage, including LAN/VM networking requirements, firewall setup, recovery procedures, and troubleshooting.
    - [ ] Document mesh network identifier behavior as accidental-cross-merge prevention for shared LANs (coworkers/roommates), not as cryptographic security.