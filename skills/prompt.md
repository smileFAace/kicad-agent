# KiCad Agent -- Operation Reference

This reference documents all operations supported by kicad-agent. Claude uses these schemas to construct valid JSON operations that the Python backend validates and executes against KiCad files.

**Key principle:** The LLM never touches raw S-expressions. It emits structured JSON intents, and the Python tool layer mutates the AST, serializes valid KiCad files, and validates via ERC/DRC gates.

**Supported targets:** `.kicad_sch` (schematic), `.kicad_pcb` (PCB), `.kicad_sym` (symbol library), `.kicad_mod` (footprint library), `.kicad_dru` (design rules), `.kicad_pro` (project settings), `sym-lib-table`, `fp-lib-table`

**KiCad version:** 10+ only

---

## Available Operations

### Component Operations

#### add_component

Add a component to a schematic or PCB.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"add_component"` |
| `target_file` | string | Relative path to KiCad file (`.kicad_sch` or `.kicad_pcb`) |
| `library_id` | string | Library reference, e.g. `"Device:R_Small_US"` (1-256 chars) |
| `position` | object | Placement coordinates `{x, y}` with optional `angle` (degrees, default 0) |

**Optional fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `reference` | string | `"R?"` | Reference designator (1-64 chars) |
| `value` | string | `""` | Component value (max 256 chars) |

**Example:**

```json
{
  "root": {
    "op_type": "add_component",
    "target_file": "motor-driver.kicad_sch",
    "library_id": "Device:R_Small_US",
    "reference": "R1",
    "value": "10k",
    "position": {"x": 50.0, "y": 30.0, "angle": 90.0}
  }
}
```

---

#### remove_component

Remove a component by reference designator.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"remove_component"` |
| `target_file` | string | Relative path to KiCad file |
| `reference` | string | Reference designator to remove (1-64 chars) |

**Example:**

```json
{
  "root": {
    "op_type": "remove_component",
    "target_file": "motor-driver.kicad_sch",
    "reference": "R1"
  }
}
```

---

#### move_component

Move a component to a new position.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"move_component"` |
| `target_file` | string | Relative path to KiCad file |
| `reference` | string | Reference designator of the component to move (1-64 chars) |
| `position` | object | Target coordinates `{x, y}` with optional `angle` |

**Example:**

```json
{
  "root": {
    "op_type": "move_component",
    "target_file": "motor-driver.kicad_pcb",
    "reference": "U3",
    "position": {"x": 100.0, "y": 50.0, "angle": 180.0}
  }
}
```

---

#### modify_property

Modify a component property (value, footprint, reference, custom field).

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"modify_property"` |
| `target_file` | string | Relative path to KiCad file |
| `reference` | string | Reference designator (1-64 chars) |
| `property_name` | string | Property to modify, e.g. `"Value"`, `"Footprint"` (1-128 chars) |
| `new_value` | string | New property value (max 1024 chars) |

**Example:**

```json
{
  "root": {
    "op_type": "modify_property",
    "target_file": "motor-driver.kicad_sch",
    "reference": "R1",
    "property_name": "Value",
    "new_value": "4.7k"
  }
}
```

---

#### duplicate_component

Duplicate a component with fresh UUID and incremented reference.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"duplicate_component"` |
| `target_file` | string | Relative path to KiCad file |
| `source_reference` | string | Reference designator of the component to duplicate (1-64 chars) |

**Optional fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `offset` | object | `null` | Position offset from source `{x, y}` (angle ignored) |
| `count` | integer | `1` | Number of copies (1-100) |

**Example:**

```json
{
  "root": {
    "op_type": "duplicate_component",
    "target_file": "motor-driver.kicad_sch",
    "source_reference": "R1",
    "offset": {"x": 5.0, "y": 0.0},
    "count": 3
  }
}
```

---

#### array_replicate

Replicate a component in a linear, circular, or matrix array pattern.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"array_replicate"` |
| `target_file` | string | Relative path to KiCad file |
| `source_reference` | string | Reference designator of the component to replicate (1-64 chars) |
| `pattern` | string | Array pattern: `"linear"`, `"circular"`, or `"matrix"` |
| `spacing` | object | Position spacing `{x, y}` with optional `angle` |

**Optional fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `count` | integer | `1` | Number of replications (1-100) |
| `angle_step` | number | `null` | Degrees per step (circular pattern only) |
| `center` | object | `null` | Center point `{x, y}` (circular pattern only) |
| `rows` | integer | `null` | Number of rows (matrix pattern only) |
| `cols` | integer | `null` | Number of columns (matrix pattern only) |

**Example (linear):**

```json
{
  "root": {
    "op_type": "array_replicate",
    "target_file": "motor-driver.kicad_sch",
    "source_reference": "R1",
    "pattern": "linear",
    "count": 4,
    "spacing": {"x": 5.0, "y": 0.0}
  }
}
```

**Example (matrix):**

```json
{
  "root": {
    "op_type": "array_replicate",
    "target_file": "motor-driver.kicad_pcb",
    "source_reference": "LED1",
    "pattern": "matrix",
    "spacing": {"x": 3.0, "y": 3.0},
    "rows": 3,
    "cols": 4
  }
}
```

---

#### embed_symbol

Embed a symbol definition from a .kicad_sym library file into a schematic's lib_symbols section. Required before a symbol can be referenced by components in the schematic. If the symbol already exists (matching libId), the operation is a no-op.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"embed_symbol"` |
| `target_file` | string | Relative path to .kicad_sch file |
| `lib_id` | string | Library:symbol ID to embed, e.g. `"Analog-Ecosystem-SMD:RP2350B"` (1-256 chars) |
| `library_path` | string | Relative path to .kicad_sym library file (from schematic's directory) |

**Example:**

```json
{
  "root": {
    "op_type": "embed_symbol",
    "target_file": "mcu-core.kicad_sch",
    "lib_id": "Analog-Ecosystem-SMD:RP2350B",
    "library_path": "../../shared/symbols/Analog-Ecosystem-SMD.kicad_sym"
  }
}
```

---

#### swap_symbol

Swap a component's symbol (lib_id) in-place, preserving position and properties. Optionally auto-embeds the new symbol definition from a library file. Wire connections are not affected (they reference UUIDs, not symbol types).

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"swap_symbol"` |
| `target_file` | string | Relative path to .kicad_sch file |
| `reference` | string | Component reference designator, e.g. `"U1"` (1-64 chars) |
| `new_lib_id` | string | New library:symbol ID, e.g. `"Analog-Ecosystem-SMD:RP2350B"` (1-256 chars) |

**Optional fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `library_path` | string | `null` | Path to .kicad_sym for auto-embedding (from schematic's directory) |
| `preserve_position` | boolean | `true` | Keep component's current (at X Y) coordinates |
| `preserve_properties` | boolean | `true` | Keep component's current properties (Value, Footprint, etc.) |

**Example:**

```json
{
  "root": {
    "op_type": "swap_symbol",
    "target_file": "mcu-core.kicad_sch",
    "reference": "U1",
    "new_lib_id": "Analog-Ecosystem-SMD:RP2350B",
    "library_path": "../../shared/symbols/Analog-Ecosystem-SMD.kicad_sym"
  }
}
```

---

### Net Operations

#### add_net

Add a net to a PCB.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"add_net"` |
| `target_file` | string | Relative path to KiCad PCB file (`.kicad_pcb`) |

**Optional fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `net_name` | string | `""` | Net name. Empty triggers auto-generation as `N_<number>` (max 64 chars) |
| `net_number` | integer | `null` | Explicit net number. `null` = auto-assign |

**Example:**

```json
{
  "root": {
    "op_type": "add_net",
    "target_file": "motor-driver.kicad_pcb",
    "net_name": "VCC_3V3"
  }
}
```

---

#### remove_net

Remove a net from a PCB, disconnecting all pads.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"remove_net"` |
| `target_file` | string | Relative path to KiCad PCB file |
| `net_name` | string | Name of the net to remove (1-64 chars) |

**Example:**

```json
{
  "root": {
    "op_type": "remove_net",
    "target_file": "motor-driver.kicad_pcb",
    "net_name": "VCC_3V3"
  }
}
```

---

#### rename_net

Rename a net, propagating to all connected pads.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"rename_net"` |
| `target_file` | string | Relative path to KiCad PCB file |
| `old_name` | string | Current net name (1-64 chars) |
| `new_name` | string | Desired new net name (1-64 chars) |

**Example:**

```json
{
  "root": {
    "op_type": "rename_net",
    "target_file": "motor-driver.kicad_pcb",
    "old_name": "VCC_3V3",
    "new_name": "VCC_3V3_DIGITAL"
  }
}
```

---

### Reference Operations

#### renumber_refs

Renumber component references with configurable prefix and sequencing.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"renumber_refs"` |
| `target_file` | string | Relative path to KiCad schematic file |

**Optional fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `prefix` | string | `""` | Only renumber components with this prefix. Empty = all (max 16 chars) |
| `start_index` | integer | `1` | Starting index for numbering (min 1) |
| `step` | integer | `1` | Step between sequential indices (min 1) |

**Example:**

```json
{
  "root": {
    "op_type": "renumber_refs",
    "target_file": "motor-driver.kicad_sch",
    "prefix": "R",
    "start_index": 1,
    "step": 1
  }
}
```

---

#### validate_refs

Validate that all component references are unique.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"validate_refs"` |
| `target_file` | string | Relative path to KiCad schematic file |

**Example:**

```json
{
  "root": {
    "op_type": "validate_refs",
    "target_file": "motor-driver.kicad_sch"
  }
}
```

---

#### annotate

Auto-assign references to unannotated components (refs ending in `?`).

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"annotate"` |
| `target_file` | string | Relative path to KiCad schematic file |

**Optional fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `prefix_filter` | string | `""` | Only annotate components matching this prefix. Empty = all (max 16 chars) |

**Example:**

```json
{
  "root": {
    "op_type": "annotate",
    "target_file": "motor-driver.kicad_sch",
    "prefix_filter": "R"
  }
}
```

---

#### cross_ref_check

Verify all symbol libIds resolve to entries in the embedded libSymbols.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"cross_ref_check"` |
| `target_file` | string | Relative path to KiCad schematic file |

**Example:**

```json
{
  "root": {
    "op_type": "cross_ref_check",
    "target_file": "motor-driver.kicad_sch"
  }
}
```

---

### Footprint Operations

#### assign_footprint

Assign a footprint to a schematic component.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"assign_footprint"` |
| `target_file` | string | Relative path to KiCad schematic file |
| `reference` | string | Component reference designator, e.g. `"U1"` (1-64 chars) |
| `footprint_lib_id` | string | Footprint library reference, e.g. `"Package_DIP:DIP-8_W7.62mm"` (1-256 chars) |

**Example:**

```json
{
  "root": {
    "op_type": "assign_footprint",
    "target_file": "motor-driver.kicad_sch",
    "reference": "U1",
    "footprint_lib_id": "Package_DIP:DIP-8_W7.62mm"
  }
}
```

---

#### swap_footprint

Swap a PCB footprint while preserving pad-to-net connections.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"swap_footprint"` |
| `target_file` | string | Relative path to KiCad PCB file |
| `reference` | string | Reference designator of the footprint to swap (1-64 chars) |
| `new_footprint_lib_id` | string | New footprint library reference (1-256 chars) |

**Example:**

```json
{
  "root": {
    "op_type": "swap_footprint",
    "target_file": "motor-driver.kicad_pcb",
    "reference": "U3",
    "new_footprint_lib_id": "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm"
  }
}
```

---

#### validate_footprint

Validate that a footprint exists in the available libraries.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"validate_footprint"` |
| `target_file` | string | Relative path to KiCad file |
| `footprint_lib_id` | string | Footprint library reference to validate (1-256 chars) |

**Example:**

```json
{
  "root": {
    "op_type": "validate_footprint",
    "target_file": "motor-driver.kicad_pcb",
    "footprint_lib_id": "Package_DIP:DIP-8_W7.62mm"
  }
}
```

---

#### verify_pin_map

Verify that symbol pin numbers match footprint pad numbers.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"verify_pin_map"` |
| `target_file` | string | Relative path to KiCad file |
| `reference` | string | Component reference designator (1-64 chars) |
| `footprint_lib_id` | string | Footprint library reference to verify against (1-256 chars) |

**Example:**

```json
{
  "root": {
    "op_type": "verify_pin_map",
    "target_file": "motor-driver.kicad_sch",
    "reference": "U1",
    "footprint_lib_id": "Package_DIP:DIP-8_W7.62mm"
  }
}
```

---

#### update_footprint_from_library

Reload a PCB footprint's geometry from the library, preserving placement, reference, value, and pad-to-net connections. Equivalent to KiCad's GUI "Tools > Update Footprints from Library".

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"update_footprint_from_library"` |
| `target_file` | string | Relative path to `.kicad_pcb` file |
| `reference` | string | Reference designator of the footprint to update |

**Optional fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `footprint_lib_id` | string | `null` | Override lib_id to swap + update. Omit to refresh from same library. |

---

#### add_wire

Add a wire segment between two points in a schematic.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"add_wire"` |
| `target_file` | string | Relative path to `.kicad_sch` file |
| `start_x` | float | Start X coordinate in mm |
| `start_y` | float | Start Y coordinate in mm |
| `end_x` | float | End X coordinate in mm |
| `end_y` | float | End Y coordinate in mm |

**Example:**

```json
{
  "root": {
    "op_type": "add_wire",
    "target_file": "motor-driver.kicad_sch",
    "start_x": 50.0,
    "start_y": 30.0,
    "end_x": 80.0,
    "end_y": 30.0
  }
}
```

---

#### connect_pins

Connect two schematic pins by reference and pin number/name. This resolves real pin endpoints from the embedded/library symbol data, then adds a wire between those endpoints. Prefer this over manual `add_wire` coordinates when connecting component pins.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"connect_pins"` |
| `target_file` | string | Relative path to `.kicad_sch` file |
| `source` | string | Source pin in `REF.PIN` format, e.g. `"U1.34"` or `"J3.Pin_2"` |
| `target` | string | Target pin in `REF.PIN` format, e.g. `"J3.2"` |

**Optional fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `route` | string | `"orthogonal"` | Routing style: `"orthogonal"` for horizontal/vertical segments or `"direct"` for one segment |

**Example:**

```json
{
  "root": {
    "op_type": "connect_pins",
    "target_file": "stm32-minimal.kicad_sch",
    "source": "U1.34",
    "target": "J3.2"
  }
}
```

---

#### add_label

Add a net label to a schematic (local, global, or hierarchical).

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"add_label"` |
| `target_file` | string | Relative path to `.kicad_sch` file |
| `name` | string | Label text (e.g. `"SDA"`, `"+5V"`) |
| `position` | object | Placement coordinates `{x, y}` with optional `angle` |

**Optional fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `label_type` | string | `"local"` | Scope: `local`, `global`, or `hierarchical` |
| `shape` | string | `"input"` | Shape for global/hierarchical: input, output, bidirectional, tri_state, passive |

**Example:**

```json
{
  "root": {
    "op_type": "add_label",
    "target_file": "motor-driver.kicad_sch",
    "name": "SDA",
    "label_type": "global",
    "position": {"x": 50.0, "y": 30.0}
  }
}
```

---

#### add_power

Add a power symbol to a schematic (e.g. +5V, GND, +3V3). Places a `power:<name>` library symbol at the specified position.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"add_power"` |
| `target_file` | string | Relative path to `.kicad_sch` file |
| `name` | string | Power net name (e.g. `"+5V"`, `"GND"`, `"+3V3"`) |
| `position` | object | Placement coordinates `{x, y}` |

**Example:**

```json
{
  "root": {
    "op_type": "add_power",
    "target_file": "motor-driver.kicad_sch",
    "name": "+3V3",
    "position": {"x": 25.0, "y": 50.0}
  }
}
```

---

#### add_no_connect

Add a no-connect flag to an unconnected schematic pin.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"add_no_connect"` |
| `target_file` | string | Relative path to `.kicad_sch` file |
| `position` | object | Placement coordinates `{x, y}` |

---

#### add_junction

Add a junction dot at a wire intersection in a schematic.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"add_junction"` |
| `target_file` | string | Relative path to `.kicad_sch` file |
| `position` | object | Placement coordinates `{x, y}` |

---

#### remove_wire

Remove a wire segment by UUID.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"remove_wire"` |
| `target_file` | string | Relative path to `.kicad_sch` file |
| `uuid` | string | UUID of the wire to remove |

---

#### remove_label

Remove a net label by UUID.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"remove_label"` |
| `target_file` | string | Relative path to `.kicad_sch` file |
| `uuid` | string | UUID of the label to remove |
| `label_type` | string | Scope: `local`, `global`, or `hierarchical` |

---

#### remove_junction

Remove a junction dot by UUID.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"remove_junction"` |
| `target_file` | string | Relative path to `.kicad_sch` file |
| `uuid` | string | UUID of the junction to remove |

---

#### remove_no_connect

Remove a no-connect flag by UUID.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"remove_no_connect"` |
| `target_file` | string | Relative path to `.kicad_sch` file |
| `uuid` | string | UUID of the no-connect flag to remove |

---

#### add_lib_entry

Add a library entry to `sym-lib-table` or `fp-lib-table`.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"add_lib_entry"` |
| `target_file` | string | Relative path to `sym-lib-table` or `fp-lib-table` |
| `lib_name` | string | Library name (e.g. `"Device"`, `"MyLib"`) |
| `uri` | string | Library URI path (may use `${KIPRJMOD}`) |

**Optional fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `lib_type` | string | `"KiCad"` | Library type: `"KiCad"` or `"Legacy"` |
| `options` | string | `""` | Library options |
| `description` | string | `""` | Library description |

---

#### remove_lib_entry

Remove a library entry from `sym-lib-table` or `fp-lib-table`.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"remove_lib_entry"` |
| `target_file` | string | Relative path to `sym-lib-table` or `fp-lib-table` |
| `lib_name` | string | Library name to remove |

---

#### list_lib_entries

List all library entries in `sym-lib-table` or `fp-lib-table`. This is read-only.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"list_lib_entries"` |
| `target_file` | string | Relative path to `sym-lib-table` or `fp-lib-table` |

---

#### add_net_class

Add a net class with track/via/clearance dimensions to a `.kicad_dru` file.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"add_net_class"` |
| `target_file` | string | Relative path to `.kicad_dru` file |
| `name` | string | Net class name |
| `clearance` | float | Clearance in mm (must be > 0) |
| `track_width` | float | Track width in mm (must be > 0) |
| `via_diameter` | float | Via diameter in mm (must be > 0) |
| `via_drill` | float | Via drill in mm (must be > 0) |

**Example:**

```json
{
  "root": {
    "op_type": "add_net_class",
    "target_file": "motor-driver.kicad_dru",
    "name": "Power",
    "clearance": 0.3,
    "track_width": 0.5,
    "via_diameter": 0.8,
    "via_drill": 0.4
  }
}
```

---

#### assign_net_class

Assign a net class to a specific net in the PCB.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"assign_net_class"` |
| `target_file` | string | Relative path to `.kicad_pcb` file |
| `net_name` | string | Net name to assign |
| `net_class_name` | string | Net class name to assign |

---

#### modify_net_class

Modify an existing net class in a `.kicad_dru` file. Only specified fields are changed.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"modify_net_class"` |
| `target_file` | string | Relative path to `.kicad_dru` file |
| `name` | string | Net class name to modify |

**Optional fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `clearance` | float | `null` | New clearance in mm |
| `track_width` | float | `null` | New track width in mm |
| `via_diameter` | float | `null` | New via diameter in mm |
| `via_drill` | float | `null` | New via drill in mm |
| `uvia_diameter` | float | `null` | New micro-via diameter in mm |
| `uvia_drill` | float | `null` | New micro-via drill in mm |
| `diff_pair_width` | float | `null` | New diff-pair width in mm |
| `diff_pair_gap` | float | `null` | New diff-pair gap in mm |

---

#### remove_net_class

Remove a net class from a `.kicad_dru` file.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"remove_net_class"` |
| `target_file` | string | Relative path to `.kicad_dru` file |
| `name` | string | Net class name to remove |

---

#### list_net_classes

List all net classes in a `.kicad_dru` file. This is read-only.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"list_net_classes"` |
| `target_file` | string | Relative path to `.kicad_dru` file |

---

#### add_design_rule

Add a custom DRC rule to `.kicad_dru`.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"add_design_rule"` |
| `target_file` | string | Relative path to `.kicad_dru` file |
| `name` | string | Rule name |
| `constraint_type` | string | Constraint type (e.g. `"clearance"`, `"width"`) |

**Optional fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `constraint_values` | object | `{}` | Key-value constraint parameters |
| `condition` | string | `""` | KiCad condition expression |

---

#### modify_design_rule

Modify an existing custom DRC rule in a `.kicad_dru` file. Only specified fields are changed.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"modify_design_rule"` |
| `target_file` | string | Relative path to `.kicad_dru` file |
| `name` | string | Rule name to modify |

**Optional fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `constraint_type` | string | `null` | New constraint type |
| `constraint_values` | object | `null` | New constraint parameters |
| `condition` | string | `null` | New KiCad condition expression |
| `layer` | string | `null` | New layer restriction |

---

#### remove_design_rule

Remove a custom DRC rule from a `.kicad_dru` file.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"remove_design_rule"` |
| `target_file` | string | Relative path to `.kicad_dru` file |
| `name` | string | Rule name to remove |

---

#### list_design_rules

List all custom DRC rules in a `.kicad_dru` file. This is read-only.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"list_design_rules"` |
| `target_file` | string | Relative path to `.kicad_dru` file |

---

#### modify_project_settings

Deep-merge JSON settings into a `.kicad_pro` project file while preserving unknown keys.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"modify_project_settings"` |
| `target_file` | string | Relative path to `.kicad_pro` file |
| `updates` | object | JSON sections to merge into the project file |

---

#### add_copper_zone

Add a copper zone/ground pour to a PCB.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"add_copper_zone"` |
| `target_file` | string | Relative path to `.kicad_pcb` file |
| `net_name` | string | Net name for the zone (e.g. `"GND"`) |

**Optional fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `layer` | string | `"F.Cu"` | Copper layer |
| `clearance` | float | `0.5` | Zone clearance in mm |
| `min_width` | float | `0.25` | Minimum fill width in mm |
| `priority` | int | `0` | Zone priority (higher = filled first) |

**Example:**

```json
{
  "root": {
    "op_type": "add_copper_zone",
    "target_file": "motor-driver.kicad_pcb",
    "net_name": "GND",
    "layer": "B.Cu",
    "clearance": 0.3
  }
}
```

---

#### modify_copper_zone

Modify an existing copper zone on a PCB. The zone is identified by UUID.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"modify_copper_zone"` |
| `target_file` | string | Relative path to `.kicad_pcb` file |
| `zone_uuid` | string | Zone UUID (`tstamp`) to modify |

**Optional fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `net_name` | string | `null` | New net name |
| `layer` | string | `null` | New copper layer |
| `clearance` | float | `null` | New clearance in mm |
| `min_width` | float | `null` | New minimum fill width in mm |
| `priority` | int | `null` | New zone priority |

---

#### remove_copper_zone

Remove a copper zone from a PCB. Identify it by `zone_uuid` when possible, or by `zone_index` as a fallback.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"remove_copper_zone"` |
| `target_file` | string | Relative path to `.kicad_pcb` file |

**Optional fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `zone_uuid` | string | `null` | Zone UUID (`tstamp`) |
| `zone_index` | int | `null` | Zone index fallback |

At least one of `zone_uuid` or `zone_index` is required.

---

#### set_board_outline

Define PCB board shape as a rectangle on Edge.Cuts.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"set_board_outline"` |
| `target_file` | string | Relative path to `.kicad_pcb` file |
| `width` | float | Board width in mm |
| `height` | float | Board height in mm |

**Example:**

```json
{
  "root": {
    "op_type": "set_board_outline",
    "target_file": "motor-driver.kicad_pcb",
    "width": 50.0,
    "height": 30.0
  }
}
```

---

#### repair_schematic

Auto-repair common ERC errors in a schematic.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"repair_schematic"` |
| `target_file` | string | Relative path to `.kicad_sch` file |

**Optional fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `snap_wires` | bool | `true` | Snap wire endpoints to nearest pin positions |
| `remove_orphans` | bool | `true` | Remove labels not connected to any wire or pin |
| `place_no_connects` | bool | `true` | Place no-connect markers on unconnected pins |

---

#### validate_power_nets

Check that all power pins have connected power symbols.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"validate_power_nets"` |
| `target_file` | string | Relative path to `.kicad_sch` file |

---

#### validate_schematic

Comprehensive schematic validation combining format, symbol resolution, power nets, and annotation checks.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"validate_schematic"` |
| `target_file` | string | Relative path to `.kicad_sch` file |

**Optional fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `check_symbol_resolution` | bool | `true` | Verify all lib_ids resolve to symbol definitions (catches question-mark boxes) |
| `check_format` | bool | `true` | Validate KiCad 10 S-expression format rules (tabs, comments, pin format, etc.) |
| `check_power_nets` | bool | `true` | Check power pin connectivity |
| `check_annotation` | bool | `true` | Check for unannotated components (R?, C?) |

**Example:**

```json
{
  "root": {
    "op_type": "validate_schematic",
    "target_file": "backplane.kicad_sch",
    "check_symbol_resolution": true,
    "check_format": true
  }
}
```

---

#### auto_route

Auto-route nets on a PCB using A* pathfinding.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"auto_route"` |
| `target_file` | string | Relative path to `.kicad_pcb` file |

**Optional fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `nets` | array | `[]` | Specific net names to route. Empty = route all. |
| `layer` | string | `"F.Cu"` | Target copper layer (e.g. `"F.Cu"`, `"B.Cu"`, `"In1.Cu"`) |

**Example:**

```json
{
  "root": {
    "op_type": "auto_route",
    "target_file": "motor-driver.kicad_pcb",
    "nets": ["SDA", "SCL"],
    "layer": "F.Cu"
  }
}
```

---

### File Creation Operations

#### create_schematic

Create a new empty `.kicad_sch` file. The file must not already exist. Generates a valid KiCad schematic with proper header, UUID, paper size, and optional title block.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"create_schematic"` |
| `target_file` | string | Relative path for the new `.kicad_sch` file |

**Optional fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `paper` | string | `"A4"` | Paper size (A4, A3, A2, A1, A0, or custom) |
| `title` | string | `""` | Title block title (max 256 chars) |

**Example:**

```json
{
  "root": {
    "op_type": "create_schematic",
    "target_file": "motor-driver.kicad_sch",
    "paper": "A3",
    "title": "Motor Driver Schematic"
  }
}
```

---

#### create_pcb

Create a new empty `.kicad_pcb` file. The file must not already exist. Generates a valid KiCad PCB with standard layer stack.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"create_pcb"` |
| `target_file` | string | Relative path for the new `.kicad_pcb` file |

**Optional fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `title` | string | `""` | Board title (max 256 chars) |

**Example:**

```json
{
  "root": {
    "op_type": "create_pcb",
    "target_file": "motor-driver.kicad_pcb"
  }
}
```

---

#### create_project

Create a new empty `.kicad_pro` project file. The file must not already exist.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"create_project"` |
| `target_file` | string | Relative path for the new `.kicad_pro` file |

**Example:**

```json
{
  "root": {
    "op_type": "create_project",
    "target_file": "motor-driver.kicad_pro"
  }
}
```

---

#### create_symbol

Create a new symbol definition in a `.kicad_sym` library file. If the library does not exist, it is created. If it exists, the symbol is appended. Duplicate symbol names are rejected.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"create_symbol"` |
| `target_file` | string | Relative path to the `.kicad_sym` library file |
| `symbol_name` | string | Symbol name (1-128 chars, alphanumeric/dash/underscore only) |

**Optional fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `reference_prefix` | string | `"U"` | Reference prefix (e.g. R, U, C, D, J) |
| `value` | string | `""` | Default value (max 256 chars) |
| `pins` | array | `[]` | Pin definitions (max 200) |
| `properties` | array | `[]` | Custom properties (max 50) |
| `body_width` | float | `10.16` | Body rectangle width in mm |
| `body_height` | float | `10.16` | Body rectangle height in mm |

**Pin definition (`pins` array items):**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `number` | string | (required) | Pin number (1-32 chars) |
| `name` | string | (required) | Pin name (1-128 chars) |
| `electrical_type` | string | `"passive"` | One of: input, output, bidirectional, tri_state, passive, free, unspecified, power_in, power_out, open_collector, open_emitter, no_connect |
| `position` | object | (required) | `{x, y}` coordinates in mm, optional `angle` |
| `length` | float | `2.54` | Pin length in mm |
| `graphical_style` | string | `"line"` | One of: line, inverted, clock, inverted_clock, input_low, clock_low, output_low, edge_clock_high, non_logic |
| `hide` | bool | `false` | Whether pin is hidden |

**Example -- IC with power and I/O pins:**

```json
{
  "root": {
    "op_type": "create_symbol",
    "target_file": "my-lib.kicad_sym",
    "symbol_name": "AK4619VN",
    "reference_prefix": "U",
    "value": "AK4619VN",
    "pins": [
      {"number": "1", "name": "VCC", "electrical_type": "power_in", "position": {"x": 0, "y": 5.08}},
      {"number": "2", "name": "GND", "electrical_type": "power_in", "position": {"x": 0, "y": -5.08}},
      {"number": "3", "name": "SDIN", "electrical_type": "input", "position": {"x": -5.08, "y": 2.54}},
      {"number": "4", "name": "SDOUT", "electrical_type": "output", "position": {"x": 5.08, "y": 2.54}},
      {"number": "5", "name": "BCLK", "electrical_type": "input", "graphical_style": "clock", "position": {"x": -5.08, "y": 0}},
      {"number": "6", "name": "LRCK", "electrical_type": "input", "position": {"x": -5.08, "y": -2.54}}
    ],
    "properties": [
      {"name": "Manufacturer", "value": "AKM"},
      {"name": "MPN", "value": "AK4619VN"}
    ],
    "body_width": 10.16,
    "body_height": 10.16
  }
}
```

---

#### create_footprint

Create a new standalone `.kicad_mod` footprint file with pads, reference/value text, optional courtyard, and attributes. The file must not already exist.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"create_footprint"` |
| `target_file` | string | Relative path for the new `.kicad_mod` file |
| `footprint_name` | string | Footprint name (1-128 chars, safe identifier) |

**Optional fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `reference_prefix` | string | `"U"` | Reference prefix (e.g. U, R, C) |
| `value` | string | `""` | Default footprint value |
| `pads` | array | `[]` | Pad definitions (max 500) |
| `courtyard_margin` | float | `0.25` | Courtyard margin in mm; 0 disables courtyard |
| `attributes` | string | `"through_hole"` | One of: through_hole, smd, board_only |

**Pad definition (`pads` array items):**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `number` | string | (required) | Pad number or designator |
| `pad_type` | string | (required) | One of: smd, thru_hole, connect |
| `shape` | string | (required) | One of: rect, roundrect, oval, circle, custom |
| `position` | object | (required) | Pad center `{x, y}` in mm, optional `angle` |
| `size_x` | float | (required) | Pad width in mm |
| `size_y` | float | (required) | Pad height in mm |
| `layers` | array | (required) | KiCad layer names |
| `drill_diameter` | float | `null` | Required for thru_hole pads; forbidden for smd/connect |
| `drill_offset_x` | float | `null` | Drill offset X in mm |
| `drill_offset_y` | float | `null` | Drill offset Y in mm |

---

### Hierarchical Sheet Operations

#### add_sheet

Add a hierarchical sheet symbol to a schematic, optionally creating the child schematic file.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"add_sheet"` |
| `target_file` | string | Relative path to parent `.kicad_sch` file |
| `sheet_name` | string | Display name for the sheet symbol |
| `file_name` | string | Relative path to child `.kicad_sch` |
| `position` | object | Sheet symbol position `{x, y}` in mm |

**Optional fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `width` | float | `30.0` | Sheet symbol width in mm |
| `height` | float | `20.0` | Sheet symbol height in mm |
| `create_sub_sheet` | bool | `true` | Auto-create child schematic if missing |

---

#### add_sheet_pin

Add a pin to an existing hierarchical sheet symbol.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"add_sheet_pin"` |
| `target_file` | string | Relative path to parent `.kicad_sch` file |
| `sheet_uuid` | string | UUID of the target hierarchical sheet |
| `pin_name` | string | Pin name matching a hierarchical label in the child sheet |
| `position` | object | Pin position on the sheet boundary |

**Optional fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `connection_type` | string | `"bidirectional"` | One of: input, output, bidirectional, tri_state, passive |

---

#### navigate_hierarchy

Traverse hierarchical sheets from a root schematic. This is read-only.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"navigate_hierarchy"` |
| `target_file` | string | Relative path to root `.kicad_sch` file |

**Optional fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `max_depth` | int | `-1` | Max traversal depth; -1 means unlimited |

---

### Query Operations

#### query_connectivity

Query PCB connectivity using the net graph without modifying the file.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"query_connectivity"` |
| `target_file` | string | Relative path to `.kicad_pcb` file |
| `query_type` | string | One of: connected_pads, net_stats, are_connected, shortest_path, connected_components |

**Optional fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `net_name` | string | `null` | Required when `query_type` is `connected_pads` |
| `source` | array | `null` | Source pad `[footprint_ref, pad_number]`; required for path queries |
| `target` | array | `null` | Target pad `[footprint_ref, pad_number]`; required for path queries |

---

### Cross-File Operations

#### propagate_symbol_change

Propagate a symbol or footprint library reference change across multiple files atomically.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"propagate_symbol_change"` |
| `target_file` | string | Primary file path for execution routing; should be first in `target_files` |
| `target_files` | array | Relative paths to mutate atomically |
| `old_lib_id` | string | Current library ID to match |
| `new_lib_id` | string | Replacement library ID |

---

### Schematic Repair Operations

#### parse_erc

Parse an ERC (Electrical Rules Check) JSON report and return structured violations.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"parse_erc"` |
| `target_file` | string | Relative path to `.kicad_sch` file |

**Example:**

```json
{
  "root": {
    "op_type": "parse_erc",
    "target_file": "motor-driver.kicad_sch"
  }
}
```

---

#### extract_violation_positions

Extract violation positions from an ERC report, filtered by violation type.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"extract_violation_positions"` |
| `target_file` | string | Relative path to `.kicad_sch` file |
| `violation_type` | string | Type of violation to filter (e.g. `"ERC_ERROR"`, `"ERC_WARNING"`) |

**Example:**

```json
{
  "root": {
    "op_type": "extract_violation_positions",
    "target_file": "motor-driver.kicad_sch",
    "violation_type": "ERC_ERROR"
  }
}
```

---

#### validate_hlabels

Validate that hierarchical labels in sub-sheets match expected labels.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"validate_hlabels"` |
| `target_file` | string | Relative path to `.kicad_sch` file |
| `expected_labels` | array | List of expected label names to verify |

**Example:**

```json
{
  "root": {
    "op_type": "validate_hlabels",
    "target_file": "motor-driver.kicad_sch",
    "expected_labels": ["VCC", "GND", "SDIN", "SDOUT"]
  }
}
```

---

#### convert_kicad6_to_10

Convert a KiCad 5/6 format schematic to KiCad 10 format. Handles header conversion, UUID quoting, legacy element removal, and format fixes.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"convert_kicad6_to_10"` |
| `target_file` | string | Relative path to `.kicad_sch` file |

**Example:**

```json
{
  "root": {
    "op_type": "convert_kicad6_to_10",
    "target_file": "legacy-schematic.kicad_sch"
  }
}
```

---

#### snap_to_grid

Snap all coordinates in a schematic to the specified grid.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"snap_to_grid"` |
| `target_file` | string | Relative path to `.kicad_sch` file |

**Optional fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `grid_mm` | float | `0.01` | Grid spacing in mm (min > 0, max 100) |

**Example:**

```json
{
  "root": {
    "op_type": "snap_to_grid",
    "target_file": "motor-driver.kicad_sch",
    "grid_mm": 0.254
  }
}
```

---

#### add_power_flag

Add power flags (PWR_FLAG) to undriven power pins.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"add_power_flag"` |
| `target_file` | string | Relative path to `.kicad_sch` file |

**Example:**

```json
{
  "root": {
    "op_type": "add_power_flag",
    "target_file": "motor-driver.kicad_sch"
  }
}
```

---

#### rebuild_root_sheet

Rebuild root schematic sheet pins from sub-sheet hierarchical labels. Reads all sub-sheets referenced by the root schematic, extracts hierarchical labels, classifies them as input/output/bidirectional, and regenerates sheet pins with correct positioning on LEFT (inputs) or RIGHT (outputs) of each sheet symbol.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"rebuild_root_sheet"` |
| `target_file` | string | Relative path to the root `.kicad_sch` file |

**Example:**

```json
{
  "root": {
    "op_type": "rebuild_root_sheet",
    "target_file": "motor-driver.kicad_sch"
  }
}
```

**Returns:** List of results per sub-sheet with `sheet_name`, `pins_placed`, `labels_placed`, and `pin_details` including positioning.

---

#### update_symbols_from_library

Re-embed symbols from their libraries when embedded definitions diverge from library versions.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"update_symbols_from_library"` |
| `target_file` | string | Relative path to `.kicad_sch` file |

**Optional fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `references` | array | `null` | Specific references to update; null updates all mismatches |
| `dry_run` | bool | `false` | Report mismatches without modifying the file |

---

#### fix_shorted_nets

Detect positions where multiple net names connect to the same items and remove the losing label according to strategy.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"fix_shorted_nets"` |
| `target_file` | string | Relative path to `.kicad_sch` file |

**Optional fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `strategy` | string | `"keep_first"` | One of: keep_first, keep_last, manual |
| `keep_nets` | array | `null` | Net names to keep for manual strategy |
| `dry_run` | bool | `false` | Report shorts without modifying the file |

---

#### fix_pin_type_mismatches

Update embedded symbol pin electrical types to resolve pin-to-pin ERC violations.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"fix_pin_type_mismatches"` |
| `target_file` | string | Relative path to `.kicad_sch` file |

**Optional fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `pin_type_map` | object | `null` | Map from old type to new type, e.g. `{"unspecified": "passive"}` |
| `dry_run` | bool | `false` | Report changes without modifying the file |

---

#### place_missing_units

Place unplaced units of multi-unit symbols adjacent to existing units.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"place_missing_units"` |
| `target_file` | string | Relative path to `.kicad_sch` file |

**Optional fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `references` | array | `null` | Specific references to fix; null fixes all |
| `offset_x` | float | `25.4` | Horizontal spacing between units in mm |
| `offset_y` | float | `0.0` | Vertical spacing between units in mm |
| `dry_run` | bool | `false` | Report placements without modifying the file |

---

#### remove_dangling_wires

Remove wire segments with endpoints not connected to pins, labels, junctions, or other wire intersections.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"remove_dangling_wires"` |
| `target_file` | string | Relative path to `.kicad_sch` file |

**Optional fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `max_length_mm` | float | `null` | Only remove wires shorter than this length; null means no limit |
| `dry_run` | bool | `false` | Report removals without modifying the file |

---

#### break_wire_shorts

Remove bridge wires that short different nets together.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"break_wire_shorts"` |
| `target_file` | string | Relative path to `.kicad_sch` file |

**Optional fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `net_pairs` | array | `null` | Specific net pairs to break, e.g. `[["ADC_IN_1", "GND"]]`; null breaks all detected shorts |
| `strategy` | string | `"shortest_path"` | One of: shortest_path, all_bridges |
| `dry_run` | bool | `false` | Report bridge wires without modifying the file |

---

#### erc_auto_fix

Run ERC, dispatch repairs by violation type, and iterate until violations are fixed or the iteration limit is reached.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"erc_auto_fix"` |
| `target_file` | string | Relative path to `.kicad_sch` file |

**Optional fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `max_iterations` | int | `3` | Maximum repair iterations (1-10) |

---

## Constraints

All operations must satisfy these constraints. Violations produce clear error messages from the Pydantic validator.

### target_file constraints

- Must be a **relative path** (no leading `/`)
- Must end in `.kicad_sch`, `.kicad_pcb`, `.kicad_sym`, `.kicad_mod`, `.kicad_dru`, or `.kicad_pro`, or be named `sym-lib-table` or `fp-lib-table`
- No path traversal (`..` segments)
- No null bytes
- Length: 1-512 characters

### String length limits

| Field | Min | Max |
|-------|-----|-----|
| `reference` | 1 | 64 |
| `library_id` | 1 | 256 |
| `value` | 0 | 256 |
| `property_name` | 1 | 128 |
| `new_value` | 0 | 1024 |
| `net_name` | 0 | 64 |
| `footprint_lib_id` | 1 | 256 |
| `prefix` / `prefix_filter` | 0 | 16 |

### Atomic operations

- One mutation per operation (no compound operations)
- One target file per operation
- Operations are wrapped in transactions with automatic rollback on failure

### Count limits

- `duplicate_component.count`: 1-100
- `array_replicate.count`: 1-100

---

## Workflow Guidance

### Before editing

1. **Read the target file first** to understand current state. Use `Read` to inspect the KiCad file and understand existing components, nets, and structure.
2. **Use exact reference designators** from the file. References are case-sensitive: `R1` is not the same as `r1`. Power symbols may use `#PWR01` format.
3. **Position coordinates are in millimeters** (mils are not supported).
4. **Check for unannotated components** (references ending in `?`) before operations that require specific designators.

### Constructing operations

1. Wrap the operation object in a `{"root": {...}}` envelope. The `root` key is required by the discriminated union schema.
2. Always include `op_type` as the discriminator field. It determines which operation model validates the rest of the payload.
3. Omit optional fields you do not need -- defaults will be applied.
4. For `position` / `spacing` objects, `x` and `y` are required. `angle` defaults to `0.0` if omitted.

### After editing

1. **Suggest running validation** if ERC/DRC is available for the target file type.
2. **Check round-trip fidelity** by reading the file back to confirm the change was serialized correctly.
3. **Report rollback status** if the operation failed -- the transaction system automatically reverts partial changes.

---

## Error Handling

### target_file validation fails

The error message includes the specific constraint violated:
- `"target_file contains null bytes"` -- null byte injection attempt
- `"target_file must be a relative path"` -- absolute path rejected
- `"target_file must not contain '..' path traversal"` -- path traversal rejected
- `"target_file must be a KiCad file type"` -- wrong extension

### Reference not found

If the specified reference does not exist in the target file, the error suggests listing existing components first. Use `Read` to inspect the file and find valid reference designators.

### Operation execution fails

If execution fails after validation passes, the error includes:
- A description of what went wrong
- A rollback confirmation indicating the file was restored to its pre-operation state
- The operation type and target file for audit traceability

### Net name validation

Net names reject whitespace-only strings. If a name is `"   "` (spaces only), the validator raises a clear error. Empty string `""` for `add_net.net_name` triggers auto-generation.

---

## Operation Quick Reference

| Operation | File Types | Required Fields |
|-----------|-----------|-----------------|
| `add_component` | sch, pcb | target_file, library_id, position |
| `remove_component` | sch, pcb | target_file, reference |
| `move_component` | sch, pcb | target_file, reference, position |
| `modify_property` | sch, pcb | target_file, reference, property_name, new_value |
| `duplicate_component` | sch, pcb | target_file, source_reference |
| `array_replicate` | sch, pcb | target_file, source_reference, pattern, spacing |
| `embed_symbol` | sch | target_file, lib_id, library_path |
| `swap_symbol` | sch | target_file, reference, new_lib_id |
| `add_net` | pcb | target_file |
| `remove_net` | pcb | target_file, net_name |
| `rename_net` | pcb | target_file, old_name, new_name |
| `renumber_refs` | sch | target_file |
| `validate_refs` | sch | target_file |
| `annotate` | sch | target_file |
| `cross_ref_check` | sch | target_file |
| `assign_footprint` | sch | target_file, reference, footprint_lib_id |
| `swap_footprint` | pcb | target_file, reference, new_footprint_lib_id |
| `validate_footprint` | all | target_file, footprint_lib_id |
| `verify_pin_map` | all | target_file, reference, footprint_lib_id |
| `update_footprint_from_library` | pcb | target_file, reference |
| `add_wire` | sch | target_file, start_x, start_y, end_x, end_y |
| `connect_pins` | sch | target_file, source, target |
| `add_label` | sch | target_file, name, position |
| `add_power` | sch | target_file, name, position |
| `add_no_connect` | sch | target_file, position |
| `add_junction` | sch | target_file, position |
| `remove_wire` | sch | target_file, uuid |
| `remove_label` | sch | target_file, uuid, label_type |
| `remove_junction` | sch | target_file, uuid |
| `remove_no_connect` | sch | target_file, uuid |
| `add_lib_entry` | lib-table | target_file, lib_name, uri |
| `remove_lib_entry` | lib-table | target_file, lib_name |
| `list_lib_entries` | lib-table | target_file |
| `add_net_class` | dru | target_file, name, clearance, track_width, via_diameter, via_drill |
| `assign_net_class` | pcb | target_file, net_name, net_class_name |
| `modify_net_class` | dru | target_file, name |
| `remove_net_class` | dru | target_file, name |
| `list_net_classes` | dru | target_file |
| `add_design_rule` | dru | target_file, name, constraint_type |
| `modify_design_rule` | dru | target_file, name |
| `remove_design_rule` | dru | target_file, name |
| `list_design_rules` | dru | target_file |
| `modify_project_settings` | pro | target_file, updates |
| `add_copper_zone` | pcb | target_file, net_name |
| `modify_copper_zone` | pcb | target_file, zone_uuid |
| `remove_copper_zone` | pcb | target_file, zone_uuid or zone_index |
| `set_board_outline` | pcb | target_file, width, height |
| `auto_route` | pcb | target_file |
| `repair_schematic` | sch | target_file |
| `validate_power_nets` | sch | target_file |
| `validate_schematic` | sch | target_file, check_symbol_resolution, check_format, check_power_nets, check_annotation |
| `parse_erc` | sch | target_file |
| `extract_violation_positions` | sch | target_file, violation_type |
| `validate_hlabels` | sch | target_file, expected_labels |
| `convert_kicad6_to_10` | sch | target_file |
| `snap_to_grid` | sch | target_file, grid_mm |
| `add_power_flag` | sch | target_file |
| `rebuild_root_sheet` | sch | target_file |
| `update_symbols_from_library` | sch | target_file |
| `fix_shorted_nets` | sch | target_file |
| `fix_pin_type_mismatches` | sch | target_file |
| `place_missing_units` | sch | target_file |
| `remove_dangling_wires` | sch | target_file |
| `break_wire_shorts` | sch | target_file |
| `erc_auto_fix` | sch | target_file |
| `create_schematic` | new sch | target_file |
| `create_pcb` | new pcb | target_file |
| `create_project` | new pro | target_file |
| `create_symbol` | sym | target_file, symbol_name |
| `create_footprint` | mod | target_file, footprint_name |
| `add_sheet` | sch | target_file, sheet_name, file_name, position |
| `add_sheet_pin` | sch | target_file, sheet_uuid, pin_name, position |
| `navigate_hierarchy` | sch | target_file |
| `query_connectivity` | pcb | target_file, query_type |
| `propagate_symbol_change` | sch, pcb | target_file, target_files, old_lib_id, new_lib_id |

---

## Component Search MCP Server

kicad-agent includes an MCP server for searching electronic components via JLCPCB/EasyEDA. This allows AI agents to find parts, retrieve pin/pad data, and get datasheet URLs without leaving the conversation.

### Setup

Add to your MCP settings (Claude Code or Claude Desktop):

```json
{
  "mcpServers": {
    "kicad-component-search": {
      "command": "kicad-component-search"
    }
  }
}
```

Or via the CLI: `kicad-agent component-search`

No API key required — all endpoints are anonymous.

### Available Tools

#### search_components

Search JLCPCB by keyword. Returns LCSC numbers, names, packages, stock, price, and datasheet URLs.

```
keyword (required): Search query (e.g., "STM32", "NE555", "100nF 0402")
limit: Maximum results, 1-50 (default: 10)
part_type: "basic" for stocked basics, "extended" for extended parts
```

#### get_component_details

Get full CAD data for a specific LCSC part — schematic pins (with KiCad-compatible electrical types) and footprint pads.

```
lcsc_id (required): LCSC part number (e.g., "C83700")
```

Pin types returned as KiCad-compatible strings: `passive`, `input`, `output`, `bidirectional`, `power_in`.

#### search_and_detail

Combined search + detail in one call. Returns top N results with full pin/pad data.

```
keyword (required): Search query
detail_limit: Number of top results to get CAD data for (default: 3)
search_limit: Total search results (default: 10)
```

#### get_component_suggestions

Quick suggestion list — LCSC, name, package, stock only. Useful for autocomplete.

```
keyword (required): Search query
limit: Maximum suggestions (default: 5)
```

### Example Workflow

1. `search_components("STM32F103")` → get LCSC number + datasheet
2. `get_component_details("C83700")` → get pin names/types and footprint pads
3. Use pin data with `create_symbol` to build a KiCad symbol library entry

---

## Analyze Operation

Analyze a KiCad PCB or schematic file using the fine-tuned spatial reasoning model.

**Usage:** `/kicad-agent analyze <path-to-kicad-file>`

**What it does:**
1. Parses the KiCad file to extract board statistics (components, nets, dimensions)
2. Constructs a PCB analysis prompt
3. Generates N reasoning chains (default: 4) using the GRPO-trained model
4. Scores each chain with the neural reward model (format, quality, accuracy)
5. Returns the highest-scoring chain

**Output includes:**
- Coordinate-grounded reasoning chain with `<point x,y>` spatial references
- Component analysis and connectivity assessment
- Spatial analysis and routing assessment
- Quality scores (format, quality, accuracy, composite)

**CLI flags (direct invocation):**
- `--n-best N`: Number of chains to generate (default: 4, max: 16)
- `--reward-model DIR`: Explicit reward model directory
- `--adapter DIR`: Explicit LoRA adapter directory
- `--max-tokens N`: Max tokens per chain (default: 1024)
- `--verbose`: Show per-chain scores and timing
