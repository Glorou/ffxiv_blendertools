import bpy, blf
import gpu
from bpy.app.handlers import persistent
from gpu_extras.batch import batch_for_shader
import mathutils
import re



shader = gpu.shader.from_builtin('SMOOTH_COLOR')
shader_box = gpu.shader.from_builtin('UNIFORM_COLOR')

owner = object()





def msgbus_callback(*args):
    calc(args[0])

def subscribe():

    global owner
    subscribe_to = (bpy.types.Object, "name")

    bpy.msgbus.subscribe_rna(
        key=subscribe_to,
        owner=owner,
        args=(True, None, None),
        notify=msgbus_callback,
        options={"PERSISTENT",}
    )
    if load_handler not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(load_handler)
    

def unsubscribe():
    global owner
    # Clear all subscribers by this owner
    if owner is not None:
        bpy.msgbus.clear_by_owner(owner)

    # Unregister the persistent handler.
    if load_handler in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(load_handler)


@persistent
def load_handler(dummy):
    subscribe()

class BlfText:
    __slots__ = 'color', 'x', 'y', 'text', 'size', 'font_id'

    # x : Left
    # y : Bottom
    def __init__(self, color, x=0, y=0, text="", size=12, font_id=0):
        self.color = color
        self.x = x
        self.y = y
        self.text = text
        self.size = size
        self.font_id = font_id

    def calc_center_pos_x(self):
        blf.size(self.font_id, self.size)
        return round(self.x + blf.dimensions(self.font_id, self.text)[0] / 2)

    def calc_center_pos_y(self):
        blf.size(self.font_id, self.size)
        return round(self.y + blf.dimensions(self.font_id, self.text)[1] / 2)
    
    def draw(self):
        font_id = self.font_id
        blf.color(font_id, *self.color)
        blf.size(font_id, self.size)
        blf.position(font_id, self.x, self.y, 0)
        blf.draw(font_id, self.text)


def draw_element(pos_left=0, pos_bottom=0, scale=1.0, bar_size_x=250, bar_size_y=20):

    counter = calc()

    border = round(10 * scale)
    inner = round(8 * scale)
    font_size = round(14 * scale)
    font_id = 0
    font_color = (0.7, 0.7, 0.7, 1.0)
    blf.size(font_id, font_size)

    bar_B = pos_bottom + border
    bar_T = round(bar_B + bar_size_y * scale)
    text_y = bar_T + inner
    text_x = pos_left + border


    
    string = ""
    warning = ""
    if bpy.context.active_object != None and bpy.context.active_object.type == 'MESH':
        matching = re.search(r"(?P<major>\d{1,2})\.(?P<minor>\d{1,5})", bpy.context.active_object.name)

        if matching != None:
            major = int(matching.groupdict()['major'])
            string = "The active submesh {major} is using {val} verts towards the limit\n".format(val=counter[major], major=major)


    for key in counter.keys():
        if counter[key] > 65535:
            warning +="Submesh {major} has {val} too many verts\n".format(val=counter[key]-65535, major=key)


    active_text = BlfText(font_color, text_x, text_y, string, font_size, font_id)

    


    warning_text = BlfText((1, 0, 0, 1), text_x, text_y - (font_size * 1.5), warning, font_size, font_id)


    shader_box.uniform_float("color", (0.2, 0.2, 0.2, 0.0))

    active_text.draw()
    if warning != "":
        warning_text.draw()

def draw_widget():


    draw_element(
        pos_left = 50,
        pos_bottom = 50,
        scale = 1.0 # or use blender UI scale
    )





def calc(override=False):
    if not hasattr(calc, "counter"):
        calc.counter = dict()
    if not hasattr(calc, "objs_seen"):
        calc.objs_seen = 0

    current_objs = 0
    for o in (o for o in bpy.context.scene.objects if o.type == 'MESH' and o.visible_get()):
        current_objs += 1
    
    if(current_objs == calc.objs_seen and not override):
        return calc.counter
    else:
        calc.objs_seen = 0
        calc.counter = dict()

    for o in (o for o in bpy.context.scene.objects if o.type == 'MESH' and o.visible_get()):
        calc.objs_seen += 1
        matching = re.search(r"(?P<major>\d{1,2})\.(?P<minor>\d{1,5})", o.name)
        if matching != None:
            #check keys
            major = int(matching.groupdict()['major'])
            minor = int(matching.groupdict()['minor'])
            if major not in calc.counter.keys():
                calc.counter[major] = 0
            if(o.data.shape_keys != None):
                shape_verts = 0  
                for shp in (shp for shp in o.data.shape_keys.key_blocks if shp != o.data.shape_keys.reference_key and 'shp' in shp.name.lower()):
                    for key in shp.points.items():
                        if shp.points[key[0]].co != o.data.shape_keys.reference_key.points[key[0]].co: 
                            shape_verts = shape_verts + 1 
                                
                calc.counter[major] += shape_verts       
            calc.counter[major] += len(o.data.vertices.items())
    return calc.counter

# Add the draw handler
