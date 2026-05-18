"""Modify component property operation handler.

Updates existing properties (Reference, Value, Footprint, Datasheet) or adds
new custom properties when they do not exist. Handles Reference changes by
propagating the update to symbol_instances entries.

Security (threat model):
- T-04-11: Reference changes propagate to symbol_instances -- no orphaned instances
- T-04-12: Property values are strings with max_length=1024 from schema validation

Usage:
    from kicad_agent.ops.modify_property import modify_property, ModifyPropertyError

    op = ModifyPropertyOp(
        target_file="schematic.kicad_sch",
        reference="J1",
        property_name="Value",
        new_value="MyConnector",
    )
    result = modify_property(op, ir)
"""

from typing import Any

from kiutils.items.common import Effects, Font, Position, Property

from kicad_agent.ops.schema import ModifyPropertyOp


class ModifyPropertyError(Exception):
    """Error raised when modify_property operation fails."""


# Standard KiCad component properties
_STANDARD_PROPERTIES = frozenset({"Reference", "Value", "Footprint", "Datasheet"})


def modify_property(
    op: ModifyPropertyOp,
    ir: Any,
) -> dict[str, Any]:
    """Modify a component property with add/update semantics.

    If the property already exists on the component, its value is updated.
    If the property does not exist, a new Property is created and appended.

    Special handling for Reference changes (T-04-11): updates the property
    on the component and propagates the change to symbol_instances entries.

    Args:
        op: ModifyPropertyOp with reference, property_name, and new_value.
        ir: SchematicIR wrapping the parsed schematic.

    Returns:
        Dict with reference, property_name, old_value, and new_value.

    Raises:
        ModifyPropertyError: If component with given reference is not found.
    """
    # Find component by reference
    component = ir.get_component_by_ref(op.reference)
    if component is None:
        raise ModifyPropertyError(
            f"Component not found: {op.reference!r}"
        )

    # Search for existing property with matching key
    existing_prop = None
    for prop in component.properties:
        if prop.key == op.property_name:
            existing_prop = prop
            break

    if existing_prop is not None:
        # Update existing property value
        old_value = existing_prop.value
        existing_prop.value = op.new_value
    else:
        # Create new property with default styling
        old_value = None
        new_prop = Property(
            key=op.property_name,
            value=op.new_value,
            id=len(component.properties),
            position=Position(),
            effects=Effects(font=Font(height=1.27, width=1.27)),
        )
        component.properties.append(new_prop)

    # T-04-11: Update symbol_instances for Reference changes
    if op.property_name == "Reference":
        _update_symbol_instances(ir, op.reference, op.new_value)

    # Record mutation for audit trail
    ir._record_mutation(
        "modify_property",
        {
            "reference": op.reference,
            "property": op.property_name,
            "old_value": old_value,
            "new_value": op.new_value,
        },
    )

    return {
        "reference": op.reference,
        "property_name": op.property_name,
        "old_value": old_value,
        "new_value": op.new_value,
    }


def _update_symbol_instances(ir: Any, old_reference: str, new_reference: str) -> None:
    """Update symbol_instances entries when a Reference property is changed.

    T-04-11: Ensures that symbol_instances references stay in sync with
    the component's Reference property, preventing orphaned instances.

    Handles both ProjectInstance (name field) and SymbolProjectPath
    (reference field) formats.

    Args:
        ir: SchematicIR with access to the kiutils schematic object.
        old_reference: The previous reference designator.
        new_reference: The new reference designator.
    """
    schematic = ir._parse_result.kiutils_obj
    if not schematic.symbolInstances:
        return

    for instance in schematic.symbolInstances:
        # SymbolProjectPath format: paths list with reference field
        if hasattr(instance, "paths"):
            for path in instance.paths:
                if hasattr(path, "reference") and path.reference == old_reference:
                    path.reference = new_reference

        # ProjectInstance format: name field contains reference
        if hasattr(instance, "name") and instance.name == old_reference:
            instance.name = new_reference
