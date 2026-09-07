# tool-system Specification

## Purpose

Provides a declarative tool abstraction — tool definition, registration,
dispatch, and serialization — whose shape is designed to be exposed to external
agent hosts via MCP with minimal effort. It is the capability layer that future
agent loops call, without building the loop itself.

## Requirements

### Requirement: Declarative tool definition

The system SHALL let a tool be declared as metadata plus a callable: a stable
name, a human-readable description, a JSON-Schema description of accepted
parameters, and a Python callable that executes the tool. The metadata SHALL be
independent of the callable so the same tool can be described to an LLM or
mapped to an external protocol without touching the callable.

#### Scenario: Register a tool carrying name, description and schema

- **WHEN** a tool is created with a name, a description, a parameters schema and
  a callable
- **THEN** all four fields are retained and the callable is unchanged by the
  metadata

#### Scenario: Tool metadata stays decoupled from the callable

- **WHEN** a tool is read back for LLM tool-definition or external mapping
- **THEN** the name, description and parameters schema are available without
  executing or introspecting the callable

### Requirement: Tool registry

The system SHALL provide a registry to register, retrieve and list tools by
name, and to reject duplicate registrations of the same name.

#### Scenario: Register and list tools

- **WHEN** several tools are registered
- **THEN** each is retrievable by name and all are returned by the listing

#### Scenario: Duplicate registration is rejected

- **WHEN** a tool is registered under a name already in the registry
- **THEN** the registration is rejected or raises, and the originally registered
  tool stays intact

### Requirement: Dispatch a tool call to execution

The system SHALL dispatch a tool call — a name plus a JSON string of arguments —
to the matching callable, running it with the parsed arguments, and SHALL handle
the case of an unknown tool name.

#### Scenario: Unknown tool name yields a structured error

- **WHEN** a dispatch names a tool that is not registered
- **THEN** it returns a structured error produced by the registry, so the caller
  can feed it back to the model

### Requirement: Structured result and serialization

The system SHALL serialize a tool result as a JSON string fit to enter message
history, and SHALL represent a failed call as a structured error object, so the
LLM or an external host can read success and failure through the same shape.

#### Scenario: Successful result is JSON-serialized

- **WHEN** a tool call succeeds and the callable returns a value
- **THEN** the result returns as a JSON string and can enter history

#### Scenario: Failure becomes a structured error

- **WHEN** a tool call raises, or its result cannot be JSON-serialized
- **THEN** the result is a `{"error": ...}` structure rather than an unhandled
  exception or un-serializable object

### Requirement: Convertible to an MCP tool surface

The system SHALL provide a thin conversion that maps registered tools to the MCP
tool manifest shape (name, description, input schema) and their callables to an
MCP-compatible callable form, producing the exposed surface without running a
server.

#### Scenario: Registry maps to MCP tool manifests

- **WHEN** the registry is converted to an MCP tool surface
- **THEN** each registered tool yields its name, description and parameters
  schema in MCP form, and a callable wrapper that can be invoked for that tool