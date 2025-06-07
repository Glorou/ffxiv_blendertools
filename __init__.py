bl_info = {
    "name": "Final Fantasy 14: A File Handler Reborn",
    "author" : "Karou",
    "description": "File exporter tailored for FFXIV",
    "blender": (4, 4, 0),
    "version" : (0, 0, 1),
    "category": "Import-Export"
}


import bpy 
import os 
from .functions import ModifierToShapeKey, ShapeKeyToReferenceKey, ModifierList
from bpy.props import StringProperty, BoolProperty, EnumProperty 
from bpy_extras.io_utils import ImportHelper, ExportHelper 
from bpy.types import Operator 



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
        with context.temp_override():
            if self.apply_modifiers == 'YES_PRESERVE' and len(context.scene.objects) > 0:
                shapekey_fixes(self, context)
            
            
        
        
        #filename, extension = os.path.splitext(self.filepath)
            match self.filename_ext:
                case ".fbx":
                    bpy.ops.export_scene.fbx(filepath = self.filepath,
                                            primary_bone_axis='X',
                                            secondary_bone_axis='Y',
                                            use_active_collection = self.use_active_collection,
                                            use_visible = self.use_visible,
                                            use_selection = self.use_visible,
                                            use_mesh_modifiers = True if self.apply_modifiers == 'YES_APPLY' else False,
                                            add_leaf_bones = False,
                                            )
                case ".glb" | ".gltf": 
                    bpy.ops.export_scene.gltf(filepath = self.filepath,
                                            export_format= 'GLB' if self.filename_ext == '.glb' else 'GLTF_SEPARATE',
                                            export_tangents=True,
                                            use_active_collection = self.use_active_collection,
                                            use_visible = self.use_visible,
                                            use_selection = self.use_visible,
                                            export_try_sparse_sk = False,
                                            export_apply = True if self.apply_modifiers == 'YES_APPLY' else False,
                                            )
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
 
#need to add triangulation but i cba
# https://blender.stackexchange.com/questions/322905/apply-all-shape-keys-to-selected-objects-except-certain-shape-keys
# need to add apply shapekey to basis
def shapekey_fixes(operator, context):
    
    was_in_edit = (bpy.context.mode == 'EDIT_MESH')
    if was_in_edit:
        active_edit = bpy.context.active_object
        
    bpy.ops.object.mode_set(mode = 'OBJECT')
    
    for o in (o for o in context.scene.objects if o.type == 'MESH' and o.data.shape_keys):
        shapes_to_delete, shapes_to_preserve = [], []
        for shape in o.data.shape_keys.key_blocks:(
            shapes_to_delete if 'shpx_' not in shape.name.lower() and 'shp_' not in shape.name.lower()
        else shapes_to_preserve
        ).append(shape)
        
        for shape in (shape for shape in shapes_to_delete if shape is not o.data.shape_keys.reference_key):
            context.view_layer.objects.active = o   
            o.active_shape_key_index = o.data.shape_keys.key_blocks.find(shape.name)
            ShapeKeyToReferenceKey.execute(operator, context)
            o.shape_key_remove(shape)
        
        
        
        for shape in shapes_to_preserve:
            context.view_layer.objects.active = o 
            o.active_shape_key_index = o.data.shape_keys.key_blocks.find(shape.name)
            ModifierToShapeKey.run(ModifierToShapeKey, context)
                
    if was_in_edit:
        bpy.context.active_object = active_edit
        bpy.ops.object.mode_set(mode = 'EDIT')
        
    return
    

classes = (
    ImportFile,
    ExportFile,
    ShapeKeyToReferenceKey,
    ModifierList,
    ModifierToShapeKey
    #IO_FH_fbx,
)

def menu_func_import(self, context):
    self.layout.operator(ImportFile.bl_idname, text="Import FFXIV Model (.fbx/.glb/.gltf)")
    

def menu_func_export(self, context):
    self.layout.operator(ExportFile.bl_idname, text="Export FFXIV Model (.fbx/.glb/.gltf)")

def register(): 
    
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)
    bpy.types.TOPBAR_MT_file_export.append(menu_func_export)

def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    bpy.types.TOPBAR_MT_file_export.remove(menu_func_export)
    for cls in classes:
        bpy.utils.unregister_class(cls)

if __name__ == "__main__":
    register() 
        
    # test call 
    #bpy.ops.test.open_filebrowser('INVOKE_DEFAULT')