'''
Copyright (C) 2025 Wayne Dixon
wayen@cgcookie.com
Created by Wayne Dixon
    This file is part of Apply modifier with shape keys
    Export to .blend is free software; you can redistribute it and/or
    modify it under the terms of the GNU General Public License
    as published by the Free Software Foundation; either version 3
    of the License, or (at your option) any later version.
    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.
    You should have received a copy of the GNU General Public License
    along with this program; if not, see <https://www.gnu.org/licenses/>.
'''


import bpy
import re
import code
from bpy.types import (
    Context,
    Key,
    Mesh,
    Object,
    Operator,
    ShapeKey,
)

from collections.abc import Iterator
from types import SimpleNamespace
from typing import cast, TypeVar

import numpy as np
T = TypeVar("T", bound=Operator)

# From apply modifiers to shapekeys


# Helper functions
    
def disable_modifiers(context, selected_modifiers):
    ''' disables any modifiers that are not selected so the mesh can be calculated.
    Returns a list of modifiers it changed so they can be reset later '''
    saved_enabled_modifiers = []

    for modifier in context.object.modifiers:
        if modifier.name not in selected_modifiers and modifier.show_viewport:
            saved_enabled_modifiers.append(modifier)
            modifier.show_viewport = False
    return saved_enabled_modifiers


def duplicate_object(context, obj):
    '''Copy the object, make it active and return it '''
    new_obj = obj.copy()
    new_obj.data = obj.data.copy()
    context.collection.objects.link(new_obj)
    context.view_layer.objects.active = new_obj
    return new_obj


def evaluate_mesh(context, obj):
    """Low-level alternative to `bpy.ops.object.convert` for converting to meshes"""
    depsgraph = context.evaluated_depsgraph_get()
    eval_obj = obj.evaluated_get(depsgraph)
    mesh = context.blend_data.meshes.new_from_object(eval_obj, preserve_all_data_layers=True, depsgraph=depsgraph)
    return mesh


def apply_modifier_to_object(context, obj, selected_modifiers):
    ''' Disables all modifers except the selected ones
    Creates a new mesh from that output and swaps it out
    Removes the selected modifiers
    Deletes the old mesh and restores the other modifiers to what they were
    '''
    context.view_layer.objects.active = obj

    # Disable all modifiers (except selected)
    saved_enabled_modifiers = disable_modifiers(context, selected_modifiers)

    # Make sure all selected modifers are enabled
    for modifier_name in selected_modifiers:
        #code.interact(local=locals())
        modifier = obj.modifiers.get(modifier_name)
        modifier.show_viewport = True

    # evaluate new mesh and swap it out
    new_mesh = evaluate_mesh(context, obj)
    old_mesh = obj.data
    old_mesh_name = old_mesh.name
    obj.data = new_mesh

    # Delete the selected modifiers from the object
    for modifier in selected_modifiers:
        obj.modifiers.remove(obj.modifiers[modifier])

    # Delete the old mesh and rename the data block
    context.blend_data.meshes.remove(old_mesh)
    obj.data.name = old_mesh_name

    # restore the previously enabled modifiers
    if len(saved_enabled_modifiers) > 0:
        for modifier in saved_enabled_modifiers:
            modifier.show_viewport = True


def save_shape_key_properties(obj):
    ''' This function will save the settings on the shape keys (min/max etc) and return them as a dictionary'''
    properties_dict = {}
    for idx, key_block in enumerate(obj.data.shape_keys.key_blocks): # will skip index 0 (Basis)
        if idx == 0:
            continue
        properties_object = {p.identifier: getattr(key_block, p.identifier) for p in key_block.bl_rna.properties if not p.is_readonly}
        properties_dict[key_block.name] = {"properties": properties_object}
    return properties_dict


def restore_shape_key_properties(obj, property_dict):
    ''' Restores the settings for each shape key (min/max etc) '''
    for idx, key_block in enumerate(obj.data.shape_keys.key_blocks): # will skip index 0 (Basis)
        if idx == 0:
            continue
        properties = list(property_dict.items())[idx - 1][1]['properties']
        for prop, value in properties.items():
                setattr(key_block, prop, value)

def join_as_shape(temp_obj, original_obj):
    '''Join the temp object back to the original as a shape key 
    Vertex positions are transferred by index.
    Different number of vertices or index will give unpredictable results
    '''

    # create a basis shape on the temp object to make the next step easier
    temp_obj_shape = temp_obj.shape_key_add(from_mix=False)
    # temp_obj_verts = temp_obj.data.shape_keys.key_blocks[1:]
    new_org_shape = original_obj.shape_key_add(from_mix=False)

    # Transfer Vertex Positions
    for source_vert, target_vert in zip(temp_obj_shape.data, new_org_shape.data):
        target_vert.co = source_vert.co

    # return {'FINISHED'}


def save_shape_key_drivers(obj, property_dict):
    ''' Copy drivers for shape key properties by checking the property dictionary against the driver paths.
    returns a new dictionary with the drivers and the properties on the shape keys they drive'''

    drivers = {}

    # Ensure the object has shape keys animation data
    if not obj.data.shape_keys.animation_data:
        # print(f"No animation data found for {obj.name}.")  # DEBUG
        return drivers

    # Loop through all the drivers in the shape keys animation data
    for driver in obj.data.shape_keys.animation_data.drivers:
        # Only consider drivers related to shape key properties
        shape_key_drivers = []

        # Extract the property name from the data_path
        data_path_parts = driver.data_path.split('.')
        if len(data_path_parts) > 1:
            property_name = data_path_parts[-1]  # The last part of the data path is the property name (e.g. 'value', 'slider_min', 'slider_max')

            # Check if the property is in the dictionary
            properties = list(property_dict.items())

            # Find the shape key name using a regular expression
            match = re.search(r'key_blocks\["(.*)"\]', driver.data_path)

            shape_key_name = match.group(1)

            # Create a dictionary for the driver data
            driver_data = {
                "driver": driver,
                "property": property_name
            }

            # Append the driver data to the shape_key_drivers list
            if shape_key_name not in drivers:
                drivers[shape_key_name] = []

            drivers[shape_key_name].append(driver_data)

    return drivers


def restore_shape_key_drivers(obj, copy_obj,drivers, context):
    ''' Restore drivers for shape key properties '''

    if not obj.data.shape_keys.animation_data:
        obj.data.shape_keys.animation_data_create()

    for shape_key_name, shape_key_drivers in drivers.items():
        # Find the shape key block by name
        shape_key_block = obj.data.shape_keys.key_blocks.get(shape_key_name)
        if not shape_key_block:            
            continue

        for driver_data in shape_key_drivers:
            # Extract the fcurve and property
            source_fcurve = driver_data["driver"]
            property_name = driver_data["property"]

            # Add the driver to the shape key property
            try:
                new_driver = shape_key_block.driver_add(property_name)

                # set the type
                new_driver.driver.type = source_fcurve.driver.type

                # Copy the driver expression if it exists
                if source_fcurve.driver.expression:
                    new_driver.driver.expression = source_fcurve.driver.expression

                # Copy the driver variables
                for var in source_fcurve.driver.variables:
                    new_var = new_driver.driver.variables.new()
                    new_var.name = var.name
                    new_var.type = var.type

                    # Copy each target for the variable
                    for idx, target in enumerate(var.targets):
                        new_var.targets[idx].id_type = target.id_type
                        if target.id == copy_obj: # if the target is point to the copy object this should be changed to the orginal object
                            target.id = obj
                        new_var.targets[idx].id = target.id
                        new_var.targets[idx].data_path = target.data_path
                        new_var.targets[idx].bone_target = target.bone_target
                        new_var.targets[idx].transform_type = target.transform_type
                        new_var.targets[idx].transform_space = target.transform_space

                # print(f"Restored driver for {property_name} on shape key {shape_key_name}.")  #DEBUG

            except Exception as e:
                print(f"Failed to restore driver for {property_name} on shape key {shape_key_name}: {str(e)}")
                # self.report({'ERROR'}, f"Failed to restore driver for {property_name} on shape key {shape_key_name}: {str(e)}")


def copy_shape_key_animation(source_obj, target_obj):
    ''' Relink all shape key animations (keyframes) for all properties from one object to another '''

    # Ensure the source object has an action for shape keys
    if not source_obj.data.shape_keys.animation_data:
        # print(f"{source_obj.name} has no animation data for shape keys.")# DEBUG
        return

    if not source_obj.data.shape_keys.animation_data.action:
        # print(f"{source_obj.name} has no action for shape keys.") # DEBUG
        return

    # Link the existing action to the target object
    if not target_obj.data.shape_keys.animation_data:
        target_obj.data.shape_keys.animation_data_create()  # Create animation data for the target shape key if needed
    target_obj.data.shape_keys.animation_data.action = source_obj.data.shape_keys.animation_data.action
    
    # Link the existing action slot to the action (Blender ver > 4.4)
    if bpy.app.version >= (4, 4, 0):
        target_obj.data.shape_keys.animation_data.action_slot = source_obj.data.shape_keys.animation_data.action_slot

    # print(f"Shape key animations copied from {source_obj.name} to {target_obj.name}.") # DEBUG


# Primary function (this gets imported and used by the operator)
def apply_modifiers_with_shape_keys(context, selected_modifiers):
    ''' Apply the selected modifiers to the mesh even if it has shape keys '''
    original_obj = context.view_layer.objects.active
    shapes_count = len(original_obj.data.shape_keys.key_blocks) if original_obj.data.shape_keys else 0
    error_message = None

    if shapes_count == 1: # if there is only a Basis shape, delete the shape and apply the modifiers
        original_obj.shape_key_remove(original_obj.data.shape_keys.key_blocks[0])
        apply_modifier_to_object(context, original_obj, selected_modifiers)
        return True, None

    # Save the pin option setting and active shape key index
    pin_setting = original_obj.show_only_shape_key
    saved_active_shape_key_index = original_obj.active_shape_key_index

    # Duplicate the object
    copy_obj = duplicate_object(context, original_obj)

    # Save the shape key properties
    shape_key_properties = save_shape_key_properties(original_obj)

    # Copy drivers for shape keys (from the copy because the original ones will be gone in a moment)
    shape_key_drivers = save_shape_key_drivers(copy_obj, shape_key_properties[original_obj.active_shape_key.name])

    # Remove all shape keys and apply modifiers on the original

    original_obj.shape_key_clear()
    apply_modifier_to_object(context, original_obj, selected_modifiers)

    # Add a basis shape key back to the original object
    original_obj.shape_key_add(name=copy_obj.data.shape_keys.key_blocks[0].name,from_mix=False)

    # Loop over the original shape keys, create a temp mesh, apply single shape, apply modifers and merge back to the original (1 shape at a time)
    for i, (key_block_name, properties) in enumerate(shape_key_properties.items()):
        # Create a temp object
        context.view_layer.objects.active = copy_obj
        temp_obj = duplicate_object(context, copy_obj)

        # Pin the shape we want
        
        #code.interact(local=locals())
        temp_obj.show_only_shape_key = True
        temp_obj.active_shape_key_index = i + 1 
        shape_key_name = temp_obj.active_shape_key.name
        temp_obj_old_mesh = temp_obj.data

        # Disable all modifiers (including selected)
        for modifier in temp_obj.modifiers:
            modifier.show_viewport = False
        

        # Now freeze the mesh by applying the selected modifiers
        apply_modifier_to_object(context, temp_obj, selected_modifiers)
        
        # Verify the meshes have the same amount of verts
        if len(original_obj.data.vertices) != len(temp_obj.data.vertices):
            error_message = f"{shape_key_name} failed because the mesh no longer have the same amount of vertices after applying selected modifier(s)."
            # Clean up the temp object and try to move on
            context.blend_data.objects.remove(temp_obj)
            continue

        # Transfer the temp object as a shape back to orginal
        join_as_shape(temp_obj, original_obj)

        # Clean up the temp object
        context.blend_data.meshes.remove(temp_obj.data)


    # Restore shape key properties
    restore_shape_key_properties(original_obj, shape_key_properties)

    # Restore any shape key animation
    copy_shape_key_animation(copy_obj, original_obj)

    # Restore any shape key drivers
    restore_shape_key_drivers(original_obj, copy_obj, shape_key_drivers, context)

    # Clean up the duplicate object
    context.blend_data.meshes.remove(copy_obj.data)

    # Restore the pin option setting and active shape key index
    original_obj.show_only_shape_key = pin_setting
    original_obj.active_shape_key_index =  saved_active_shape_key_index

    # Make sure the original object is active before finishing
    context.view_layer.objects.active = original_obj

    # Report the error message if any
    if error_message:
        return False, error_message

    return True, None
            



#Apply shapekey to basis

def set_operator_description_from_doc(cls: type[T]) -> type[T]:
    """
    Clean up an Operator's .__doc__ for use as bl_description.
    :param cls: Operator subclass.
    :return: The Operator subclass argument.
    """
    doc = cls.__doc__
    if not doc or getattr(cls, "bl_description", None) is not None:
        # There is nothing to do if there is no `__doc__` or if `bl_description` has been set manually.
        return cls
    # Strip the entire string first to remove leading/trailing newlines and other whitespace.
    doc = doc.strip()
    if doc[-1] == ".":
        # Remove any trailing "." because Blender adds one automatically.
        doc = doc[:-1]
    # Remove leading/trailing whitespace from each line.
    cls.bl_description = "\n".join(line.strip() for line in doc.splitlines())
    return cls


def _shape_key_co_memory_as_ndarray(shape_key: ShapeKey, do_check: bool = True):
    """
    ShapeKey.data elements have a dynamic typing based on the Object the shape keys are attached to, which makes them
    slower to access with foreach_get. For 'MESH' type Objects, the elements are always ShapeKeyPoint type and their
    data is stored contiguously, meaning an array can be constructed from the pointer to the first ShapeKeyPoint
    element.

    Creating an array from a pointer is inherently unsafe, so this function does a number of checks to make it safer.
    """
    if do_check and not _fast_mesh_shape_key_co_check():
        return None
    shape_data = shape_key.data
    num_co = len(shape_data)

    if num_co < 2:
        # At least 2 elements are required to check memory size.
        return None

    co_dtype = np.dtype(np.single)

    start_address = shape_data[0].as_pointer()
    last_element_start_address = shape_data[-1].as_pointer()

    memory_length_minus_one_item = last_element_start_address - start_address

    expected_element_size = co_dtype.itemsize * 3
    expected_memory_length = (num_co - 1) * expected_element_size

    if memory_length_minus_one_item == expected_memory_length:
        # Use NumPy's array interface protocol to construct an array from the pointer.
        array_interface_holder = SimpleNamespace(
            __array_interface__=dict(
                shape=(num_co * 3,),
                typestr=co_dtype.str,
                data=(start_address, False),  # False for writable
                version=3,
            )
        )
        return np.asarray(array_interface_holder)
    else:
        return None


# Initially set to None
_USE_FAST_SHAPE_KEY_CO_FOREACH_GETSET = None


def _fast_mesh_shape_key_co_check():
    global _USE_FAST_SHAPE_KEY_CO_FOREACH_GETSET
    if _USE_FAST_SHAPE_KEY_CO_FOREACH_GETSET is not None:
        # The check has already been run and the result has been stored in _USE_FAST_SHAPE_KEY_CO_FOREACH_GETSET.
        return _USE_FAST_SHAPE_KEY_CO_FOREACH_GETSET

    tmp_mesh = None
    tmp_object = None
    try:
        tmp_mesh = bpy.data.meshes.new("")
        num_co = 100
        tmp_mesh.vertices.add(num_co)
        # An Object is needed to add/remove shape keys from a Mesh.
        tmp_object = bpy.data.objects.new("", tmp_mesh)
        shape_key = tmp_object.shape_key_add(name="")
        shape_data = shape_key.data

        if shape_key.bl_rna.properties["data"].fixed_type == shape_data[0].bl_rna:
            # The shape key "data" collection is no longer dynamically typed and foreach_get/set should be fast enough.
            _USE_FAST_SHAPE_KEY_CO_FOREACH_GETSET = False
            return False

        co_dtype = np.dtype(np.single)

        # Fill the shape key with some data.
        shape_data.foreach_set("co", np.arange(3 * num_co, dtype=co_dtype))

        # The check is this function, so explicitly don't do the check.
        co_memory_as_array = _shape_key_co_memory_as_ndarray(shape_key, do_check=False)
        if co_memory_as_array is not None:
            # Immediately make a copy in case the `foreach_get` afterward can cause the memory to be reallocated.
            co_array_from_memory = co_memory_as_array.copy()
            del co_memory_as_array
            # Check that the array created from the pointer has the exact same contents
            # as using foreach_get.
            co_array_check = np.empty(num_co * 3, dtype=co_dtype)
            shape_data.foreach_get("co", co_array_check)
            if np.array_equal(co_array_check, co_array_from_memory, equal_nan=True):
                _USE_FAST_SHAPE_KEY_CO_FOREACH_GETSET = True
                return True

        # Something didn't work.
        print("Fast shape key co access failed. Access will fall back to regular foreach_get/set.")
        _USE_FAST_SHAPE_KEY_CO_FOREACH_GETSET = False
        return False
    finally:
        # Clean up temporary objects.
        if tmp_object is not None:
            tmp_object.shape_key_clear()
            bpy.data.objects.remove(tmp_object)
        if tmp_mesh is not None:
            bpy.data.meshes.remove(tmp_mesh)


def fast_mesh_shape_key_co_foreach_get(shape_key: ShapeKey, arr: np.ndarray):
    co_memory_as_array = _shape_key_co_memory_as_ndarray(shape_key)
    if co_memory_as_array is not None:
        arr[:] = co_memory_as_array
    else:
        shape_key.data.foreach_get("co", arr)


def fast_mesh_shape_key_co_foreach_set(shape_key: ShapeKey, arr: np.ndarray):
    co_memory_as_array = _shape_key_co_memory_as_ndarray(shape_key)
    if co_memory_as_array is not None:
        co_memory_as_array[:] = arr
        # Unsure if this is required. I don't think `.update()` actually does anything, nor do I think #foreach_set
        # calls any function equivalent to `.update()` either.
        # Memory has been set directly, so call `.update()`.
        shape_key.data.update()
    else:
        shape_key.data.foreach_set("co", arr)


# Blender Classes



# As of Blender 4.0 (in commit d32748cdf4), modifying Shape Keys in Edit mode propagates changes to all Shape Keys
# recursively relative to the current Shape Key. This Operator is still useful for its ability to be run without
# swapping into Edit mode.
@set_operator_description_from_doc
class ShapeKeyToReferenceKey(Operator):
    """
    Applies the active shape key at its current strength (if non-zero) to the reference shape key (usually 'Basis'), and
    then inverts the active shape key so that it reverts its application.
    """
    # Blender 3.3 is the current oldest LTS and still has a small maximum length for Operator descriptions, so the
    # description can't be too long.
    bl_idname = "ffxiv.apply_shape_key_to_reference_key"
    # The label uses "Basis" because that is what most users are familiar with, though the reference Shape Key can have
    # any name.
    bl_label = "Apply Shape Key to Basis"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context: Context):
        obj = context.object

        if not obj:
            return cls.poll_fail("Requires an active Object")

        # Could be extended to other types that have Shape Keys, but only MESH supported for now
        if obj.type != 'MESH':
            return cls.poll_fail("The active Object must be a Mesh")

        if obj.mode == 'EDIT':
            return cls.poll_fail("The Mesh must not be in Edit mode")

        mesh = cast(Mesh, obj.data)
        shape_keys = mesh.shape_keys

        if not shape_keys:
            return cls.poll_fail("The Mesh must have Shape Keys")

        # The operator makes no sense when Shape Keys are in Absolute mode.
        if not shape_keys.use_relative:
            return cls.poll_fail("The Shape Keys must use the Relative mode")

        active_shape_key = obj.active_shape_key

        # Maybe possible if the active index is out of bounds?
        if not active_shape_key:
            return cls.poll_fail("An active Shape Key is required")

        reference_key = shape_keys.reference_key

        # If the active Shape Key is the Reference Key, then is does nothing because it is the base state of the Mesh.
        # Technically it can be relative to another Shape Key still, but this is not shown in the UI. For the purposes
        # of this operator, the Reference Key is treated as if it is always relative to itself.
        if active_shape_key == shape_keys.reference_key:
            return cls.poll_fail("The active Shape Key must be a different Shape Key to the reference Shape Key ('%s')"
                                 % reference_key.name)

        # If the active Shape Key is relative to itself, then it does nothing.
        if active_shape_key.relative_key == active_shape_key:
            return cls.poll_fail("The active Shape Key must not be relative to itself")

        return True

    def execute(self, context: Context):
        # If an object other than the active object is to be used, it can be specified using a context override.
        obj = context.object

        me = cast(Mesh, obj.data)

        # Get Shape Key which will be the new Reference Key. The `poll` function prevents this from being the current
        # Reference Key.
        new_reference_shape_key = obj.active_shape_key

        # Get sets of all Shape Keys which are recursively relative to the current Reference Key and the new reference
        # key.
        # The Shape Keys may be in their own sets if they are relative to themselves.
        relative_to_old_reference, relative_to_new_reference = get_recursive_relative_shape_keys(
            me.shape_keys, new_reference_shape_key)

        # Cancel execution if the new reference Shape Key is relative to itself (via a loop, since `poll` already
        # returns False for being immediately relative to itself since that will always do nothing).
        # If the Relative Keys loop back around, then if the key is turned into its reverse after applying, it would
        # affect all Shape Keys that it is relative to. Consider:
        # Key1 relative -> Key2
        # Key2 relative -> Key1
        # If Key1 is applied to the Reference Key, Key1 should be changed to a reversed Shape Key in order to undo the
        # application.
        # Since Key2 is relative to Key1, it has to be modified to account for the change in Key1 so that its relative
        # movement to Key1 stays the same.
        # Since Key1 is relative to Key2, it has to be modified to account for the change in Key2 so that its relative
        # movement to Key2 stays the same, but that creates an infinite loop.
        #
        # Another way of looking at it is if Key1 moves a vertex by +1, then Key2 MUST move that same vertex by -1 since
        # the two Shape Keys are relative to one other.
        # If Key1 is applied to the Reference Key, it should become a reversed Shape Key that moves a Vertex by -1
        # instead so that when it is re-applied, it undoes the initial application, but that would mean that Key2 would
        # have to become a Shape Key that moves a vertex by +1, but Key2 must keep its original relative movement of -1.
        if new_reference_shape_key in relative_to_new_reference:
            self.report({'ERROR_INVALID_INPUT'},
                        "Shape Key '%s' is recursively relative to itself, so cannot be applied on '%s'"
                        % (new_reference_shape_key.name, obj.name))
            return {'CANCELLED'}

        apply_new_reference_key(obj=obj,
                                new_ref=new_reference_shape_key,
                                keys_relative_to_new_ref=relative_to_new_reference,
                                keys_relative_to_old_ref=relative_to_old_reference)

        # The active key is now the reverse of what it was before so rename it as such.
        reversed_string = " - Reversed"
        reversed_string_len = len(reversed_string)
        old_name = new_reference_shape_key.name

        if old_name[-reversed_string_len:] == reversed_string:
            # If the last letters of the name are `reversed_string`, remove them.
            new_reference_shape_key.name = old_name[:-reversed_string_len]
        else:
            # Add `reversed_string` to the end of the name, so it is clear that this Shape Key is now the reverse of what
            # it was before.
            new_reference_shape_key.name = old_name + reversed_string

        # Setting `.value` to `0.0` will make the Mesh appear unchanged in overall shape and help to show that the
        # Operator has worked correctly.
        
        if new_reference_shape_key.slider_min > 0.0:
            new_reference_shape_key.slider_min = 0.0
        new_reference_shape_key.value = 0.0
        new_reference_shape_key.slider_min = 0.0
        # Regardless of what the max was before, 1.0 will now fully undo the applied Shape Key.
        new_reference_shape_key.slider_max = 1.0

        self.report({'INFO'}, "Applied '%s' to the Reference Key" % old_name)
        return {'FINISHED'}


# Implementation


def get_recursive_relative_shape_keys(all_shape_keys: Key,
                                      new_ref_key: ShapeKey) -> tuple[set[ShapeKey], set[ShapeKey]]:
    """
    Get all Shape Keys which are recursively relative the current Reference Key and the specified new Reference Key.
    :param all_shape_keys: Shape Key data block.
    :param new_ref_key:
    :return:
    """
    assert new_ref_key.name in all_shape_keys.key_blocks

    # `shape_key.relative_key` gets the Shape Key that `shape_key` is directly relative to.
    # `reverse_relative_map` stores all the Shape Keys that are directly relative to each Shape Key.
    reverse_relative_map = {}

    current_ref_key = all_shape_keys.reference_key
    for shape_key in all_shape_keys.key_blocks:

        # Special handling for the reference Shape Key to treat it as if its always relative to itself.
        relative_key = current_ref_key if shape_key == current_ref_key else shape_key.relative_key
        keys_relative_to_relative_key = reverse_relative_map.get(relative_key)
        if keys_relative_to_relative_key is None:
            keys_relative_to_relative_key = {shape_key}
            reverse_relative_map[relative_key] = keys_relative_to_relative_key
        else:
            keys_relative_to_relative_key.add(shape_key)

    # Find all Shape Keys that are either directly or recursively relative to the Reference Key, and the same for
    # `new_ref_key`.

    # Pretty much a depth-first search, but with loop prevention.
    def inner_recursive_loop(key, shape_set, checked_set=None):
        if checked_set is None:
            checked_set = set()

        # Prevent infinite loops by maintaining a set of Shape Keys that have been checked.
        if key not in checked_set:
            # The current Shape Key must be added to the set before the recursive call.
            checked_set.add(key)
            keys_relative_to_shape_key_inner = reverse_relative_map.get(key)
            if keys_relative_to_shape_key_inner:
                for relative_to_inner in keys_relative_to_shape_key_inner:
                    shape_set.add(relative_to_inner)
                    inner_recursive_loop(relative_to_inner, shape_set, checked_set)

    recursively_relative_to_current_ref_key = set()
    # It should work to pick a different Shape Key to apply to, so long as that Shape Key is immediately relative to
    # itself (`key.relative_key == key`). For now, the reference Shape Key is always used.
    inner_recursive_loop(all_shape_keys.reference_key, recursively_relative_to_current_ref_key)

    recursively_relative_to_new_ref_key = set()
    inner_recursive_loop(new_ref_key, recursively_relative_to_new_ref_key)

    return recursively_relative_to_current_ref_key, recursively_relative_to_new_ref_key


def vertex_group_weight_generator(mesh: Mesh, vertex_group_index: int) -> Iterator[float]:
    """
    Generator for Vertex Group weights. Yields 0.0 when a Vertex does not belong to the Vertex Group.
    :param mesh:
    :param vertex_group_index:
    :return:
    """
    # Blender has no efficient way to get all the weights for a particular Vertex Group.
    # It's pretty much always a few times faster to create a new Shape Key from mix and get its "co" with
    # #foreach_get, but that requires temporarily muting all other Shape Keys and disabling `Object.show_only_shape_key`
    # to ensure the new shape is created with the correct mix.
    # For simplicity, and because Vertex Groups are rarely used on Shape Keys, the slower access of Vertex Group weights
    # is used here.
    # https://developer.blender.org/D6227 has the sort of function that is needed, which could make it into Blender one
    # day.
    # There has also been talk of Vertex Groups possibly becoming more like generic Mesh Attributes in the future, which
    # would hopefully be able to use some, or all, of the Attributes API.

    # This method for getting Vertex Group weights scales poorly with lots of vertex groups assigned to each vertex.
    #
    # An alternative method is to use `VertexGroup.weight(vertex_index)`, which does not scale poorly. However, it
    # raises an Error when the vertex index is not in the Vertex Group, and relying on catching the Error is really
    # slow.
    for v in mesh.vertices:
        for g in v.groups:
            if g.group == vertex_group_index:
                yield g.weight
                break
        else:
            # No matching vertex group index found.
            yield 0.0


# Figures out what needs to be added to each affected Shape key, then iterates through all the affected Shape keys,
# getting the current coordinates, adding the corresponding amount to it and then setting that as the new coordinates.
# Gets and sets Shape Key coordinates manually with #foreach_get and #foreach_set.
def apply_new_reference_key(obj: Object,
                            new_ref: ShapeKey,
                            keys_relative_to_new_ref: set[ShapeKey],
                            keys_relative_to_old_ref: set[ShapeKey]):
    value = new_ref.value
    if value == 0.0:
        # 0.0 would have no effect, so set to 1.0.
        value = 1.0

    mesh = cast(Mesh, obj.data)
    num_verts = len(mesh.vertices)

    new_ref_key_vertex_group_name = new_ref.vertex_group
    if new_ref_key_vertex_group_name:
        new_ref_key_vertex_group = obj.vertex_groups.get(new_ref_key_vertex_group_name)
    else:
        new_ref_key_vertex_group = None

    new_ref_key_affected_by_own_application = new_ref in keys_relative_to_old_ref

    # Array of Vector type is flattened by #foreach_get into a sequence so the length needs to be multiplied by 3.
    flat_co_length = num_verts * 3

    # Store Shape Key coordinates for `new_ref`.
    # There is no need to initialise the elements to anything since they will all be overwritten.
    # The `ShapeKeyPoint` type's "co" property is a FloatProperty type, these are single precision floats.
    # It is extremely important for performance that the correct float type (np.single/np.float32) is used.
    # Using the wrong type could result in 3-5 times slower performance (depending on array length) due to Blender being
    # required to iterate through each element in the data first instead of immediately setting/getting all the data
    # directly.
    # See #foreach_getset in bpy_rna.cc of the Blender source for the implementation.
    new_ref_co_flat = np.empty(flat_co_length, dtype=np.single)
    new_ref_relative_key_co_flat = np.empty(flat_co_length, dtype=np.single)

    fast_mesh_shape_key_co_foreach_get(new_ref, new_ref_co_flat)
    fast_mesh_shape_key_co_foreach_get(new_ref.relative_key, new_ref_relative_key_co_flat)

    # This is movement of `new_ref` at a value of 1.0.
    difference_co_flat = np.subtract(new_ref_co_flat, new_ref_relative_key_co_flat)

    # Scale the difference based on the `.value` of `new_ref`.
    difference_co_flat_value_scaled = np.multiply(difference_co_flat, value)

    # These arrays can be reused over and over instead of allocating new arrays each time.
    temp_co_array = np.empty(flat_co_length, dtype=np.single)
    temp_co_array2 = np.empty(flat_co_length, dtype=np.single)

    if new_ref_key_vertex_group:
        # Scale the difference based on the Vertex Group.
        vertex_weight_generator = vertex_group_weight_generator(mesh, new_ref_key_vertex_group.index)
        vertex_group_weights = np.fromiter(vertex_weight_generator, difference_co_flat_value_scaled.dtype, num_verts)

        # Both arrays must be promoted to 2D views so that broadcasting can occur due to there being only a single
        # Vertex Group weight per vector.
        difference_co_flat_scaled = np.multiply(
            difference_co_flat_value_scaled.reshape(num_verts, 3),
            vertex_group_weights.reshape(num_verts, 1)
        ).ravel()
    else:
        difference_co_flat_scaled = difference_co_flat_value_scaled

    if new_ref_key_affected_by_own_application:
        # All Shape Keys in `keys_relative_to_new_ref` must also be in `keys_relative_to_old_ref`.
        # All the keys that will have only difference_co_flat_scaled added to them are those which are neither
        # `new_ref` nor relative to `new_ref`.
        keys_not_relative_to_new_ref_and_not_new_ref = (keys_relative_to_old_ref - keys_relative_to_new_ref) - {new_ref}

        # This for loop is where most of the execution will happen for typical setups of many Shape Keys directly
        # relative to the Reference Key.
        #
        # Add the difference between `new_ref` and `new_ref.relative_key` (scaled according to the `.value` and
        # `.vertex_group` of `new_ref`).
        # The coordinates for `new_ref.relative_key` has already been retrieved, so do it separately to save a
        # #foreach_get call.
        new_ref.relative_key.data.foreach_set(
            "co",
            np.add(new_ref_relative_key_co_flat, difference_co_flat_scaled, out=temp_co_array)
        )
        # And now the rest of the Shape Keys
        for key_block in keys_not_relative_to_new_ref_and_not_new_ref - {new_ref.relative_key}:
            fast_mesh_shape_key_co_foreach_get(key_block, temp_co_array)
            fast_mesh_shape_key_co_foreach_set(key_block,
                                               np.add(temp_co_array, difference_co_flat_scaled, out=temp_co_array))

        # Shorthand key:
        # NR = new_ref
        # NR.r = new_ref.relative_key
        # r(NR) = reversed(new_ref)
        # r(NR).r = reversed(new_ref).relative_key
        # NR.v = new_ref.value (`value`)
        # NR.vg = new_ref.vertex_group
        #
        # The difference between r(NR) and r(NR).r needs to be the negative of:
        #   (r(NR) - r(NR).r) * NR.vg = -((NR - NR.r) * NR.v * NR.vg)
        #                             = -(NR - NR.r) * NR.v * NR.vg
        # NR.vg cancels on both sides, leaving:
        #   r(NR) - r(NR).r = -(NR - NR.r) * NR.v
        # Rearranging for r(NR) gives:
        #   r(NR) = r(NR).r - (NR - NR.r) * NR.v
        # Note that (NR - NR.r) * NR.v = difference_co_flat_value_scaled so:
        #   r(NR) = r(NR).r - difference_co_flat_value_scaled
        # Note that r(NR).r = (NR.r + difference_co_flat_scaled) because that has been added to it.
        #   r(NR) = NR.r + difference_co_flat_scaled - difference_co_flat_value_scaled
        # Note that r(NR) = NR + X where X is what needs to be found to add to NR (and all Shape Keys relative to NR so
        # that their relative differences remain the same).
        #   NR + X = NR.r + difference_co_flat_scaled - difference_co_flat_value_scaled
        #   X = NR.r - NR + difference_co_flat_scaled - difference_co_flat_value_scaled
        #   X = -(NR - NR.r) + difference_co_flat_scaled - difference_co_flat_value_scaled
        # Fully expanding out would give:
        #   X = -(NR - NR.r) + (NR - NR.r) * NR.v * NR.vg - (NR - NR.r) * NR.v
        # And factorizing (NR - NR.r) gives:
        #   X = (NR - NR.r) * (-1 + 1 * NR.v * NR.vg - 1 * NR.v)
        #   X = (NR - NR.r) * (-1 + NR.v * NR.vg - NR.v)
        #   X = (NR - NR.r) * (-1 + NR.v * (NR.vg - 1))
        #   X = difference_co_flat * (-1 + NR.v * (NR.vg - 1))
        #
        # However, difference_co_flat, difference_co_flat_scaled and difference_co_flat_value_scaled have already been
        # calculated, which can be used to achieve the same result with fewer operations:
        #   X = -(NR - NR.r) + difference_co_flat_scaled - (NR - NR.r) * NR.v
        #   Which we can either factor to
        #       X = (NR - NR.r)(-1 - NR.v) + difference_co_flat_scaled
        #       X = difference_co_flat * (-1 - NR.v) + difference_co_flat_scaled
        #   Or, as NR - NR.r = difference_co_flat, calculate as
        #       X = -difference_co_flat + difference_co_flat_scaled - difference_co_flat_value_scaled
        #
        # The numpy functions take close to a negligible amount of the total function time, so the choice is not very
        # important, however, from my own benchmarks, `np.multiply(array1, scalar, out=output_array)` starts to scale
        # slightly better than `np.add(array1, array2, out=output_array)` once array1 gets to around 9000 elements or
        # more.
        # I guess this is due to the fact that the add operation needs to do 1 extra array access per element, and that
        # eventually surpasses the effect of the multiply operation being more expensive than the add operation.
        # In this case, the array length is 3*num_verts, meaning the multiplication option gets better at around 3000
        # Vertices, so the multiplication option is what is used here.
        if new_ref_key_vertex_group:
            np.multiply(difference_co_flat, -1 - new_ref.value, out=temp_co_array2)
            np.add(temp_co_array2, difference_co_flat_scaled, out=temp_co_array2)

            # The coordinates for `new_ref` have already been acquired, so `new_ref` can be done separately from the
            # others to save a #foreach_get call.
            fast_mesh_shape_key_co_foreach_set(new_ref, np.add(new_ref_co_flat, temp_co_array2, out=temp_co_array))

            # Now add to the rest of the keys
            for key_block in keys_relative_to_new_ref:
                fast_mesh_shape_key_co_foreach_get(key_block, temp_co_array)
                fast_mesh_shape_key_co_foreach_set(key_block, np.add(temp_co_array, temp_co_array2, out=temp_co_array))
        # But for there not being a vertex group, the NR.vg term can be eliminated as it becomes effectively 1.0:
        #   X = -(NR - NR.r) + (NR - NR.r) * NR.v - (NR - NR.r) * NR.v
        # Then the last part cancels out:
        #   X = -(NR - NR.r)
        # Giving X = -difference_co_flat.
        else:
            # Instead of adding the difference_co_flat_scaled to each Shape Key it will be subtracted from each Shape
            # Key instead.
            # The coordinates for `new_ref` have already been acquired, so it can be done separately to avoid a
            # #foreach_get call.
            # Note that:
            #   difference_co_flat = NR - NR.r
            # Rearrange for NR.r:
            #   NR.r = NR - difference_co_flat
            # Instead of doing `np.subtract(new_ref_co_flat, difference_co_flat)`, NR can simply be set to NR.r.
            fast_mesh_shape_key_co_foreach_set(new_ref, new_ref_relative_key_co_flat)
            # And the rest of the Shape Keys
            for key_block in keys_relative_to_new_ref:
                fast_mesh_shape_key_co_foreach_get(key_block, temp_co_array)
                fast_mesh_shape_key_co_foreach_set(key_block,
                                                   np.subtract(temp_co_array, difference_co_flat, out=temp_co_array))
    else:
        # `new_ref` is not relative to the Reference Key so the Shape Keys `new_ref` is relative to will remain
        # unchanged.
        # Shape Keys relative to the Reference Key and Shape Keys recursively relative to `new_ref` will be mutually
        # exclusive.
        # Typical user setups have all the Shape Keys immediately relative to the Reference Key, so this will not be
        # used much.

        # Add the difference between `new_ref` and `new_ref.relative_key` (scaled according to the `.value` and
        # `.vertex_group` of `new_ref`).
        for key_block in keys_relative_to_old_ref:
            fast_mesh_shape_key_co_foreach_get(key_block, temp_co_array)
            fast_mesh_shape_key_co_foreach_set(key_block,
                                               np.add(temp_co_array, difference_co_flat_scaled, out=temp_co_array))

        # The difference between the reversed Shape Key and its Relative Key needs to equal the negative of the
        # difference between `new_ref` and `new_ref`.relative_key multiplied.
        # `new_ref.vertex_group` should be present on both.
        #   (r(NR) - r(NR).r) * NR.vg = -((NR - NR.r) * NR.v * NR.vg)
        #                             = -(NR - NR.r) * NR.v * NR.vg
        # NR.vg cancels on both sides, leaving:
        #   r(NR) - r(NR).r = -(NR - NR.r) * NR.v
        # r(NR).r is unchanged, meaning r(NR).r = NR.r
        #   r(NR) - NR.r = -(NR - NR.r) * NR.v
        # r(NR) = X + NR where X is what needs to be found to add
        #   X + NR - NR.r = -(NR - NR.r) * NR.v
        # Rearrange for X:
        #   X = -(NR - NR.r) - (NR - NR.r) * NR.v
        #
        # (NR - NR.r) can be factorised:
        #   X = (NR - NR.r)(-1 - NR.v)
        # Note that (NR - NR.r) is difference_co_flat, giving:
        #   X = difference_co_flat * (-1 - NR.v)
        #
        # Alternatively, instead of factorising, note that (NR - NR.r) * NR.v is difference_co_flat_value_scaled:
        #   X = -(NR - NR.r) - difference_co_flat_value_scaled
        # Note that (NR - NR.r) is difference_co_flat, giving
        #   X = -difference_co_flat - difference_co_flat_value_scaled
        # Or
        #   X = -(difference_co_flat + difference_co_flat_value_scaled)
        #
        # Since NR.vg is not present, it does not matter whether `new_ref` has a Vertex Group or not.
        #
        # As with before, the multiplication option is used due to it scaling slightly better with a larger number of
        # Vertices:
        # X = difference_co_flat * (-1 - NR.v)
        np.multiply(difference_co_flat, -1 - new_ref.value, out=temp_co_array2)

        # The coordinates for `new_ref` have already been acquired, so it can be done separately from the others to save
        # a #foreach_get call.
        fast_mesh_shape_key_co_foreach_set(new_ref, np.add(new_ref_co_flat, temp_co_array2, out=temp_co_array))
        # And now the rest of the Shape Keys.
        for key_block in keys_relative_to_new_ref:
            fast_mesh_shape_key_co_foreach_get(key_block, temp_co_array)
            fast_mesh_shape_key_co_foreach_set(key_block, np.add(temp_co_array, temp_co_array2, out=temp_co_array))

    # Update Mesh Vertices to avoid reference Shape Key and Mesh Vertices being desynced until Edit mode has been
    # entered and exited, which can cause odd behaviour when creating Shape Keys with `from_mix=False`, when removing
    # all Shape Keys or exporting as a format that supports exporting Shape Keys.
    fast_mesh_shape_key_co_foreach_get(mesh.shape_keys.reference_key, temp_co_array)
    # The "position" Attribute giving faster access to a Mesh's Vertex positions was added in Blender 3.5.
    if bpy.app.version >= (3, 5):
        position_attribute = mesh.attributes.get("position")
        if (position_attribute
                and position_attribute.data_type == 'FLOAT_VECTOR'
                and position_attribute.domain == 'POINT'):
            position_attribute.data.foreach_set("vector", temp_co_array)
    else:
        mesh.vertices.foreach_set("co", temp_co_array)