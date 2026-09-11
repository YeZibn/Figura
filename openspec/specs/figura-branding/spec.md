# figura-branding Specification

## Purpose

Define Figura as the consistent user-facing identity across the desktop workspace and local service while preserving the existing internal runtime contracts.

## Requirements

### Requirement: Figura is the user-facing product identity

The desktop client, its window metadata, its local Gateway service presentation, and user-facing project documentation SHALL identify the product as `Figura`. The assistant-facing label SHALL use `Figura Agent`, and the local service display name SHALL use `Figura Gateway`. User-visible surfaces SHALL NOT present `ChartAgent` as the primary product brand.

#### Scenario: Desktop workspace presents Figura

- **WHEN** the desktop client opens in mock mode or Gateway mode
- **THEN** its brand mark, application title, assistant label, and primary workspace copy identify the product as Figura

#### Scenario: Gateway presentation uses Figura

- **WHEN** a client reads the Gateway health or service presentation intended for people
- **THEN** the displayed service name identifies the service as Figura Gateway while preserving the existing versioned response shape

#### Scenario: Documentation uses the product identity

- **WHEN** a user reads the project README or desktop startup guidance
- **THEN** the user-facing product and application names are presented as Figura, with technical commands shown only where needed to run the project

### Requirement: Existing chartagent runtime identifiers remain compatible

This branding change SHALL preserve the existing `chartagent` Python import and module paths, `CHARTAGENT_*` configuration variables, versioned protocol field names and headers, and existing local data location behavior. The branding change SHALL NOT require users to migrate existing configuration or session data.

#### Scenario: Existing Python startup remains valid

- **WHEN** a user runs the existing `python -m chartagent` or `python -m chartagent.gateway` command in the `agent` environment
- **THEN** the command remains usable without requiring a Figura-named replacement command

#### Scenario: Existing configuration remains valid

- **WHEN** the project is started with existing `CHARTAGENT_*` environment variables and an existing `.env` configuration
- **THEN** the Gateway and desktop runtime continue to resolve that configuration without a naming migration

#### Scenario: Existing session data remains available

- **WHEN** the project is upgraded with this change and an existing local session database is present
- **THEN** the existing sessions remain discoverable without being moved, renamed, or deleted because of the branding change
