## MODIFIED Requirements

### Requirement: Publish the measurement contract atomically
Current measurement producers and consumers SHALL activate the updated registry/contract together without old-contract conversion executors or family aliases. Previous Registry Runs SHALL be terminal before activation. Durable prior measurement business payloads, original identities and source meanings SHALL remain readable without reinterpretation as a newer measurement schema.

The explicit backed-up maintenance migration for multimodal results SHALL be allowed to enrich only the outer result envelope with canonical media descriptions. It SHALL NOT change old measurement observations, normalize values, convert old families or rerun a measurement sensor. Any annotation newly materialized from old committed data during that migration SHALL be marked migration_reconstructed; unsupported or missing-source observations SHALL remain text-readable with no invented attachment. Normal online readers SHALL NOT infer or backfill images for those records. Tool descriptions SHALL retain correct normalized-scope examples and distinguish geometry from semantic values.

#### Scenario: Activate after prior Runs terminate
- **WHEN** the updated Registry is deployed
- **THEN** prior Registry Runs are terminal, new results use the updated contract, and old business payloads are neither rewritten nor converted; any outer attachment enrichment has already completed in the explicit migration

#### Scenario: Keep maintenance media enrichment separate from measurement conversion
- **WHEN** migration encounters a prior measurement result supported for text reads but not for current typed measurement resources
- **THEN** its business payload and call identity remain intact, no new-family conversion runs, and normal catalog construction does not expose it as a supported current resource
