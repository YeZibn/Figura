# basic-tools Specification

## Purpose

Provides a first set of read-only, deterministic tools — file reading, directory
listing, and JSON parsing — built on the tool-system mechanism. They give the
future agent loop a safe, side-effect-free capability surface to act on the real
world, and lay groundwork for supplying data to the chart-reading side.

## ADDED Requirements

### Requirement: Batch-register built-in tools

The system SHALL expose a function that registers all built-in basic tools into
a given tool registry with one call, each tool carrying a proper name,
description and parameters schema.

#### Scenario: Register all built-ins at once

- **WHEN** `register_builtins(registry)` is called on an empty registry
- **THEN** all built-in basic tools become retrievable by name via the registry

### Requirement: Read a file's text content

The system SHALL provide a `read_file` tool that returns the text content of a
file at a given path, and SHALL report a structured error when the file cannot
be read.

#### Scenario: Read an existing file

- **WHEN** `read_file` is dispatched with a path to an existing file
- **THEN** the result is the file's text content as JSON-serializable output

#### Scenario: Missing or unreadable file yields an error

- **WHEN** `read_file` is dispatched with a path that does not exist or cannot
  be read
- **THEN** the result is a structured `{"error": ...}` rather than an unhandled
  exception

### Requirement: List directory entries

The system SHALL provide a `list_dir` tool that returns the entry names in a
directory at a given path, as a JSON-serializable list.

#### Scenario: List entries of an existing directory

- **WHEN** `list_dir` is dispatched with a path to an existing directory
- **THEN** the result is the list of entry names in that directory

#### Scenario: Missing or unreadable directory yields an error

- **WHEN** `list_dir` is dispatched with a path that does not exist or cannot be
  read
- **THEN** the result is a structured `{"error": ...}` rather than an unhandled
  exception

### Requirement: Parse JSON text

The system SHALL provide a `parse_json` tool that parses a JSON string into
JSON-serializable data, and SHALL report a structured error when the input is
invalid JSON.

#### Scenario: Parse valid JSON text

- **WHEN** `parse_json` is dispatched with a valid JSON string
- **THEN** the result is the parsed value as JSON-serializable output

#### Scenario: Invalid JSON yields an error

- **WHEN** `parse_json` is dispatched with invalid JSON text
- **THEN** the result is a structured `{"error": ...}`

### Requirement: Read and parse a JSON file

The system SHALL provide a `read_json_file` tool that combines reading and
parsing: read the file at a path, then parse its content as JSON, and SHALL
report a structured error if reading or parsing fails.

#### Scenario: Read and parse an existing JSON file

- **WHEN** `read_json_file` is dispatched with a path to an existing valid JSON
  file
- **THEN** the result is the parsed JSON data

#### Scenario: Read or parse failure yields an error

- **WHEN** `read_json_file` is dispatched with a missing file or a file whose
  content is invalid JSON
- **THEN** the result is a structured `{"error": ...}`