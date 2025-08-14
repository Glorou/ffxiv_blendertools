bl_info = {
    "name": "Final Fantasy 14: A File Handler Reborn",
    "author" : "Karou",
    "description": "File exporter tailored for FFXIV",
    "blender": (4, 2, 0),
    "version" : (0, 3, 0),
    "category": "Import-Export"
}


import bpy 
import os 
import code
import bmesh
import re
import mathutils
from .functions import apply_modifiers_with_shape_keys, ShapeKeyToReferenceKey
from .widget import BlfText, draw_widget, subscribe, unsubscribe
from bpy.props import StringProperty, BoolProperty, EnumProperty 
from bpy_extras.io_utils import ImportHelper, ExportHelper 
from bpy.types import Operator 



class ShapekeyCounter(Operator):
    bl_idname = "ffxiv_tools.shape_count"
    bl_label = "FFXIV Shapekeys"

    enabled : BoolProperty(
        name="Enable or Disable",
        description="Turn the shapekey counter on or off",
        default=False,
    )

    def draw(self, context):
        layout = self.layout
        overlay = context.space_data.overlay
        layout.prop(overlay, "enabled", text="FF14 Shapekey Counter", toggle=True)

    def execute(self, context):
        global text_handle
        if not self.enabled:
            text_handle = bpy.types.SpaceView3D.draw_handler_add(draw_widget, (), 'WINDOW', 'POST_PIXEL')
            subscribe()
            self.enabled = not self.enabled
        else:
            bpy.types.SpaceView3D.draw_handler_remove(text_handle, 'WINDOW')
            unsubscribe()
            self.enabled = not self.enabled
        return {'FINISHED'}
    

    


class ImportFile(Operator, ImportHelper):

    bl_idname = "import_scene.tool"
    bl_label = "Import model"
    #bl_options = {'UNDO', 'PRESET'}
    
    filter_glob: StringProperty(
        default='*.glb;*.gltf;*.fbx',
        options={'HIDDEN'} 
    )
        
    some_boolean: BoolProperty( 
        name='Do a thing',
        description='Do a thing with the file you\'ve selected',
        default=True,
    ) 
        
    def execute(self, context):
        """Do something with the selected file(s).""" 
        
        filename, extension = os.path.splitext(self.filepath)
        
        match extension.lower():
            case ".fbx":
                bpy.ops.import_scene.fbx(filepath = self.filepath, primary_bone_axis='X', secondary_bone_axis='Y')
            case ".glb" | ".gltf":
                bpy.ops.import_scene.gltf(filepath = self.filepath)
            
        return {'FINISHED'} 
        

class ExportFile(Operator, ExportHelper):

    bl_idname = "export_scene.tool"
    bl_label = "Export model"
    bl_description = "Export"
    #bl_options = {'UNDO', 'PRESET'}
    
    def file_callback(self, context):
        return (
            ('.fbx', '.fbx file', "fbx for exporting to Textools"),
            ('.gltf', '.gltf file', "gltf for exporting to Penumbra"),
            ('.glb', '.glb file', "glb for exporting to Penumbra"),
        )
    
    filter_glob: StringProperty(
        default='*.glb;*.gltf;*.fbx',
        options={'HIDDEN'} 
    )
    
    filename_ext: EnumProperty(
        items=file_callback,
        name='File type',
        description='Pick a file type to export with',
        default=None)
    
    
    use_selection: BoolProperty(
        name="Selected Objects",
        description="Export selected and visible objects only",
        default=False,
    )
    use_visible: BoolProperty(
        name='Visible Objects',
        description='Export visible objects only',
        default=True
    )
    use_active_collection: BoolProperty(
        name="Active Collection",
        description="Export only objects from the active collection (and its children)",
        default=False,
    )
    gltf_props: BoolProperty(
        name="Custom Properties",
        description="Include Custom Properties to author attributes",
        default=True,
    )
    apply_modifiers: EnumProperty(
        name="Shapekey behaviour",
        items=(('YES_PRESERVE', "Yes, keep Shapekeys", "Apply modifiers while preserving shapekeys"),
               ('YES_APPLY', "Yes, apply Shapekeys", "Apply modifiers and shapekeys"),
               ('NO', "No, don't apply modifiers", "Exports the mesh without any modifiers"),
               ),
        default='YES_PRESERVE'
    )
     
        
    
    some_boolean: BoolProperty( 
        name='Do a thing',
        description='Do a thing with the file you\'ve selected',
        default=True,
    ) 
    
    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False  # No animation.

        # Are we inside the File browser
        is_file_browser = context.space_data.type == 'FILE_BROWSER'

        export_main(layout, self, is_file_browser)
        export_panel_include(layout, self, is_file_browser)        
        export_panel_gltf(layout, self)

        
    def execute(self, context):
        """Do something with the selected file(s)."""

        active = bpy.context.active_object
        selected = bpy.context.selected_objects

        #print(self.apply_modifiers)     
        if self.use_visible:
            objects = context.visible_objects
        elif self.use_selection:
            objects = context.selected_objects
        else:
            objects = context.scene.objects

        currentview = context.object.mode
        dupes = []
        
        tempcontext = bpy.context.copy()
        bpy.ops.object.mode_set(mode='OBJECT')
        for o in(o for o in objects if o.type == 'MESH'):
            with context.temp_override(context=tempcontext):
                
                if context.selected_objects != []:
                    bpy.ops.object.select_all(action="DESELECT")
                context.view_layer.objects.active = o
                o.select_set(state=True)
                bpy.ops.object.duplicate()
                dupe = context.active_object
                dupe.name = "Export " + o.name
                dupes.append(dupe)
          #      if not mod.object.visible_get():
        
        armatures = []
        for o in dupes:
            for mod in (mod for mod in o.modifiers if mod.type == 'ARMATURE'):
                if mod.show_viewport and not any(x == mod.object for x in armatures):
                    armatures.append(mod.object)
        #halts if a mesh doesnt have an armature modifier
        if None in armatures:
            self.report({'ERROR'}, "One or more meshes with an amature modifier doesn't have an associated armature, please add the armature or remove the modifier.")
            for o in dupes:
                bpy.data.objects.remove(o)
            return {'CANCELLED'}

        armatures_export = []
        changed = None


        if(len(armatures) > 0):
            for arm in armatures:
                with context.temp_override(context=tempcontext):
                    
                    
                    arm_hidden = arm.hide_get()
                    if arm_hidden:
                        arm.hide_set(False)

                    
                    #if this is true then the collection should not be in the view layer
                    if arm.hide_get() == arm.visible_get():
                        coll = arm.users_collection[0]
                        for lay in (lay for lay in context.scene.view_layers[0].layer_collection.children if lay.collection.user_of_id(arm.users_collection[0]) > 0):
                            index = lay.children.find(arm.users_collection[0].name)
                            if index != -1:
                                changed = lay.children[index]
                                lay.children[index].exclude = False
                            else:
                                for layer in (layer for layer in lay.children if layer.collection.user_of_id(arm.users_collection[0]) > 0):
                                    index = lay.children.find(arm.users_collection[0].name)
                                    if index != -1:
                                        changed = lay.children[index]
                                        lay.children[index].exclude = False



                
                if context.selected_objects != []:
                    bpy.ops.object.select_all(action="DESELECT")
                #code.interact(local=locals())
                context.view_layer.objects.active = arm
                arm.select_set(state=True)
                bpy.ops.object.duplicate()
                dupe = context.active_object
                dupe.name = "Export " + arm.name
                dupes.append(dupe)
                armatures_export.append(dupe)

                if arm_hidden:
                    arm.hide_set(True)



        
        for o in (o for o in dupes if o.type == 'MESH'):
            for mod in (mod for mod in o.modifiers if mod.type == 'ARMATURE'):
                if mod.show_viewport and not any(x == mod.object for x in armatures_export):
                    for arm in armatures_export:                      
                        if arm.name.endswith(mod.object.name):                        
                            mod.object = arm
        



        override = context.copy()
        override["selected_objects"] = dupes
        override["active_object"] = dupes[0]
        with bpy.context.temp_override(**override):

            bpy.ops.object.mode_set(mode = 'OBJECT')
            #we need to duplicate every mesh so when we do all of our modifications we dont touch the originals



            if self.apply_modifiers == 'YES_PRESERVE' and len(context.scene.objects) > 0:
                shapekey_fixes(self, context, dupes)



            for ob in context.selected_objects:
                ob.select_set(True)
                
            
        

        #filename, extension = os.path.splitext(self.filepath)
            match self.filename_ext:
                case ".fbx":
                    bpy.ops.export_scene.fbx(filepath = self.filepath,
                                            primary_bone_axis='X',
                                            secondary_bone_axis='Y',
                                            #use_active_collection = self.use_active_collection,
                                            #use_visible = self.use_visible,
                                            use_selection = True,
                                            use_mesh_modifiers = False if self.apply_modifiers == 'NO' else True,
                                            use_custom_props = True,
                                            add_leaf_bones = False,
                                            bake_anim = False,
                                            )
                case ".glb" | ".gltf": 
                    #experemental gltf fix
                    #parent_meshes(self, context, dupes)
                    bpy.ops.export_scene.gltf(filepath = self.filepath,
                                            export_format= 'GLB' if self.filename_ext == '.glb' else 'GLTF_SEPARATE',
                                            export_tangents=True,
                                            use_selection = True,
                                            export_try_sparse_sk = False,
                                            export_apply = False if self.apply_modifiers == 'NO' else True,
                                            export_animations = False,
                                            )
            #code.interact(local=locals())
        
        for o in dupes:
            bpy.data.objects.remove(o)
        bpy.context.view_layer.objects.active = active
        bpy.ops.object.mode_set(mode=currentview)
        if changed != None:
            changed.exclude = True
        return {'FINISHED'} 

def export_main(layout, operator, is_file_browser):
    row = layout.row(align=True)
    row.prop(operator, "filename_ext")
    layout.prop(operator, "apply_modifiers")


def export_panel_include(layout, operator, is_file_browser):
    header, body = layout.panel("ffxiv_export_include", default_closed=False)
    header.label(text="Include")
    if body:
        sublayout = body.column(heading="Limit to")
        if is_file_browser:
            sublayout.prop(operator, "use_selection")
            sublayout.prop(operator, "use_visible")
            sublayout.prop(operator, "use_active_collection")



def export_panel_gltf(layout, operator):
    header, body = layout.panel("ffxiv_export_gltf", default_closed=True)
    header.use_property_split = False
    header.label(text="glTF options")
    if body:
        body.enabled = (operator.filename_ext == ('.glb' or '.gltf'))
        body.prop(operator, "gltf_props")
 




        
def parent_meshes(operator, context, dupes):

    for mesh in (mesh for mesh in dupes if mesh.type == 'MESH'):
        if mesh.modifiers[0].type == 'ARMATURE':
            if context.selected_objects != []:
                bpy.ops.object.select_all(action="DESELECT")
                #code.interact(local=locals())
            context.view_layer.objects.active = mesh.modifiers[0].object
            mesh.select_set(state=True)
            bpy.ops.object.parent_set(type='ARMATURE', keep_transform=True)
            mesh.parent = mesh.modifiers[0].object

    return







#need to add triangulation but i cba
# https://blender.stackexchange.com/questions/322905/apply-all-shape-keys-to-selected-objects-except-certain-shape-keys
# need to add apply shapekey to basis
def shapekey_fixes(operator, context, dupes):
    

    for o in filter(lambda obj: obj.type == 'MESH' and obj.data.shape_keys, dupes):
        if not o.visible_get():
            o.hide_set(False)
        context.view_layer.objects.active = o


        #skip object if we cant set it for some reason
        #if not o.visible_get():
         #   continue
        for shape in (shape for shape in o.data.shape_keys.key_blocks if (('shpx_' not in shape.name.lower() and 'shp_' not in shape.name.lower()) and (shape.value == 0.0 or shape.mute) and shape.name != o.data.shape_keys.reference_key.name)):
            o.shape_key_remove(shape)

        shapes_to_delete, shapes_to_preserve = [], []
        for shape in o.data.shape_keys.key_blocks:(
            shapes_to_delete if 'shpx_' not in shape.name.lower() and 'shp_' not in shape.name.lower()
        else shapes_to_preserve
        ).append(shape)
        #print("!!!!!!!!! Shapekey_fix pre op")
        #print(o)
        #print(o.data.shape_keys.key_blocks.values())
        #print(context.blend_data.shape_keys['Butt Shapekeys'].key_blocks.find('shpx_wa_tre'))
        #print(o.data.shape_keys.reference_key)
        #code.interact(local=locals())
        for shape in (shape for shape in shapes_to_delete if shape.name != o.data.shape_keys.reference_key.name and (shape.value > 0.0 or not shape.mute)):   
            o.active_shape_key_index = o.data.shape_keys.key_blocks.find(shape.name)
            print(o)
            with context.temp_override(object=o):
                ShapeKeyToReferenceKey.execute(operator, context)
            o.shape_key_remove(shape)
        



        for shape in shapes_to_preserve:
            context.view_layer.objects.active = o 
            o.active_shape_key_index = o.data.shape_keys.key_blocks.find(shape.name)
            
            
            selected_modifiers = [o.name for o in o.modifiers if o.type != 'ARMATURE']
            #print(dir(selected_modifiers))
            #print("%d" % o.data.shape_keys.key_blocks.find(shape.name))
            apply_modifiers_with_shape_keys(context, selected_modifiers)
        #code.interact(local=locals())    

        
    return
    
text_handle = None

classes = (
    ImportFile,
    ExportFile,
    ShapeKeyToReferenceKey,
    ShapekeyCounter,
    #IO_FH_fbx,
)

def menu_func_import(self, context):
    self.layout.operator(ImportFile.bl_idname, text="Import FFXIV Model (.fbx/.glb/.gltf)")
    

def menu_func_export(self, context):
    self.layout.operator(ExportFile.bl_idname, text="Export FFXIV Model (.fbx/.glb/.gltf)")

def menu_func_shapes(self, context):
    self.layout.operator(ShapekeyCounter.bl_idname)


def register(): 

    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)
    bpy.types.TOPBAR_MT_file_export.append(menu_func_export)
    bpy.types.VIEW3D_PT_overlay.append(menu_func_shapes)


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    bpy.types.TOPBAR_MT_file_export.remove(menu_func_export)
    bpy.types.VIEW3D_PT_overlay.remove(menu_func_shapes)
    for cls in classes:
        bpy.utils.unregister_class(cls)

if __name__ == "__main__":
    register() 
        
    # test call 
    #bpy.ops.test.open_filebrowser('INVOKE_DEFAULT')


        #    print("!!!!!!!!! Shapekey_fix")
        #print(o)
        #if o.data.shape_keys:
        #    print(o.data.shape_keys.key_blocks.values())
        #print(context.blend_data.shape_keys['Butt Shapekeys'].key_blocks.find('shpx_wa_tre'))
        