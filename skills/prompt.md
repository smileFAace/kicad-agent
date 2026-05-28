# KiCad Agent -- Operation Reference

This reference documents all operations supported by kicad-agent. Claude uses these schemas to construct valid JSON operations that the Python backend validates and executes against KiCad files.

**Key principle:** The LLM never touches raw S-expressions. It emits structured JSON intents, and the Python tool layer mutates the AST, serializes valid KiCad files, and validates via ERC/DRC gates.

**Supported file types:** `.kicad_sch` (schematic), `.kicad_pcb` (PCB), `.kicad_sym` (symbol library), `.kicad_mod` (footprint library)

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

### Bus Operations

#### add_bus

Add a bus to a schematic with member nets.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"add_bus"` |
| `target_file` | string | Relative path to KiCad schematic file (`.kicad_sch`) |
| `bus_name` | string | Bus name (1-64 chars) |
| `member_nets` | array | List of net names that belong to this bus (1-32 members, each max 64 chars) |

**Example:**

```json
{
  "root": {
    "op_type": "add_bus",
    "target_file": "motor-driver.kicad_sch",
    "bus_name": "SPI_BUS",
    "member_nets": ["SPI_MOSI", "SPI_MISO", "SPI_SCK", "SPI_CS"]
  }
}
```

---

#### remove_bus

Remove a bus from a schematic.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"remove_bus"` |
| `target_file` | string | Relative path to KiCad schematic file |
| `bus_name` | string | Bus name to remove (1-64 chars) |

**Example:**

```json
{
  "root": {
    "op_type": "remove_bus",
    "target_file": "motor-driver.kicad_sch",
    "bus_name": "SPI_BUS"
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

### Schematic Repair Operations

#### parse_erc

Parse an ERC (Electrical Rules Check) JSON report and return structured violations.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"parse_erc"` |
| `target_file` | string | Relative path to `.kicad_sch` file |
| `erc_report_path` | string | Path to the ERC JSON report file |

**Example:**

```json
{
  "root": {
    "op_type": "parse_erc",
    "target_file": "motor-driver.kicad_sch",
    "erc_report_path": "erc_report.json"
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
| `erc_report_path` | string | Path to the ERC JSON report file |
| `violation_type` | string | Type of violation to filter (e.g. `"ERC_ERROR"`, `"ERC_WARNING"`) |

**Example:**

```json
{
  "root": {
    "op_type": "extract_violation_positions",
    "target_file": "motor-driver.kicad_sch",
    "erc_report_path": "erc_report.json",
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

Snap all coordinates in a schematic to the specified grid size.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"snap_to_grid"` |
| `target_file` | string | Relative path to `.kicad_sch` file |
| `grid_size` | float | Grid size in mm (default 0.01, min 0.001) |

**Example:**

```json
{
  "root": {
    "op_type": "snap_to_grid",
    "target_file": "motor-driver.kicad_sch",
    "grid_size": 0.254
  }
}
```

---

#### add_power_flag

Add power flags (PWR_FLAG) to undriven power pins identified by an ERC report.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"add_power_flag"` |
| `target_file` | string | Relative path to `.kicad_sch` file |
| `erc_report_path` | string | Path to the ERC JSON report file |

**Example:**

```json
{
  "root": {
    "op_type": "add_power_flag",
    "target_file": "motor-driver.kicad_sch",
    "erc_report_path": "erc_report.json"
  }
}
```

---

#### place_no_connects_from_erc

Place no-connect markers on unconnected pins identified by an ERC report.

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `op_type` | string | Must be `"place_no_connects_from_erc"` |
| `target_file` | string | Relative path to `.kicad_sch` file |
| `erc_report_path` | string | Path to the ERC JSON report file |

**Example:**

```json
{
  "root": {
    "op_type": "place_no_connects_from_erc",
    "target_file": "motor-driver.kicad_sch",
    "erc_report_path": "erc_report.json"
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

## Constraints

All operations must satisfy these constraints. Violations produce clear error messages from the Pydantic validator.

### target_file constraints

- Must be a **relative path** (no leading `/`)
- Must end in `.kicad_sch`, `.kicad_pcb`, `.kicad_sym`, or `.kicad_mod`
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
| `bus_name` | 1 | 64 |
| `member_nets` items | 0 | 64 |
| `footprint_lib_id` | 1 | 256 |
| `prefix` / `prefix_filter` | 0 | 16 |

### Atomic operations

- One mutation per operation (no compound operations)
- One target file per operation
- Operations are wrapped in transactions with automatic rollback on failure

### Count limits

- `duplicate_component.count`: 1-100
- `array_replicate.count`: 1-100
- `add_bus.member_nets`: 1-32 items

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

Net names and bus names reject whitespace-only strings. If a name is `"   "` (spaces only), the validator raises a clear error. Empty string `""` for `add_net.net_name` triggers auto-generation.

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
| `add_net` | pcb | target_file |
| `remove_net` | pcb | target_file, net_name |
| `rename_net` | pcb | target_file, old_name, new_name |
| `add_bus` | sch | target_file, bus_name, member_nets |
| `remove_bus` | sch | target_file, bus_name |
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
| `add_label` | sch | target_file, name, position |
| `add_power` | sch | target_file, name, position |
| `add_no_connect` | sch | target_file, position |
| `add_junction` | sch | target_file, position |
| `add_lib_entry` | lib-table | target_file, lib_name, uri |
| `remove_lib_entry` | lib-table | target_file, lib_name |
| `add_net_class` | dru | target_file, name, clearance, track_width, via_diameter, via_drill |
| `assign_net_class` | pcb | target_file, net_name, net_class_name |
| `add_design_rule` | dru | target_file, name, constraint_type |
| `repair_schematic` | sch | target_file |
| `validate_power_nets` | sch | target_file |
| `validate_schematic` | sch | target_file, check_symbol_resolution, check_format, check_power_nets, check_annotation |
| `add_copper_zone` | pcb | target_file, net_name |
| `set_board_outline` | pcb | target_file, width, height |
| `auto_route` | pcb | target_file |
| `create_schematic` | new sch | target_file |
| `create_pcb` | new pcb | target_file |
| `create_project` | new pro | target_file |
| `create_symbol` | sym | target_file, symbol_name |
| `parse_erc` | sch | target_file, erc_report_path |
| `extract_violation_positions` | sch | target_file, erc_report_path, violation_type |
| `validate_hlabels` | sch | target_file, expected_labels |
| `convert_kicad6_to_10` | sch | target_file |
| `snap_to_grid` | sch | target_file, grid_size |
| `add_power_flag` | sch | target_file, erc_report_path |
| `place_no_connects_from_erc` | sch | target_file, erc_report_path |
| `rebuild_root_sheet` | sch | target_file |
| `embed_symbol` | sch | target_file, lib_id, library_path |
| `swap_symbol` | sch | target_file, reference, new_lib_id |

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
