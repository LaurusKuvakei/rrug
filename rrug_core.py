bl_info = {
    "name": "RRUG Core",
    "author": "Laurus Kuvakei",
    "version": (1, 1, 2),
    "blender": (4, 2, 0),
    "location": "3D Viewport > Sidebar (N Panel) > Animation",
    "description": "Reactive Rig UI Generator (Core Engine).",
    "category": "Rigging",
    "license": "GPL-2.0-or-later",
}

# RRUG UI - Reactive Rig UI Generator.
# Copyright (C) 2025-2026 Laurus Kuvakei 

# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY and FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, see
# <https://www.gnu.org/licenses/>.

import bpy
import re
import traceback
import mathutils
import functools
from bpy.app.handlers import persistent
# ==============================================================================
# SECTION 1: CONFIGURATION & CONSTANTS
# ==============================================================================
RRUG_TRIGGER_KEY = "RRUG_UI"
MAX_UI_NESTING = 8
FIXED_FPS = 4.0

# 0: RRUG UI, 1: Animation, 2: View, 3: Tool, 4: Item, 5: Constraints
UI_LOCATION_INDEX = 1 
_UI_LOCS = [
    ('VIEW_3D',   'UI',     'RRUG UI',   ''),            # 0: RRUG UI
    ('VIEW_3D',   'UI',     'Animation', ''),            # 1: Animation
    ('VIEW_3D',   'UI',     'View',      ''),            # 2: View
    ('VIEW_3D',   'UI',     'Tool',      ''),            # 3: Tool
    ('VIEW_3D',   'UI',     'Item',      ''),            # 4: Item
    ('PROPERTIES', 'WINDOW', '',          'constraint'), # 5: Constraints
]
# Extract active configuration
UI_SPACE_TYPE, UI_REGION_TYPE, UI_CATEGORY, UI_CONTEXT = _UI_LOCS[UI_LOCATION_INDEX]

def get_current_ui_cfg():
    return _UI_LOCS[UI_LOCATION_INDEX]

_DYNAMIC_PARAM = "__DYNAMIC__"
CTX_VIS = "VIS"
CTX_PROP = "PROP"
CTX_SNAP = "SNAP"
CTX_INTERNAL = "INTERNAL"

FLAG_CONFIG = {
    "INLINE":    {"params": None, "validator": None},
    "LINK":      {"params": None, "validator": None},
    "ICON":      {"params": _DYNAMIC_PARAM, "validator": lambda x: x in _get_valid_blender_icons()},
    "JOIN":      {"params": None, "validator": None},
    "HIDE":      {"params": None, "validator": None},
    "TO":        {"params": None, "validator": None},
    "SKIP":      {"params": None, "validator": None},
    "FILTER":    {"params": {"IFHIDDEN"}, "validator": None},
    "DISPLAYS":  {"params": None, "validator": None},
    "SETTINGS":  {"params": None, "validator": None},
    "SNAPS":     {"params": None, "validator": None},
    "INTERNALS": {"params": None, "validator": None},
    "BOARD":     {"params": None, "validator": None},
}
_EXPLICIT_NAME_PATTERN = re.compile(r'\{([^}]+)\}(?:\[[^\]]+\])?')
_PROP_ORDER_PATTERN = re.compile(r'^\{\d+\}\s*')
_FLAG_KEYS = sorted(FLAG_CONFIG.keys(), key=len, reverse=True)
_FLAG_TUPLE_PATTERN = re.compile(r'\((%s)\)(?:\s*\[([^\]]+)\])?' % "|".join(map(re.escape, _FLAG_KEYS)))
_TIPS = {
    "SNAP":             ("Snap Hierarchy", "Snap source bones to target bones based on hierarchy"),
    "SEL_REPLACE":      ("Replace", "Select bones in this collection (Replace Selection)"),
    "SEL_ADD":          ("Add", "Add bones in this collection to Selection"),
    "VIS":              ("Vis", "Toggle visibility for this collection"),
    "SOLO":             ("Solo", "Isolate this collection (Solo Mode)"),
    "SYM":              ("Symmetrize", "Copy custom properties to the linked partner"),
    "SYM_ALL":          ("Symmetrize All", "Symmetrize all linked property pairs in the rig"),
    "RESET":            ("Reset", "Reset custom properties to defaults"),
    "DUMMY":            ("", "Global Symmetrization active"),
    "EXPAND_ALL":       ("Expand/Collapse", "Expand or Collapse all collections in this panel"),
    "RST_SEL_LOC":      ("Loc", "Reset Location (Selection)"),
    "RST_SEL_ROT":      ("Rot", "Reset Rotation (Selection)"),
    "RST_SEL_SCALE":    ("Scl", "Reset Scale (Selection)"),
    "RST_SEL_ALL":      ("All", "Reset All Transforms (Selection)"),
    "RST_RIG_LOC":      ("Loc", "Reset Location (Whole Rig)"),
    "RST_RIG_ROT":      ("Rot", "Reset Rotation (Whole Rig)"),
    "RST_RIG_SCALE":    ("Scl", "Reset Scale (Whole Rig)"),
    "RST_RIG_ALL":      ("All", "Reset All Transforms (Whole Rig)"),
    "SNAP_CURS_TO_SEL": ("Cur->Sel", "Snap 3D Cursor to the Active Bone"),
    "SNAP_SEL_TO_CURS_LOC": ("Loc", "Snap Selection Location to Cursor"),
    "SNAP_SEL_TO_CURS_ROT": ("Rot", "Snap Selection Rotation to Cursor"),
    "SNAP_SEL_TO_CURS_ALL": ("All", "Snap Selection Location & Rotation to Cursor"),
    "ZERO_AXIS":        ("Zero Axis", "Reset this specific cursor axis to 0.0"),
    "VIS_SEARCH":       ("Search Bone", "Search for bones by name in the rig visibility groups"),
    "VIS_SELECT":       ("Select Bone", "Select the found bone and update the active bone"),
    "VIS_ISOLATE":      ("Isolate Search", "Toggle UI Filtering: Only display collections containing the found bone"),
    "VIS_GET_ACTIVE": ("Get Active", "Copy the active bone name from the viewport into the search field"),
    "VIS_SHOW_ALL":   ("Show All", "Unhide all visibility collections"),
    "VIS_UNSOLO_ALL": ("Unsolo All", "Disable solo mode for all collections"),
}

_rrug_ui_data_cache = {}
_entrance_gatekeeper_cache = {}
_DEFAULT_RRUG_UI_DATA = {
    "node_map": {}, "vis_display": [], "snap_groups": {}, "snap_layout": [],
    "props_others": [], "has_links": False, "found_settings": False,
    "root_collection_names": []
}

# ==============================================================================
# SECTION 2: UTILITIES & MATH
# ==============================================================================

@functools.lru_cache(maxsize=1)
def _get_valid_blender_icons():
    try:
        items = bpy.types.UILayout.bl_rna.functions["prop"].parameters["icon"].enum_items
        return set(items.keys())
    except (AttributeError, KeyError, TypeError):
        return set()

def purge_rrug_cache():
    _rrug_ui_data_cache.clear()
    _entrance_gatekeeper_cache.clear()
    _parse_collection_name.cache_clear()
    _get_valid_blender_icons.cache_clear()
    print("RRUG UI: Cache Flushed")

@persistent
def rrug_ui_load_handler(dummy):
    purge_rrug_cache()

def is_in_pose_mode(context):
    return context.mode == 'POSE'

def get_3d_view_area(context):
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D': return window, area
    return None, None

def limited_redraw():
    try: wm = bpy.context.window_manager
    except AttributeError: return
    if not wm: return
    target_areas = {'VIEW_3D', UI_SPACE_TYPE}
    for window in wm.windows:
        if not window.screen: continue
        for area in window.screen.areas:
            if area.type in target_areas: area.tag_redraw()

def safe_get_collection(armature, collection_name):
    if not armature or not collection_name: return None
    return armature.collections_all.get(collection_name)

if bpy.app.version >= (5, 0, 0):
    def select_bone(arm_obj, data_bone):
        if pb := arm_obj.pose.bones.get(data_bone.name): pb.select = True
else:
    def select_bone(arm_obj, data_bone):
        data_bone.select = True

def get_composed_matrix(source_matrix, target_matrix, snap_mode):
    loc_s, rot_s, scl_s = source_matrix.decompose()
    loc_t, rot_t, scl_t = target_matrix.decompose()
    final_loc = loc_t if snap_mode[0] else loc_s
    final_rot = rot_t if snap_mode[1] else rot_s
    final_scl = scl_t if snap_mode[2] else scl_s
    return mathutils.Matrix.LocRotScale(final_loc, final_rot, final_scl)

def apply_keyframes(pose_bone, snap_mode):
    snap_loc, snap_rot, snap_scale = snap_mode
    if snap_loc: pose_bone.keyframe_insert(data_path="location")
    if snap_rot:
        mode = pose_bone.rotation_mode
        path = "rotation_quaternion" if mode == 'QUATERNION' else "rotation_axis_angle" if mode == 'AXIS_ANGLE' else "rotation_euler"
        pose_bone.keyframe_insert(data_path=path)
    if snap_scale: pose_bone.keyframe_insert(data_path="scale")

def restore_mirror_channels(pose_bone, original_data, snap_mode):
    snap_loc, snap_rot, snap_scale = snap_mode
    if not snap_loc: pose_bone.location = original_data.get('loc', pose_bone.location)
    if not snap_rot:
        mode = pose_bone.rotation_mode
        if mode == 'QUATERNION': pose_bone.rotation_quaternion = original_data.get('rot_q', pose_bone.rotation_quaternion)
        elif mode == 'AXIS_ANGLE': pose_bone.rotation_axis_angle = original_data.get('rot_a', pose_bone.rotation_axis_angle)
        else: pose_bone.rotation_euler = original_data.get('rot_e', pose_bone.rotation_euler)
    if not snap_scale: pose_bone.scale = original_data.get('scl', pose_bone.scale)

# ==============================================================================
# SECTION 3: SCANNING & PARSING ENGINE
# ==============================================================================

def _clean_search_suffix(self, context, prop_name):
    val = getattr(self, prop_name, "")
    if " (" in val and val.endswith(")"):
        clean_val = val.rsplit(" (", 1)[0]
        setattr(self, prop_name, clean_val)

def _update_prop_search(self, context):
    _clean_search_suffix(self, context, "rrug_prop_search")

def _update_snap_search(self, context):
    _clean_search_suffix(self, context, "rrug_snap_search")

def _get_vis_candidates(self, context, edit_text):
    # Verify active object is an armature
    obj = context.object
    if not obj or obj.type != 'ARMATURE': return []
    # Retrieve UI structure from cache
    ui_data = update_and_get_master_tree_data(obj.data)
    nm = ui_data.get("node_map", {})
    roots = ui_data.get("root_collection_names", [])
    query = edit_text.lower()
    allowed_bones = set()
    # Recursive helper to harvest bones from visibility branches
    def harvest_bones(node_id):
        node = nm.get(node_id)
        if not node: return
        # Check FILTER logic
        # Default to including bones unless restricted
        include_bones = True
        active_flags = node.get("active_flags", set())
        if "FILTER" in active_flags:
            # Retrieve parameter for FILTER flag from flag_list
            f_param = next((p for f, p in node.get("flag_list", []) if f == "FILTER"), None)
            # (FILTER) -> Always exclude from search (handles None and empty string "")
            if not f_param:
                include_bones = False
            # (FILTER)[IFHIDDEN] -> Exclude only if collection is hidden
            elif f_param == "IFHIDDEN":
                if not node.get("is_visible", True):
                    include_bones = False
        # Access the collection and add its bones to the allowed set if allowed
        coll = safe_get_collection(obj.data, node_id)
        if coll and include_bones:
            for b in coll.bones:
                allowed_bones.add(b.name)
        # Continue traversal through children
        for child_id in node.get("children", []):
            harvest_bones(child_id)
    # Initiate harvesting only for roots belonging to the DISPLAYS context
    for r_name in roots:
        root_node = nm.get(r_name)
        if root_node and root_node.get("tree_type") == CTX_VIS:
            harvest_bones(r_name)
    # Filter armature bones based on query and visibility membership
    candidates = [
        b.name for b in obj.data.bones 
        if b.name in allowed_bones and query in b.name.lower()
    ]

    return sorted(candidates)

def _get_prop_candidates(self, context, edit_text):
    obj = context.object
    if not obj or obj.type != 'ARMATURE': return []
    ui_data = update_and_get_master_tree_data(obj.data)
    nm = ui_data.get("node_map", {})
    query = edit_text.lower()
    candidates = set()
    def recurse(layout_list):
        for item in layout_list:
            if isinstance(item, str):
                node = nm.get(item)
                coll = safe_get_collection(obj.data, item)
                # Verify node metadata and collection existence
                if node and coll:
                    col_label = node.get('label', item)
                    # Iterate through custom properties excluding RNA metadata
                    for k in coll.keys():
                        if k != "_RNA_UI":
                            # Apply the regex to clean the key for the search list
                            clean_k = _PROP_ORDER_PATTERN.sub("", k)
                            # Match query against the CLEAN key (or label)
                            if query in clean_k.lower() or query in col_label.lower():
                                # Format display string using the CLEAN key
                                display = f"{clean_k} ({col_label})"
                                candidates.add(display)
                # Cascade search through nested layouts
                if node and node.get("ui_layout"): recurse(node["ui_layout"])
            elif isinstance(item, list):
                recurse(item)
    # Initiate recursive scan from properties root
    recurse(ui_data.get("props_others", []))

    return sorted(list(candidates))

def _get_snap_candidates(self, context, edit_text):
    obj = context.object
    if not obj or obj.type != 'ARMATURE': return []
    ui_data = update_and_get_master_tree_data(obj.data)
    nm = ui_data.get("node_map", {})
    query = edit_text.lower()
    candidates = set()
    def recurse(layout_list):
        for item in layout_list:
            if isinstance(item, str):
                node = nm.get(item)
                # Check for snap group flag on the current node
                if node and node.get("is_snap_group"):
                    label = node.get('label', item)
                    parent_id = node.get("parent")
                    parent_label = "Root"
                    # Resolve parent label to display the containing folder
                    if parent_id and parent_id in nm:
                        parent_label = nm[parent_id].get("label", parent_id)
                    # Match query against snap group label or parent collection label
                    if query in label.lower() or query in parent_label.lower():
                        # Format entry as 'Group Name (Folder Name)' for the search menu
                        display = f"{label} ({parent_label})"
                        candidates.add(display)
                # Recursively scan child layouts
                if node and node.get("ui_layout"): recurse(node["ui_layout"])
            elif isinstance(item, list):
                recurse(item)
    # Initialize traversal from the snapping layout root
    recurse(ui_data.get("snap_layout", []))
    

    return sorted(list(candidates))

def run_structure_scanner(armature, start_collection=None, ignore_skip=False):
    # Initialize data structures for node mapping and traversal tracking
    node_map = {}
    roots = []
    traversal_order = []
    stack = []
    # Define entry point: use specific collection or identify root collections from armature
    if start_collection:
        stack.append((start_collection, None, 0, None)) 
    else:
        # Scan top-level collections and assign UI context based on naming tags
        for c in reversed(armature.collections):
            if c.parent is None:
                ctx = None
                n = c.name
                if "(DISPLAYS)" in n: ctx = CTX_VIS
                elif "(SETTINGS)" in n: ctx = CTX_PROP
                elif "(SNAPS)" in n: ctx = CTX_SNAP
                elif "(INTERNALS)" in n: ctx = CTX_INTERNAL
                stack.append((c, None, 0, ctx))
    # Execute depth-first traversal of the collection hierarchy
    while stack:
        b_coll, parent_id, depth, tree_ctx = stack.pop()
        raw_name = b_coll.name
        traversal_order.append(raw_name)
        # Inherit tree context from naming conventions
        if tree_ctx is None:
             if "(DISPLAYS)" in raw_name: tree_ctx = CTX_VIS
             elif "(SETTINGS)" in raw_name: tree_ctx = CTX_PROP
             elif "(SNAPS)" in raw_name: tree_ctx = CTX_SNAP
             elif "(INTERNALS)" in raw_name: tree_ctx = CTX_INTERNAL
        # Construct node metadata dictionary for the engine
        node = {
            "name": raw_name,
            "parent": parent_id,
            "children": [],
            "is_visible": b_coll.is_visible,
            "is_solo": b_coll.is_solo,
            "label": raw_name,
            "active_flags": set(),
            "flag_list": [],
            "icon_name": None,
            "is_valid": True,
            "ui_layout": [],
            "link_meta": None,
            "tree_type": tree_ctx
        }
        node_map[raw_name] = node
        # Link node to parent or register as a root node
        if parent_id:
            if parent_id in node_map: node_map[parent_id]["children"].append(raw_name)
        else:
            roots.append(raw_name)
        # Enforce filtering for skipped nodes or internal engine data
        if not ignore_skip and "(SKIP)" in raw_name: continue
        if not ignore_skip and tree_ctx == CTX_INTERNAL: continue
        # Recursively add children to stack until maximum nesting limit is reached
        if depth < MAX_UI_NESTING:
            for child in reversed(b_coll.children):
                stack.append((child, raw_name, depth + 1, tree_ctx))
        elif len(b_coll.children) > 0:
            # Mark node if hierarchy exceed recursion depth limits
            node["overflow"] = True

    return {
        "node_map": node_map,
        "root_collection_names": roots,
        "traversal_order": traversal_order
    }

@functools.lru_cache(maxsize=1024)
def _parse_collection_name(raw_name):
    # Initialize parser state and result variables
    valid = True
    err = None
    clean = ""
    flags = []
    active = set()
    icon = None
    remain = raw_name
    # Extract explicit display name using curly brace pattern
    m = _EXPLICIT_NAME_PATTERN.search(remain)
    if m:
        clean = m.group(1).strip()
        remain = remain.replace(m.group(0), "")
    # Find all flag tuples and remove them from the remaining string
    tuples = _FLAG_TUPLE_PATTERN.findall(remain)
    remain = _FLAG_TUPLE_PATTERN.sub("", remain)
    # Validate that no unrecognized characters remain in the string
    leftover = remain.strip()
    if leftover:
        valid = False
        err = f"SYNTAX ERROR: {leftover}"
        clean = ""
    # Process extracted flags and validate parameters
    for f, p in tuples:
        f = f.strip()
        rules = FLAG_CONFIG.get(f)
        if not rules: continue
        # Normalize parameter strings and strip quotes
        if p:
            p = p.strip()
            if p.startswith("'") and p.endswith("'"): p = p[1:-1]
            else: p = p.upper()
        # Check parameter counts and allowed values
        c, msg = rules["params"], None
        if c is None and p:
            msg = f"SYNTAX ERROR: {f} takes no parameters"
        elif p and isinstance(c, (set, str)):
            is_dyn = (_DYNAMIC_PARAM in c) if isinstance(c, set) else (c == _DYNAMIC_PARAM)
            if not is_dyn and not ((p in c) if isinstance(c, set) else (p == c)):
                msg = f"SYNTAX ERROR: '{p}' is not valid for {f}"
        # Execute secondary validation rules if defined
        if not msg and rules["validator"]:
            if not p: msg = f"SYNTAX ERROR: {f} missing parameter"
            elif not rules["validator"](p):
                msg = f"SYNTAX ERROR: '{p}' invalid"
                if f == "ICON": icon = 'ERROR'
        # Update active flags and resolved icon state
        active.add(f)
        flags.append((f, p))
        if msg:
            valid = False
            err = msg
        else:
            if f == "ICON": icon = p

    return {"id": raw_name, "clean_name": clean, "flag_list": flags, "active_flags": active,
            "icon_name": icon, "is_valid": valid, "error_msg": err}

def run_data_parsing(scan_result):
    # Retrieve the node map from the initial scan results
    nm = scan_result.get("node_map", {})
    # Iterate through every scanned collection to extract metadata
    for raw_name, node in nm.items():
        # Execute the regex-based name parser for each collection
        parsed = _parse_collection_name(raw_name)
        # Determine the display label: use the error message if parsing failed, otherwise use the clean name
        final_label = parsed["error_msg"] if not parsed["is_valid"] else parsed["clean_name"]
        # Update the node dictionary with validated flags, icons, and labels
        node.update({
            "label": final_label,
            "flag_list": parsed["flag_list"],
            "active_flags": parsed["active_flags"],
            "icon_name": parsed["icon_name"],
            "is_valid": parsed["is_valid"]
        })

    return scan_result

def _helper_generate_clean_layout(node_names, node_map):
    # Initialize container for finalized layout rows and a buffer for the current row
    layout_rows = []
    current_row_buffer = []
    # Iterate through each node name to determine row grouping
    for name in node_names:
        # Add the current node to the row buffer
        current_row_buffer.append(name)
        node = node_map.get(name, {})
        # Check if the node lacks a JOIN flag, signaling the end of the current row
        if "JOIN" not in node.get("active_flags", set()):
            # Commit the buffer to the layout rows and reset the buffer
            layout_rows.append(current_row_buffer)
            current_row_buffer = []
    # Commit any remaining items in the buffer if the loop terminates without a final commit
    if current_row_buffer: layout_rows.append(current_row_buffer)
 
    return layout_rows

def _helper_resolve_links(node_names, node_map):
    # Initialize index for sequential traversal of node names
    i = 0
    # Iterate through the list to establish partner links between adjacent nodes
    while i < len(node_names):
        curr_name = node_names[i]
        curr_node = node_map.get(curr_name)
        # Skip iteration if the current node metadata is missing
        if not curr_node: i += 1; continue
        # Check for the presence of a LINK flag on the current node
        has_link_request = "LINK" in curr_node.get("active_flags", set())
        # Verify link eligibility by checking for a subsequent node in the list
        if has_link_request and i + 1 < len(node_names):
            next_name = node_names[i + 1]
            next_node = node_map.get(next_name)
            # Establish bidirectional link metadata if the next node exists
            if next_node:
                # Assign the next node as the partner and mark current as the source
                curr_node["link_meta"] = {"partner": next_name, "is_source": True}
                # Assign the current node as the partner for the next node
                next_node["link_meta"] = {"partner": curr_name, "is_source": False}
        # Move to the next index in the sequence
        i += 1

def run_ui_data_preparation(scan_result):
    # Initialize the target data structure for the UI engine
    nm = scan_result.get("node_map", {})
    roots = scan_result.get("root_collection_names", [])
    data = {
        "vis_display": [], "snap_groups": {}, "snap_layout": [],
        "props_others": [], "has_links": False, "found_settings": False
    }

    def is_ui_visible(node_id):
        # Determine if a collection should be rendered in the UI based on visibility flags
        node = nm.get(node_id)
        if not node: return False
        # Check if the HIDE flag is active while the collection is hidden
        if "HIDE" in node["active_flags"] and not node["is_visible"]: return False
        # Exclude nodes explicitly marked with the SKIP flag
        if "SKIP" in node["active_flags"]: return False
        return True
    # Initialize buffers for top-level category branches
    raw_vis = []
    raw_props = []
    raw_snaps = []
    # Categorize root collections into specific UI functional groups
    for r_name in roots:
        node = nm[r_name]
        valid_children = [c for c in node["children"] if is_ui_visible(c)]
        if "(DISPLAYS)" in r_name: raw_vis.extend(valid_children)
        elif "(SETTINGS)" in r_name: raw_props.extend(valid_children)
        elif "(SNAPS)" in r_name: raw_snaps.extend(valid_children)
        elif "(INTERNALS)" in r_name: continue
    # Generate layout grouping and resolve property links for top-level items
    data["vis_display"] = _helper_generate_clean_layout(raw_vis, nm)
    data["props_others"] = _helper_generate_clean_layout(raw_props, nm)
    if raw_props: data["found_settings"] = True
    _helper_resolve_links(raw_props, nm)

    def process_snap_group(group_id):
        # Identify and pair source/target bones within a snapping group
        node = nm.get(group_id)
        if not node: return
        children = node["children"]
        pair_list = []
        i = 0
        while i < len(children):
            curr_id = children[i]
            curr_node = nm.get(curr_id)
            # Use positional forward linking for 'TO' flags to establish snap pairs
            if curr_node and "TO" in curr_node["active_flags"]:
                if i + 1 < len(children):
                    target_id = children[i + 1]
                    pair_list.append((curr_id, target_id))
                    i += 2; continue
            i += 1
        # Register the node as a snap group if pairs were successfully created
        if pair_list:
            data["snap_groups"][group_id] = pair_list
            node["is_snap_group"] = True
        else:
            # Recursively process children if no snap pairs exist at the current level
            valid_snap_children = [c for c in children if is_ui_visible(c)]
            node["ui_layout"] = _helper_generate_clean_layout(valid_snap_children, nm)
            for c in valid_snap_children: process_snap_group(c)
    # Process snapping layout and group hierarchy
    valid_raw_snaps = [s for s in raw_snaps if is_ui_visible(s)]
    data["snap_layout"] = _helper_generate_clean_layout(valid_raw_snaps, nm)
    for r in valid_raw_snaps: process_snap_group(r)

    def prepare_recursive(node_id):
        # Recursively build the UI layout structure for nested collections
        node = nm[node_id]
        valid_children = [
            c for c in node["children"] 
            if nm.get(c, {}).get("tree_type") == node["tree_type"] and is_ui_visible(c)
        ]
        # Resolve property linking specifically within the settings context
        if node["tree_type"] == CTX_PROP:
             _helper_resolve_links(valid_children, nm)
        # Generate formatted layout rows for children and continue recursion
        node["ui_layout"] = _helper_generate_clean_layout(valid_children, nm)
        for c in valid_children: prepare_recursive(c)
    # Trigger final layout preparation for all categorized branches
    for r in raw_vis + raw_props + valid_raw_snaps:
        prepare_recursive(r)
    # Scan node map for established links to update global state
    for node in nm.values():
        if node.get("link_meta"): data["has_links"] = True; break

    scan_result.update(data)
    return scan_result

# ==============================================================================
# SECTION 4: STATE MANAGEMENT
# ==============================================================================

def update_and_get_master_tree_data(armature):
    # Retrieve the computed UI data for the given armature from cache.
    return _rrug_ui_data_cache.get(armature.as_pointer(), _DEFAULT_RRUG_UI_DATA)

def _get_descendant_names(node_map, start_coll_name):
    # Helper to get all recursive descendants for a node.
    descendants = []
    def recurse(name):
        node = node_map.get(name, {})
        for child_name in node.get("children", []):
            descendants.append(child_name)
            recurse(child_name)
    recurse(start_coll_name)
    return descendants

def _cascade_solo_state(armature, scan_result, start_coll_name, new_state):
    # Apply solo state recursively to descendants.
    start_collection = safe_get_collection(armature, start_coll_name)
    if not start_collection: return
    node_map = scan_result.get("node_map", {})
    to_toggle_names = [start_coll_name] + _get_descendant_names(node_map, start_coll_name)
    for name in to_toggle_names:
        coll = safe_get_collection(armature, name)
        if not coll: continue
        final_state = new_state
        node_data = node_map.get(name, {})
        # Respect HIDE flag: do not solo if hidden.
        if new_state:
            if "HIDE" in node_data.get("active_flags", set()) and not coll.is_visible:
                final_state = False
        if getattr(coll, "is_solo", None) != final_state:
            try: coll.is_solo = final_state
            except AttributeError: pass
        if node_data: node_data["is_solo"] = final_state

def _run_temporal_comparator(old_packet, new_packet, manifest):
    # Compare two packets for changes in monitored keys.
    diff_log = {}
    keys_to_monitor = manifest.get("monitored_keys", [])
    if not keys_to_monitor: return diff_log
    old_map = old_packet.get("node_map", {}) if old_packet else {}
    new_map = new_packet.get("node_map", {})
    for coll_name, new_node in new_map.items():
        old_node = old_map.get(coll_name)
        if not old_node: continue
        changes = []
        for key in keys_to_monitor:
            new_val = new_node.get(key)
            old_val = old_node.get(key)
            if new_val != old_val:
                changes.append({"property": key, "to": new_val})
        if changes: diff_log[coll_name] = changes
    return diff_log

# --- Specialized Guards ---

def _guard_hide_state(armature, change_log, node_map, current_packet):
    # Handles visibility-based solo logic for HIDE collections IF parent is soloed.
    did_act = False
    for coll_name, node_data in node_map.items():
        if "HIDE" not in node_data.get("active_flags", set()): continue
        # REQUISITE: Only trigger if the parent is soloed
        parent_id = node_data.get("parent")
        if parent_id:
            parent_node = node_map.get(parent_id)
            if not (parent_node and parent_node.get("is_solo")):
                continue
        coll_changes = change_log.get(coll_name, [])
        vis_change = next((c for c in coll_changes if c["property"] == "is_visible"), None)
        if vis_change:
            # Transition Hidden -> Visible: Restore solo
            if vis_change["to"] is True:
                if not node_data.get("is_solo"):
                    _cascade_solo_state(armature, current_packet, coll_name, True)
                    did_act = True
            # Transition Visible -> Hidden: Force solo OFF
            else:
                if node_data.get("is_solo"):
                    _cascade_solo_state(armature, current_packet, coll_name, False)
                    did_act = True
        # Safety Net: Prevent invisible HIDE items from being soloed if parent is soloed
        elif not node_data.get("is_visible") and node_data.get("is_solo"):
            _cascade_solo_state(armature, current_packet, coll_name, False)
            did_act = True

    return did_act

def _guard_solo_state(armature, change_log, node_map, current_packet):
    # Handles structural "Empty Nest" and "Full Nest" logic.
    did_act = False
    for coll_name, node_data in node_map.items():
        children_ids = node_data.get("children")
        if not children_ids: continue 
        curr_solo = node_data.get("is_solo")
        # Filter children: ignore invisible HIDE collections.
        relevant_children = []
        for cid in children_ids:
            c_node = node_map.get(cid)
            if not c_node: continue
            if "HIDE" in c_node.get("active_flags", set()) and not c_node.get("is_visible"):
                continue
            relevant_children.append(c_node)
        if not relevant_children: continue
        # Scan filtered children state
        all_children_solo = all(c.get("is_solo") for c in relevant_children)
        no_children_solo = not any(c.get("is_solo") for c in relevant_children)
        # Rule 1: EMPTY NEST -> Un-solo parent
        if curr_solo and no_children_solo:
            changes = change_log.get(coll_name, [])
            just_turned_on = any(c["property"] == "is_solo" and c["to"] is True for c in changes)
            if not just_turned_on:
                _cascade_solo_state(armature, current_packet, coll_name, False)
                did_act = True
        # Rule 2: FULL NEST -> Auto-solo parent
        elif not curr_solo and all_children_solo:
            _cascade_solo_state(armature, current_packet, coll_name, True)
            did_act = True
    return did_act

def guard_enforcer(arm, old_packet, current_packet):
    # Patch and stabilize the packet based on dual guard logic.
    node_map = current_packet.get("node_map", {})
    if not node_map: return current_packet

    manifest = {"monitored_keys": ["is_visible", "is_solo"]}
    change_log = _run_temporal_comparator(old_packet, current_packet, manifest)

    # Stabilize states iteratively.
    max_iters = 10
    for _ in range(max_iters):
        act_h = _guard_hide_state(arm, change_log, node_map, current_packet)
        act_s = _guard_solo_state(arm, change_log, node_map, current_packet)
        
        if not (act_h or act_s): break
            
        for coll in arm.collections_all:
            node = node_map.get(coll.name)
            if node:
                node["is_visible"] = coll.is_visible
                node["is_solo"] = coll.is_solo
                
    return current_packet

def rrug_ui_timer_update():
    # Execute main polling loop at a frequency defined by FIXED_FPS
    try:
        global _rrug_ui_data_cache, _entrance_gatekeeper_cache
        # Identify currently valid armature pointers to prevent memory leaks
        live_keys = {a.as_pointer() for a in bpy.data.armatures}
        # Purge cached data for armatures that no longer exist in the Blender session
        for key in list(_rrug_ui_data_cache.keys()):
            if key not in live_keys:
                del _rrug_ui_data_cache[key]
                if key in _entrance_gatekeeper_cache: del _entrance_gatekeeper_cache[key]
        # Verify that the active object is a valid armature and contains the RRUG trigger property
        obj = getattr(bpy.context, "active_object", None)
        if not obj or obj.type != 'ARMATURE' or not obj.data: return 1.0 / FIXED_FPS
        if not obj.data.get(RRUG_TRIGGER_KEY): return 1.0 / FIXED_FPS
        arm = obj.data
        arm_key = arm.as_pointer()
        # Initiate structure scan to capture the current state of bone collections
        raw_packet = run_structure_scanner(arm)
        nm = raw_packet["node_map"]
        order = raw_packet["traversal_order"]
        # Construct a state snapshot representing visibility and solo status for change detection
        current_state = tuple(
            (
                name, 
                nm[name]["is_visible"], 
                nm[name]["is_solo"], 
                nm[name]["parent"], 
                nm[name].get("overflow", False)
            ) 
            for name in order
        )
        cached_state = _entrance_gatekeeper_cache.get(arm_key)
        # Trigger processing pipeline only if a structural or state change is detected
        if current_state != cached_state:
            # Update the gatekeeper cache with the new state snapshot
            _entrance_gatekeeper_cache[arm_key] = current_state
            # Parse raw collection names into validated UI metadata
            parsed_packet = run_data_parsing(raw_packet)
            old_packet = _rrug_ui_data_cache.get(arm_key)
            # Stabilize states using guard logic and prepare the final UI layout structure
            stabilized_packet = guard_enforcer(arm, old_packet, parsed_packet)
            final_packet = run_ui_data_preparation(stabilized_packet)
            # Commit the prepared packet to the global cache and request a viewport redraw
            _rrug_ui_data_cache[arm_key] = final_packet
            limited_redraw()
    except Exception:
        # Log any internal engine errors to the console for debugging
        traceback.print_exc()
    # Schedule the next timer execution based on the fixed FPS interval
    return 1.0 / FIXED_FPS
# ==============================================================================
# SECTION 5: UI DRAWING LOGIC
# ==============================================================================
def _draw_expand_buttons(layout, panel_type):
    row = layout.row(align=True)
    op_col = row.operator("rrug_ui.expand_all", text="", icon='FULLSCREEN_EXIT')
    op_col.action = 'COLLAPSE'; op_col.panel = panel_type
    op_exp = row.operator("rrug_ui.expand_all", text="", icon='FULLSCREEN_ENTER')
    op_exp.action = 'EXPAND'; op_exp.panel = panel_type

def draw_vis_recursive(layout, armature, node_id, ui_data, depth=0):
    # Terminate recursion if the maximum nesting depth is exceeded
    if depth > MAX_UI_NESTING: return
    # Retrieve node metadata and the corresponding bone collection
    nm = ui_data.get("node_map", {})
    node = nm.get(node_id)
    if not node: return
    if not (coll := safe_get_collection(armature, node_id)): return
    # Extract UI properties
    lbl = node["label"]
    is_valid = node.get("is_valid", True)
    flags = node["active_flags"]
    # Check for content: Valid Children OR an Overflow flag
    has_children = bool(node["ui_layout"])
    has_overflow = node.get("overflow", False)
    
    # --- BRANCH: BOARD MODE ---
    if "BOARD" in flags:
        box = layout.box()
        # Header Row
        row = box.row(align=True)
        if not is_valid: row.alert = True
        
        # 1. Label (Left)
        ic = node.get("icon_name") or 'FILE_FOLDER'
        row.label(text=lbl, icon=ic)
        
        # 2. Buttons (Right)
        # Create a sub-row for buttons to keep them aligned to the right or integrated
        btns = row.row(align=True)
        btns.alignment = 'RIGHT'
        
        btns.operator("rrug_ui.select_replace", text="", icon='RESTRICT_SELECT_OFF').collection_name = node_id
        btns.operator("rrug_ui.select_add", text="", icon='ADD').collection_name = node_id
        
        if "HIDE" not in flags:
            btns.operator("rrug_ui.vis_toggle", text="",
                        icon='HIDE_OFF' if coll.is_visible else 'HIDE_ON').collection_name = node_id 
                        
        btns.operator("rrug_ui.solo_toggle", text="",
                    icon='SOLO_ON' if coll.is_solo else 'SOLO_OFF').collection_name = node_id
        
        # Render children unconditionally (Always Open)
        inner = box.column(align=True)
        if has_children:
            for row_group in node["ui_layout"]:
                if isinstance(row_group, list):
                    if len(row_group) == 1:
                        draw_vis_recursive(inner, armature, row_group[0], ui_data, depth + 1)
                    else:
                        split = inner.row(align=True).split(factor=1.0 / len(row_group), align=True)
                        for k, i in enumerate(row_group):
                            draw_vis_recursive(split, armature, i, ui_data, depth + 1)
                            if k < len(row_group) - 1:
                                split = split.split(factor=1.0 / (len(row_group) - (k + 1)), align=True)
        if has_overflow:
            err_box = inner.box(); err_row = err_box.row(align=True); err_row.alert = True
            err_row.label(text="Max Depth Exceeded", icon='ERROR')
            
    # --- BRANCH: STANDARD MODE ---
    else:
        show_expand = has_children or has_overflow
        box = layout.box()
        # Configure row alignment based on the presence of the INLINE flag
        is_inline = "INLINE" in flags
        row = box.row(align=True)
        if not is_valid: row.alert = True
        # Assign the button container to the main row or a secondary centered row
        if is_inline: btns = row
        else:
            row.alignment = 'CENTER'
            btns = box.row(align=True)
            btns.alignment = 'CENTER'
        # Select icon: Use folder if expandable (children or overflow), else bone
        default_icon = 'COLLECTION_NEW' if show_expand else 'BONE_DATA'
        ic = node.get("icon_name") or default_icon
        # Render either an expansion toggle or a static label based on content availability
        if show_expand: row.prop(coll, "is_expanded", text=lbl, icon=ic)
        else: row.label(text=lbl, icon=ic)
        # Add selection operators for bone management
        btns.operator("rrug_ui.select_replace", text="", icon='RESTRICT_SELECT_OFF').collection_name = node_id
        btns.operator("rrug_ui.select_add", text="", icon='ADD').collection_name = node_id
        # Conditionally add visibility toggle if the HIDE flag is absent
        if "HIDE" not in flags:
            btns.operator("rrug_ui.vis_toggle", text="",
                        icon='HIDE_OFF' if coll.is_visible else 'HIDE_ON').collection_name = node_id 
        # Add the solo toggle operator
        btns.operator("rrug_ui.solo_toggle", text="",
                    icon='SOLO_ON' if coll.is_solo else 'SOLO_OFF').collection_name = node_id
        # Recursively render content if the collection is expanded
        if show_expand and coll.is_expanded:
            inner = box.column(align=True)
            if has_children:
                for row_group in node["ui_layout"]:
                    if isinstance(row_group, list):
                        if len(row_group) == 1:
                            draw_vis_recursive(inner, armature, row_group[0], ui_data, depth + 1)
                        else:
                            split = inner.row(align=True).split(factor=1.0 / len(row_group), align=True)
                            for k, i in enumerate(row_group):
                                draw_vis_recursive(split, armature, i, ui_data, depth + 1)
                                if k < len(row_group) - 1:
                                    split = split.split(factor=1.0 / (len(row_group) - (k + 1)), align=True)
            if has_overflow:
                err_box = inner.box(); err_row = err_box.row(align=True); err_row.alert = True
                err_row.label(text="Max Depth Exceeded", icon='ERROR')

def draw_props_recursive(layout, armature, node_id, ui_data):
    # Retrieve node metadata and verify existence
    nm = ui_data.get("node_map", {})
    node = nm.get(node_id)
    if not node: return
    if not (coll := safe_get_collection(armature, node_id)): return
    # Extract Metadata
    lbl = node.get("label", node_id)
    is_valid = node.get("is_valid", True)
    flags = node.get("active_flags", set())
    link = node.get("link_meta")
    # Check content types
    has_children = bool(node.get("ui_layout"))
    has_overflow = node.get("overflow", False)
    # Setup Container
    box = layout.box()
    # --- HEADER ROW ---
    row = box.row(align=True)
    if not is_valid: row.alert = True
    # 1. Reset Button (Always available)
    row.operator("rrug_ui.reset", text="", icon='LOOP_BACK').collection_name = node_id
    # 2. Label / Toggle
    default_icon = 'LINKED' if link else ('FILE_FOLDER' if (has_children or has_overflow) else 'SETTINGS')
    ic = node.get("icon_name") or default_icon
    is_board = "BOARD" in flags
    if is_board:
        row.label(text=lbl, icon=ic)
        show_content = True
    else:
        row.prop(coll, "is_expanded", text=lbl, icon=ic)
        show_content = coll.is_expanded
    # 3. Symmetrize Button (If linked)
    if link:
        src = link["is_source"]
        op = row.operator("rrug_ui.prop_symmetrize", text="", icon='TRIA_RIGHT' if src else 'TRIA_LEFT')
        op.sync_left_to_right = src
        op.l_name, op.r_name = (node_id, link["partner"]) if src else (link["partner"], node_id)
    # --- CONTENT BLOCK ---
    if show_content:
        col = box.column(align=True)
        # Part A: Custom Properties (Modified for {01} stripping)
        # -------------------------
        keys = [k for k in sorted(coll.keys()) if k != "_RNA_UI"]
        if keys:
            for k in keys:
                # Clean the display name using the regex
                display_name = _PROP_ORDER_PATTERN.sub("", k)
                col.prop(coll, f'["{k}"]', text=display_name)
        # Part B: Nested Children
        # -----------------------
        if has_children or has_overflow:
            if keys: col.separator()
            if has_children:
                for row_group in node["ui_layout"]:
                    if isinstance(row_group, list):
                        if len(row_group) == 1:
                            draw_props_recursive(col, armature, row_group[0], ui_data)
                        else:
                            split = col.row(align=True).split(factor=1.0 / len(row_group), align=True)
                            for k, i in enumerate(row_group):
                                draw_props_recursive(split, armature, i, ui_data)
                                if k < len(row_group) - 1:
                                    split = split.split(factor=1.0 / (len(row_group) - (k + 1)), align=True)      
            if has_overflow:
                err_box = col.box(); err_row = err_box.row(align=True); err_row.alert = True
                err_row.label(text="Max Depth Exceeded", icon='ERROR')
        # Part C: Empty State
        elif not keys:
            col.label(text="No properties.", icon='INFO')

def draw_snap_recursive(layout, armature, node_id, ui_data):
    # Fetch node metadata and verify the existence of the bone collection
    nm = ui_data.get("node_map", {})
    node = nm.get(node_id)
    if not node: return
    coll = safe_get_collection(armature, node_id)
    if not coll: return
    # Extract labeling and validation status
    lbl = node.get("label") or node_id
    is_valid = node.get("is_valid", True)
    flags = node.get("active_flags", set())
    # Logic for structural folders needs to accommodate overflow
    has_children = bool(node.get("ui_layout"))
    has_overflow = node.get("overflow", False)
    # Process functional snap groups containing bone pairs (Terminal Nodes)
    if node.get("is_snap_group"):
        # Configure layout flow based on the INLINE flag
        is_inline = "INLINE" in flags
        if is_inline:
            # Map both label and buttons to a single horizontal row
            container = layout.row(align=True)
            lbl_row = container; btn_row = container
        else:
            # Stack the label and buttons vertically with center alignment
            container = layout.column(align=True)
            lbl_row = container.row(align=True)
            lbl_row.alignment = 'CENTER'
            btn_row = container.row(align=True)
            btn_row.alignment = 'CENTER'
        # Trigger visual alert if the node metadata is invalid
        if not is_valid: lbl_row.alert = True
        # Render the group label with an icon
        ic = node.get("icon_name")
        lbl_row.label(text=lbl, icon=ic if ic else 'GROUP_BONE')
        # Add discrete snap operators for Location, Rotation, and Scale
        op = btn_row.operator("rrug_ui.snap_hierarchy_batch", text="", icon='CON_LOCLIKE')
        op.parent_collection_name = node_id; op.snap_loc = True; op.snap_rot = False; op.snap_scale = False
        op = btn_row.operator("rrug_ui.snap_hierarchy_batch", text="", icon='CON_ROTLIKE')
        op.parent_collection_name = node_id; op.snap_loc = False; op.snap_rot = True; op.snap_scale = False
        op = btn_row.operator("rrug_ui.snap_hierarchy_batch", text="", icon='CON_SIZELIKE')
        op.parent_collection_name = node_id; op.snap_loc = False; op.snap_rot = False; op.snap_scale = True
        # Add a master snap operator for all transform channels
        op = btn_row.operator("rrug_ui.snap_hierarchy_batch", text="", icon='SNAP_ON')
        op.parent_collection_name = node_id; op.snap_loc = True; op.snap_rot = True; op.snap_scale = True
    # Process structural folder collections (Containers)
    else:
        # Determine if we show the expansion arrow (has children or overflow)
        show_expand = has_children or has_overflow
        box = layout.box()
        
        # --- BRANCH: BOARD MODE ---
        if "BOARD" in flags:
            row = box.row(align=True)
            if not is_valid: row.alert = True
            ic = node.get("icon_name") or 'FILE_FOLDER'
            row.label(text=lbl, icon=ic)
            should_draw_children = True
        # --- BRANCH: STANDARD MODE ---
        else:
            row = box.row(align=True)
            if not is_valid: row.alert = True
            ic = node.get("icon_name")
            icon_to_use = ic if ic else 'FILE_FOLDER'
            if show_expand:
                row.prop(coll, "is_expanded", text=lbl, icon=icon_to_use)
            else:
                row.label(text=lbl, icon=icon_to_use)
            should_draw_children = (show_expand and coll.is_expanded)
        # Recursively render nested snap groups or folders
        if should_draw_children:
            inner = box.column(align=True)
            # 1. Render Children
            if has_children:
                for row_group in node.get("ui_layout", []):
                    if isinstance(row_group, list):
                        if len(row_group) == 1:
                            draw_snap_recursive(inner, armature, row_group[0], ui_data)
                        else:
                            split = inner.row(align=True).split(factor=1.0 / len(row_group), align=True)
                            for k, item in enumerate(row_group):
                                draw_snap_recursive(split, armature, item, ui_data)
                                if k < len(row_group) - 1:
                                    split = split.split(factor=1.0 / (len(row_group) - (k + 1)), align=True)
            # 2. Render Overflow Warning
            if has_overflow:
                err_box = inner.box(); err_row = err_box.row(align=True); err_row.alert = True
                err_row.label(text="Max Depth Exceeded", icon='ERROR')

# --- Filtered Drawers ---
def draw_vis_filtered(layout, armature, ui_data, query):
    # Retrieve node map and normalize search query
    nm = ui_data.get("node_map", {})
    query = query.lower()
    any_found = False
    
    def scan_recursive(layout_list):
        nonlocal any_found
        for item in layout_list:
            if isinstance(item, str):
                node_id = item
                node = nm.get(node_id)
                coll = safe_get_collection(armature, node_id)
                # Check for bone matches within the current collection
                if node and coll:
                    has_match = False
                    for b in coll.bones:
                        if query in b.name.lower():
                            has_match = True
                            break
                    # Render collection entry if a match is found
                    if has_match:
                        any_found = True
                        box = layout.box()
                        row = box.row(align=True)
                        ic = node.get("icon_name") or 'BONE_DATA'
                        row.label(text=node.get("label", node_id), icon=ic)
                        # Draw bone selection and visibility operators
                        btns = row.row(align=True)
                        btns.operator("rrug_ui.select_replace", text="", icon='RESTRICT_SELECT_OFF').collection_name = node_id
                        btns.operator("rrug_ui.select_add", text="", icon='ADD').collection_name = node_id
                        # Only show visibility toggle if the HIDE flag is not set
                        if "HIDE" not in node.get("active_flags", set()):
                            btns.operator("rrug_ui.vis_toggle", text="",
                                          icon='HIDE_OFF' if coll.is_visible else 'HIDE_ON').collection_name = node_id
                        btns.operator("rrug_ui.solo_toggle", text="",
                                      icon='SOLO_ON' if coll.is_solo else 'SOLO_OFF').collection_name = node_id
                # Recursively process child layouts
                if node and node.get("ui_layout"): 
                    scan_recursive(node["ui_layout"])
            elif isinstance(item, list):
                scan_recursive(item)
    # Initiate scan from the visibility display root
    scan_recursive(ui_data.get("vis_display", []))
    if not any_found: 
        layout.label(text="No matching results found.", icon='INFO')

def draw_props_filtered(layout, armature, ui_data, query):
    # Retrieve node map and normalize search query
    nm = ui_data.get("node_map", {})
    query = query.lower()
    any_found = False
    
    def scan_recursive(layout_list):
        nonlocal any_found
        for item in layout_list:
            if isinstance(item, str):
                node_id = item
                node = nm.get(node_id)
                coll = safe_get_collection(armature, node_id)
                # Scan for matches within property keys or collection labels
                if node and coll:
                    node_label = node.get('label', node_id)
                    matches = []
                    for k in coll.keys():
                        if k == "_RNA_UI": continue
                        # Match query against CLEAN key (or raw key) + label
                        clean_k = _PROP_ORDER_PATTERN.sub("", k)
                        if query in k.lower() or query in clean_k.lower() or query in node_label.lower():
                            matches.append(k)
                    # Draw matching properties inside a container box
                    if matches:
                        any_found = True
                        box = layout.box()
                        row = box.row()
                        row.label(text=node_label, icon='FILE_FOLDER')
                        op = row.operator("rrug_ui.reset", text="", icon='LOOP_BACK')
                        op.collection_name = node_id
                        for k in matches: 
                            # Clean the display name here too
                            display_name = _PROP_ORDER_PATTERN.sub("", k)
                            box.prop(coll, f'["{k}"]', text=display_name)
                # Recurse through nested layouts
                if node and node.get("ui_layout"): 
                    scan_recursive(node["ui_layout"])
            elif isinstance(item, list):
                scan_recursive(item)
    # Initiate scan from the properties root
    scan_recursive(ui_data.get("props_others", []))
    if not any_found: 
        layout.label(text="No matching results found.", icon='INFO')

def draw_snap_filtered(layout, armature, ui_data, query):
    # Retrieve node map and normalize search query
    nm = ui_data.get("node_map", {})
    query = query.lower()
    any_found = False
    def scan_recursive(layout_list):
        nonlocal any_found
        for item in layout_list:
            if isinstance(item, str):
                node_id = item
                node = nm.get(node_id)
                # Focus processing on established snap groups
                if node and node.get("is_snap_group"):
                    label = node.get("label", node_id)
                    parent_id = node.get("parent")
                    parent_label = "Root"
                    # Identify the parent collection for the folder header
                    if parent_id and parent_id in nm:
                        parent_label = nm[parent_id].get("label", parent_id)
                    # Match query against group label or parent folder name
                    if query in label.lower() or query in parent_label.lower():
                        any_found = True
                        box = layout.box()
                        # Draw containing folder header
                        head = box.row()
                        head.label(text=parent_label, icon='FILE_FOLDER')
                        # Draw individual snap group row and operators
                        row = box.row(align=True)
                        row.label(text=label, icon=node.get("icon_name") or 'GROUP_BONE')
                        btn_row = row.row(align=True)
                        # Add snapping operators for Loc, Rot, Scale, and All
                        op = btn_row.operator("rrug_ui.snap_hierarchy_batch", text="", icon='CON_LOCLIKE')
                        op.parent_collection_name = node_id; op.snap_loc = True; op.snap_rot = False; op.snap_scale = False
                        op = btn_row.operator("rrug_ui.snap_hierarchy_batch", text="", icon='CON_ROTLIKE')
                        op.parent_collection_name = node_id; op.snap_loc = False; op.snap_rot = True; op.snap_scale = False
                        op = btn_row.operator("rrug_ui.snap_hierarchy_batch", text="", icon='CON_SIZELIKE')
                        op.parent_collection_name = node_id; op.snap_loc = False; op.snap_rot = False; op.snap_scale = True
                        op = btn_row.operator("rrug_ui.snap_hierarchy_batch", text="", icon='SNAP_ON')
                        op.parent_collection_name = node_id; op.snap_loc = True; op.snap_rot = True; op.snap_scale = True
                # Continue depth-first search through children
                if node and node.get("ui_layout"):
                    scan_recursive(node["ui_layout"])
            elif isinstance(item, list):
                scan_recursive(item)
    # Initiate scan from the snapping layout root
    scan_recursive(ui_data.get("snap_layout", []))
    if not any_found:
        layout.label(text="No matching snap groups found.", icon='INFO')
# ==============================================================================
# SECTION 6: OPERATORS
# ==============================================================================
class RRUG_OperatorMixin:
    _metadata_key = ""
    @classmethod
    def description(cls, context, properties):
        if not cls._metadata_key: return ""
        meta = _TIPS.get(cls._metadata_key)
        if meta and isinstance(meta, tuple): return meta[1]
        return ""

class RRUG_OT_get_active_bone_to_search(bpy.types.Operator, RRUG_OperatorMixin):
    bl_idname = "rrug_ui.get_active_bone_to_search"
    bl_label = "Get Active"
    _metadata_key = "VIS_GET_ACTIVE"
    bl_options = {'UNDO', 'INTERNAL'}

    def execute(self, context):
        # Set search string to active pose bone name
        if pb := context.active_pose_bone:
            context.object.data.rrug_vis_search = pb.name
        return {'FINISHED'}

class RRUG_OT_zero_cursor_axis(bpy.types.Operator, RRUG_OperatorMixin):
    bl_idname = "rrug_ui.zero_cursor_axis"
    bl_label = "Zero Axis"
    bl_options = {'UNDO'}
    _metadata_key = "ZERO_AXIS"
    axis: bpy.props.IntProperty()
    def execute(self, context):
        cursor = context.scene.cursor
        mode = cursor.rotation_mode
        if mode == 'QUATERNION':
            val = cursor.rotation_quaternion.copy(); val[self.axis] = 0.0; cursor.rotation_quaternion = val
        elif mode == 'AXIS_ANGLE':
            val = cursor.rotation_axis_angle.copy(); val[self.axis] = 0.0; cursor.rotation_axis_angle = val
        else:
            val = cursor.rotation_euler.copy(); val[self.axis] = 0.0; cursor.rotation_euler = val
        return {'FINISHED'}

class RRUG_OT_reset_pose_transforms(bpy.types.Operator):
    # Define operator identifiers and registration properties
    bl_idname = "rrug_ui.reset_pose_transforms"
    bl_label = "Reset Pose"
    bl_options = {'UNDO'}
    # Configure selection scope and transform channel properties
    subset: bpy.props.EnumProperty(items=[('SELECTED', "Selected", ""), ('ALL', "All", "")], default='SELECTED')
    clear_type: bpy.props.EnumProperty(items=[('LOC', "Location", ""), ('ROT', "Rotation", ""), ('SCALE', "Scale", ""), ('ALL', "All", "")], default='ALL')
    @classmethod
    def description(cls, context, properties):
        # Resolve dynamic tooltip key based on property state
        mode_prefix = "RST_SEL" if properties.subset == 'SELECTED' else "RST_RIG"
        key = f"{mode_prefix}_{properties.clear_type}"
        return _TIPS.get(key, ("", "Reset Pose Transforms"))[1]

    def execute(self, context):
        def run_clear_cmds():
            # Trigger native Blender operators for specific transform clearing
            if self.clear_type == 'LOC': bpy.ops.pose.loc_clear()
            elif self.clear_type == 'ROT': bpy.ops.pose.rot_clear()
            elif self.clear_type == 'SCALE': bpy.ops.pose.scale_clear()
            elif self.clear_type == 'ALL': bpy.ops.pose.transforms_clear()

        if self.subset == 'SELECTED':
            # Execute clear commands on current viewport selection
            if not context.selected_pose_bones:
                self.report({'WARNING'}, "No bones selected")
                return {'CANCELLED'}
            run_clear_cmds()
        elif self.subset == 'ALL':
            # Cache selection, select all rig bones, clear, then restore selection
            selected_names = [b.name for b in context.selected_pose_bones]
            bpy.ops.pose.select_all(action='SELECT')
            run_clear_cmds()
            bpy.ops.pose.select_all(action='DESELECT')
            for name in selected_names:
                pb = context.object.pose.bones.get(name)
                # FIXED: Use version-safe helper instead of direct attribute access
                if pb: select_bone(context.object, pb.bone)
        return {'FINISHED'}

class RRUG_OT_expand_all(bpy.types.Operator, RRUG_OperatorMixin):
    # Define operator identifiers and mixin metadata
    bl_idname = "rrug_ui.expand_all"
    bl_label = "Expand/Collapse"
    _metadata_key = "EXPAND_ALL"
    bl_options = {'UNDO'}
    # Configure toggle action and target UI panel scope
    action: bpy.props.EnumProperty(items=[('EXPAND', "Expand", ""), ('COLLAPSE', "Collapse", "")], default='EXPAND')
    panel: bpy.props.EnumProperty(items=[('VIS', "Visibility", ""), ('PROPS', "Properties", ""), ('SNAP', "Snapping", "")], default='VIS')

    def execute(self, context):
        arm = context.object.data
        ui_data = update_and_get_master_tree_data(arm)
        nm = ui_data.get("node_map", {})
        allowed_collections = set()
        def harvest_from_layout(layout_list):
            # Recursively collect collection names from the targeted UI branch
            if not layout_list: return
            for row in layout_list:
                if isinstance(row, list):
                    for item in row:
                        if isinstance(item, str):
                            allowed_collections.add(item)
                            node = nm.get(item)
                            if node and node.get("ui_layout"): harvest_from_layout(node["ui_layout"])
        # Select the layout branch based on the panel property
        if self.panel == 'VIS': harvest_from_layout(ui_data.get("vis_display", []))
        elif self.panel == 'PROPS': harvest_from_layout(ui_data.get("props_others", []))
        elif self.panel == 'SNAP': harvest_from_layout(ui_data.get("snap_layout", []))
        # Apply expansion state to all harvested collections
        target_state = (self.action == 'EXPAND')
        for coll_name in allowed_collections:
            coll = safe_get_collection(arm, coll_name)
            if coll: coll.is_expanded = target_state
            
        context.view_layer.update()
        return {'FINISHED'}

class RRUG_OT_snap_cursor_utils(bpy.types.Operator):
    # Define operator identifiers and snap direction options
    bl_idname = "rrug_ui.snap_cursor_utils"
    bl_label = "Cursor Snap"
    bl_options = {'UNDO'}
    
    action: bpy.props.EnumProperty(
        items=[
            ('CURS_TO_SEL_LOC', "Cursor -> Sel (Loc)", ""),
            ('CURS_TO_SEL_ROT', "Cursor -> Sel (Rot)", ""),
            ('CURS_TO_SEL_ALL', "Cursor -> Sel (All)", ""),
            ('SEL_TO_CURS_LOC', "Sel -> Cursor (Loc)", ""),
            ('SEL_TO_CURS_ROT', "Sel -> Cursor (Rot)", ""),
            ('SEL_TO_CURS_ALL', "Sel -> Cursor (All)", ""),
        ]
    )

    @classmethod
    def description(cls, context, properties):
        # Resolve specific descriptive text based on the active action
        if properties.action == 'CURS_TO_SEL_LOC': return "Snap Cursor Location to Active Bone"
        if properties.action == 'CURS_TO_SEL_ROT': return "Snap Cursor Rotation to Active Bone"
        if properties.action == 'CURS_TO_SEL_ALL': return "Snap Cursor to Active Bone (Loc & Rot)"
        if properties.action == 'SEL_TO_CURS_LOC': return _TIPS["SNAP_SEL_TO_CURS_LOC"][1]
        if properties.action == 'SEL_TO_CURS_ROT': return _TIPS["SNAP_SEL_TO_CURS_ROT"][1]
        if properties.action == 'SEL_TO_CURS_ALL': return _TIPS["SNAP_SEL_TO_CURS_ALL"][1]
        return "Cursor Snap Operations"

    def execute(self, context):
        obj = context.active_object
        arm = obj.data
        cursor = context.scene.cursor
        # Handle Cursor snapping to Active Bone
        if self.action.startswith('CURS_TO_SEL'):
            pb = context.active_pose_bone
            if not pb:
                self.report({'WARNING'}, "No active bone")
                return {'CANCELLED'}
            loc, rot, _ = pb.matrix.decompose()
            if 'LOC' in self.action or 'ALL' in self.action:
                cursor.location = loc
            if 'ROT' in self.action or 'ALL' in self.action:
                # Apply rotation based on the cursor's current rotation mode
                if cursor.rotation_mode == 'QUATERNION':
                    cursor.rotation_quaternion = rot
                elif cursor.rotation_mode == 'AXIS_ANGLE':
                    cursor.rotation_axis_angle = rot.to_axis_angle()
                else:
                    cursor.rotation_euler = rot.to_euler(cursor.rotation_mode)
            return {'FINISHED'}
        # Handle Selection snapping to Cursor
        bones = context.selected_pose_bones
        if not bones:
            self.report({'WARNING'}, "No bones selected")
            return {'CANCELLED'}
        # Determine transform mask
        if 'LOC' in self.action: snap_mode = (True, False, False)
        elif 'ROT' in self.action: snap_mode = (False, True, False)
        else: snap_mode = (True, True, False)
        target_matrix = cursor.matrix
        for pb in bones:
            # Decompose current matrix and recompose with cursor transforms
            pb.matrix = get_composed_matrix(pb.matrix, target_matrix, snap_mode)
            # Apply keyframes if auto-keying is enabled for snapping
            if arm.rrug_auto_key:
                apply_keyframes(pb, snap_mode)
        context.view_layer.update()
        return {'FINISHED'}

class RRUG_OT_snap_hierarchy_batch(bpy.types.Operator, RRUG_OperatorMixin):
    # Define operator identifiers and metadata keys
    bl_idname = "rrug_ui.snap_hierarchy_batch"
    bl_label = "Snap Hierarchy"
    _metadata_key = "SNAP"
    bl_options = {'UNDO'}
    
    # Define properties for snap targets and transform channels
    parent_collection_name: bpy.props.StringProperty()
    snap_loc: bpy.props.BoolProperty(default=True)
    snap_rot: bpy.props.BoolProperty(default=True)
    snap_scale: bpy.props.BoolProperty(default=True)

    def execute(self, context):
        # Access armature data and global snapping settings
        obj, data = context.active_object, context.active_object.data
        keys, mirror = data.rrug_auto_key, data.rrug_snap_mirror
        mode = (self.snap_loc, self.snap_rot, self.snap_scale)
        # Retrieve snap pair definitions from the UI data cache
        ui = update_and_get_master_tree_data(data)
        pairs = ui.get("snap_groups", {}).get(self.parent_collection_name, [])
        if not pairs: return {'CANCELLED'}
        bones = obj.pose.bones
        l_set, r_set = set(), set()
        resolved = []
        # Resolve collection names into valid bone collection objects
        for s, t in pairs:
            sc, tc = safe_get_collection(data, s), safe_get_collection(data, t)
            if sc and tc: resolved.append((sc, tc))

        def apply(s_name, t_name):
            # Apply source-to-target matrix transforms and handle keyframing
            pb_s, pb_t = bones.get(s_name), bones.get(t_name)
            if pb_s and pb_t:
                pb_s.matrix = get_composed_matrix(pb_s.matrix, pb_t.matrix, mode)
                if keys: apply_keyframes(pb_s, mode)
                # Track bones for subsequent mirror operations if side-suffixes match
                if mirror:
                    if s_name.endswith(".L"): l_set.add(s_name)
                    elif s_name.endswith(".R"): r_set.add(s_name)
                return True
            return False
        # Iterate through snap chains to ensure hierarchical dependencies are resolved
        for _ in range(max(1, len(resolved))):
            did_update = False
            for sc, tc in resolved:
                # Sort bones by name to ensure consistent pairing between collections
                srcs, tgts = sorted(sc.bones, key=lambda b: b.name), sorted(tc.bones, key=lambda b: b.name)
                for s, t in zip(srcs, tgts):
                    if apply(s.name, t.name): did_update = True
            # Terminate iteration if no further matrix updates are detected
            if not did_update: break
            context.view_layer.update()
        # Execute mirror-paste logic if mirroring is enabled and bones are flagged
        if mirror and (l_set or r_set):
            win, area = get_3d_view_area(context)
            # GUARD: Ensure a valid 3D Viewport exists for the operator override
            if win and area:
                # Use context override to execute viewport-dependent operators
                with context.temp_override(window=win, area=area):
                    def run_mirror(names):
                        # Deselect all and select target source bones
                        bpy.ops.pose.select_all(action='DESELECT')
                        for n in names:
                            if pb := bones.get(n): select_bone(obj, pb.bone)
                        restore = {}
                        # Cache transform state for opposite-side bones to prevent unwanted channel updates
                        for n in names:
                            opp = None
                            if n.endswith(".L"): opp = n[:-2] + ".R"
                            elif n.endswith(".R"): opp = n[:-2] + ".L"
                            if opp and (pb := bones.get(opp)):
                                restore[opp] = {'loc': pb.location.copy(), 'scl': pb.scale.copy()}
                                if pb.rotation_mode == 'QUATERNION': restore[opp]['rot_q'] = pb.rotation_quaternion.copy()
                                elif pb.rotation_mode == 'AXIS_ANGLE': restore[opp]['rot_a'] = pb.rotation_axis_angle.copy()
                                else: restore[opp]['rot_e'] = pb.rotation_euler.copy()
                        # Use native Blender copy-paste flipped operator
                        bpy.ops.pose.copy()
                        bpy.ops.pose.paste(flipped=True)
                        # Revert non-snapped channels to original cached values
                        for n, d in restore.items():
                            if pb := bones.get(n):
                                restore_mirror_channels(pb, d, mode)
                                if keys: apply_keyframes(pb, mode)
                    # Process left-to-right and right-to-left sets independently
                    if l_set: run_mirror(l_set)
                    if r_set: run_mirror(r_set)
                    context.view_layer.update()
            else:
                # ERROR HANDLING: Notify user if context is missing
                self.report({'WARNING'}, "Mirror Snap requires an open 3D Viewport.")
                return {'CANCELLED'}
        return {'FINISHED'}

class RRUG_OT_select_replace(bpy.types.Operator, RRUG_OperatorMixin):
    bl_idname = "rrug_ui.select_replace"
    bl_label = "Replace"
    _metadata_key = "SEL_REPLACE"
    bl_options = {'UNDO'}
    collection_name: bpy.props.StringProperty()

    def execute(self, ctx):
        arm_obj = ctx.active_object
        arm = arm_obj.data
        bpy.ops.pose.select_all(action='DESELECT')
        ui = update_and_get_master_tree_data(arm)
        nm = ui.get("node_map", {})
        targets = [self.collection_name]
        def collect(nid):
            node = nm.get(nid, {})
            for c in node.get("children", []):
                targets.append(c)
                collect(c)
        collect(self.collection_name)
        for t in targets:
            c = safe_get_collection(arm, t)
            if c:
                for b in c.bones: select_bone(arm_obj, b)
        limited_redraw()
        return {'FINISHED'}

class RRUG_OT_select_add(bpy.types.Operator, RRUG_OperatorMixin):
    bl_idname = "rrug_ui.select_add"
    bl_label = "Add"
    _metadata_key = "SEL_ADD"
    bl_options = {'UNDO'}
    collection_name: bpy.props.StringProperty()

    def execute(self, ctx):
        arm_obj = ctx.active_object
        arm = arm_obj.data
        ui = update_and_get_master_tree_data(arm)
        nm = ui.get("node_map", {})
        targets = [self.collection_name]
        def collect(nid):
            node = nm.get(nid, {})
            for c in node.get("children", []):
                targets.append(c)
                collect(c)
        collect(self.collection_name)
        for t in targets:
            c = safe_get_collection(arm, t)
            if c:
                for b in c.bones: select_bone(arm_obj, b)
        limited_redraw()
        return {'FINISHED'}

class RRUG_OT_vis_toggle(bpy.types.Operator, RRUG_OperatorMixin):
    bl_idname = "rrug_ui.vis_toggle"
    bl_label = "Vis"
    _metadata_key = "VIS"
    bl_options = {'UNDO'}
    collection_name: bpy.props.StringProperty()

    def execute(self, ctx):
        c = safe_get_collection(ctx.active_object.data, self.collection_name)
        if c: c.is_visible = not c.is_visible; limited_redraw()
        return {'FINISHED'}

class RRUG_OT_vis_show_all(bpy.types.Operator, RRUG_OperatorMixin):
    bl_idname = "rrug_ui.vis_show_all"
    bl_label = "Show All"
    _metadata_key = "VIS_SHOW_ALL"
    bl_options = {'UNDO'}

    def execute(self, context):
        arm = context.object.data
        # Access the cached UI structure
        ui_data = update_and_get_master_tree_data(arm)
        nm = ui_data.get("node_map", {})
        
        # Iterate through all known nodes
        for node_id, node in nm.items():
            # Only affect collections in the DISPLAYS hierarchy
            if node.get("tree_type") == CTX_VIS:
                c = safe_get_collection(arm, node_id)
                if c:
                    c.is_visible = True
                    
        limited_redraw()
        return {'FINISHED'}

class RRUG_OT_vis_unsolo_all(bpy.types.Operator, RRUG_OperatorMixin):
    bl_idname = "rrug_ui.vis_unsolo_all"
    bl_label = "Unsolo All"
    _metadata_key = "VIS_UNSOLO_ALL"
    bl_options = {'UNDO'}

    def execute(self, context):
        arm = context.object.data
        # Iterate all collections in the armature and disable solo
        for coll in arm.collections_all:
            if coll.is_solo:
                coll.is_solo = False
        
        # Force a refresh of the internal cache state to prevent lag
        rrug_ui_timer_update()
        limited_redraw()
        return {'FINISHED'}

class RRUG_OT_solo_toggle(bpy.types.Operator, RRUG_OperatorMixin):
    bl_idname = "rrug_ui.solo_toggle"
    bl_label = "Solo"
    _metadata_key = "SOLO"
    bl_options = {'UNDO'}
    collection_name: bpy.props.StringProperty()

    def execute(self, ctx):
        arm = ctx.active_object.data
        c = safe_get_collection(arm, self.collection_name)
        if c:
            _cascade_solo_state(arm, update_and_get_master_tree_data(arm), self.collection_name, not c.is_solo)
            limited_redraw()
        return {'FINISHED'}

class RRUG_OT_prop_symmetrize(bpy.types.Operator, RRUG_OperatorMixin):
    bl_idname = "rrug_ui.prop_symmetrize" 
    bl_label = "Symmetrize"               
    _metadata_key = "SYM"                 
    bl_options = {'UNDO'}
    
    sync_left_to_right: bpy.props.BoolProperty()
    l_name: bpy.props.StringProperty()
    r_name: bpy.props.StringProperty()

    def execute(self, ctx):
        arm = ctx.active_object.data
        l, r = safe_get_collection(arm, self.l_name), safe_get_collection(arm, self.r_name)
        if l and r:
            # Logic remains the same (Direct Copy), but name implies symmetry now
            src, tgt = (l, r) if self.sync_left_to_right else (r, l)
            for k in src.keys():
                if k != "_RNA_UI" and k in tgt: tgt[k] = src[k]
        ctx.active_object.update_tag(); limited_redraw()
        return {'FINISHED'}

class RRUG_OT_prop_symmetrize_all(bpy.types.Operator, RRUG_OperatorMixin):
    bl_idname = "rrug_ui.prop_symmetrize_all" 
    bl_label = "Symmetrize All"               
    _metadata_key = "SYM_ALL"                 
    bl_options = {'UNDO'}
    
    sync_left_to_right: bpy.props.BoolProperty()

    def execute(self, ctx):
        arm = ctx.active_object.data
        nm = update_and_get_master_tree_data(arm).get("node_map", {})
        for name, node in nm.items():
            meta = node.get("link_meta")
            if meta and meta.get("is_source"):
                l, r = safe_get_collection(arm, name), safe_get_collection(arm, meta.get("partner"))
                if l and r:
                    src, tgt = (l, r) if self.sync_left_to_right else (r, l)
                    for k in src.keys():
                        if k != "_RNA_UI" and k in tgt: tgt[k] = src[k]
        ctx.active_object.update_tag(); limited_redraw()
        return {'FINISHED'}

class RRUG_OT_reset(bpy.types.Operator, RRUG_OperatorMixin):
    bl_idname = "rrug_ui.reset"
    bl_label = "Reset"
    _metadata_key = "RESET"
    bl_options = {'UNDO'}
    collection_name: bpy.props.StringProperty()

    def execute(self, ctx):
        arm = ctx.active_object.data
        # 1. Get the UI structure
        ui_data = update_and_get_master_tree_data(arm)
        nm = ui_data.get("node_map", {})
        # 2. Collect the target and ALL its descendants
        targets = [self.collection_name]
        def collect_children(node_id):
            node = nm.get(node_id)
            if node:
                for child_id in node.get("children", []):
                    targets.append(child_id)
                    collect_children(child_id)
        # Start the recursive collection
        collect_children(self.collection_name)
        # 3. Iterate through EVERY collection found and reset
        did_reset = False
        for t_name in targets:
            c = safe_get_collection(arm, t_name)
            if c:
                for k in c.keys():
                    if k != "_RNA_UI":
                        # Safely try to get the default value
                        try:
                            prop_ui = c.id_properties_ui(k).as_dict()
                            default_val = prop_ui.get("default")
                            if default_val is not None:
                                c[k] = default_val
                                did_reset = True
                        except Exception:
                            # Skip keys that might not have UI data definition
                            pass
        if did_reset:
            ctx.active_object.update_tag()
            limited_redraw()
            self.report({'INFO'}, f"Reset properties for {len(targets)} collections.")
        return {'FINISHED'}

class RRUG_OT_dummy(bpy.types.Operator, RRUG_OperatorMixin):
    bl_idname = "rrug_ui.dummy"
    bl_label = ""
    bl_options = {'INTERNAL'}
    _metadata_key = "DUMMY"
    def execute(self, ctx): return {'FINISHED'}

class RRUG_OT_select_from_search(bpy.types.Operator, RRUG_OperatorMixin):
    bl_idname = "rrug_ui.select_from_search"
    bl_label = "Select"
    _metadata_key = "VIS_SELECT"
    bl_options = {'UNDO'}
    def execute(self, context):
        obj = context.object
        arm = obj.data
        query = arm.rrug_vis_search.strip()
        if not query: return {'CANCELLED'}
        target_bone = arm.bones.get(query)
        if target_bone:
            bpy.ops.pose.select_all(action='DESELECT')
            select_bone(obj, target_bone)
            arm.bones.active = target_bone
            return {'FINISHED'}
        self.report({'WARNING'}, f"Bone '{query}' not found")
        return {'CANCELLED'}

class RRUG_OT_clear_search(bpy.types.Operator):
    bl_idname = "rrug_ui.clear_search"
    bl_label = "Clear"
    bl_options = {'INTERNAL'}
    prop_name: bpy.props.StringProperty()
    def execute(self, context):
        arm = context.object.data
        if self.prop_name == "rrug_vis_search":
            arm.rrug_vis_is_filtered = False
        setattr(arm, self.prop_name, "")
        return {'FINISHED'}

class RRUG_PT_auto_key_popover(bpy.types.Panel):
    bl_label = "Auto Keying Settings"
    bl_idname = "RRUG_PT_auto_key_popover"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'
    
    def draw(self, context):
        layout = self.layout
        ts = context.scene.tool_settings
        layout.prop(ts, "auto_keying_mode", expand=True)
        layout.prop(ts, "use_keyframe_insert_keyingset", text="Only Active Keying Set")
        layout.prop(ts, "use_record_with_nla", text="Layered Recording")      

# ==============================================================================
# SECTION 7: PANELS
# ==============================================================================

class RRUG_PT_Main(bpy.types.Panel):
    bl_idname = "RRUG_PT_Main"
    bl_label = "Reactive Rig UI Generator"
    bl_space_type = UI_SPACE_TYPE
    bl_region_type = UI_REGION_TYPE
    bl_category = UI_CATEGORY
    bl_context = UI_CONTEXT
    bl_order = 0

    @classmethod
    def poll(cls, context):
        # Global Gatekeeper: Only show if in Pose Mode and Rig has RRUG data
        return context.mode == 'POSE' and context.object and context.object.data.get(RRUG_TRIGGER_KEY)

    def draw(self, context):
        pass

class RRUG_PT_Workflow(bpy.types.Panel):
    bl_idname = "RRUG_PT_00_Workflow_Priority"
    bl_label = "Workflow"
    bl_space_type = UI_SPACE_TYPE
    bl_region_type = UI_REGION_TYPE
    bl_context = UI_CONTEXT
    bl_parent_id = "RRUG_PT_Main"
    bl_order = 0

    @classmethod
    def poll(cls, context): 
        return True

    def draw(self, context):
        layout = self.layout
        obj = context.active_object
        arm = obj.data
        scene = context.scene
        tool_settings = scene.tool_settings
        # --- 1. POSE POSITION (TOP) ---
        layout.prop(arm, "pose_position", expand=True)
        layout.separator()
        # --- 2. PLAYBACK RANGE (SEPARATED) ---
        row = layout.row(align=True)
        col_curr = row.column(align=True)
        col_curr.scale_x = 0.8
        col_curr.prop(scene, "frame_current", text="")
        row.separator(factor=2.0)
        range_row = row.row(align=True)
        range_row.prop(scene, "use_preview_range", text="", icon='TIME')
        sub = range_row.row(align=True)
        if scene.use_preview_range:
            sub.prop(scene, "frame_preview_start", text="Start")
            sub.prop(scene, "frame_preview_end", text="End")
        else:
            sub.prop(scene, "frame_start", text="Start")
            sub.prop(scene, "frame_end", text="End")
        layout.separator()
        # --- 3. KEYING & AUTO-KEY ---
        row = layout.row(align=True)
        row.prop(tool_settings, "use_keyframe_insert_auto", text="", toggle=True, icon='RECORD_OFF')
        row.popover(panel="RRUG_PT_auto_key_popover", text="", icon='DOWNARROW_HLT')
        row.prop_search(scene.keying_sets_all, "active", scene, "keying_sets_all", text="")
        row.operator("anim.keyframe_insert_menu", text="", icon='KEY_HLT') 
        layout.separator()
        # --- 4. TRANSFORM RESETS ---
        row = layout.row(align=True)
        split_resets = row.split(factor=0.5, align=True)
        row_sel = split_resets.row(align=True)
        row_sel.alignment = 'CENTER'
        row_sel.label(text="", icon='RESTRICT_SELECT_OFF') 
        for t, i in [('LOC','CON_LOCLIKE'),('ROT','CON_ROTLIKE'),('SCALE','CON_SIZELIKE'),('ALL','LOOP_BACK')]:
            op = row_sel.operator("rrug_ui.reset_pose_transforms", text="", icon=i)
            op.subset = 'SELECTED'
            op.clear_type = t
        row_all = split_resets.row(align=True)
        row_all.alignment = 'CENTER'
        row_all.label(text="", icon='OUTLINER_OB_ARMATURE')
        for t, i in [('LOC','CON_LOCLIKE'),('ROT','CON_ROTLIKE'),('SCALE','CON_SIZELIKE'),('ALL','LOOP_BACK')]:
            op = row_all.operator("rrug_ui.reset_pose_transforms", text="", icon=i)
            op.subset = 'ALL'
            op.clear_type = t
            

class RRUG_PT_Vis(bpy.types.Panel):
    bl_idname = "RRUG_PT_01_Vis_New"
    bl_label = "Visibility"
    bl_space_type = UI_SPACE_TYPE
    bl_region_type = UI_REGION_TYPE
    bl_context = UI_CONTEXT
    bl_parent_id = "RRUG_PT_Main"
    bl_order = 1

    @classmethod
    def poll(cls, context): 
        return True

    def draw(self, context):
        arm = context.object.data
        ui = update_and_get_master_tree_data(arm)
        layout = self.layout
        # 1. Main Container (Align=False allows gaps between groups)
        row = layout.row(align=False)
        # --- GROUP 1: Search & Filter ---
        sub_left = row.row(align=True)
        sub_left.operator("rrug_ui.get_active_bone_to_search", text="", icon='EYEDROPPER')
        sub_left.prop(arm, "rrug_vis_search", text="", icon='VIEWZOOM')
        sub_select = sub_left.row(align=True)
        sub_select.enabled = bool(arm.rrug_vis_search)
        sub_select.operator("rrug_ui.select_from_search", text="", icon='RESTRICT_SELECT_OFF')
        sub_left.prop(arm, "rrug_vis_is_filtered", text="", toggle=True, icon='OUTLINER_COLLECTION')
        # --- SEPARATION 1 ---
        row.separator(factor=0.4)
        # --- GROUP 2: Global Vis Actions ---
        sub_right = row.row(align=True)
        sub_right.operator("rrug_ui.vis_show_all", text="", icon='HIDE_OFF')
        sub_right.operator("rrug_ui.vis_unsolo_all", text="", icon='SOLO_OFF')
        # --- GROUP 3: Expand/Collapse ---
        if not (arm.rrug_vis_search and arm.rrug_vis_is_filtered):
            # --- SEPARATION 2 ---
            row.separator(factor=0.4)
            _draw_expand_buttons(row, 'VIS')
        layout.separator()
        if arm.rrug_vis_search and arm.rrug_vis_is_filtered:
            draw_vis_filtered(layout, arm, ui, arm.rrug_vis_search)
        else:
            col = layout.column(align=True)
            for g in ui.get('vis_display', []):
                if isinstance(g, list):
                    if len(g) == 1:
                        draw_vis_recursive(col, arm, g[0], ui, 0)
                    else:
                        s = col.row(align=True).split(factor=1.0 / len(g), align=True)
                        for k, i in enumerate(g):
                            draw_vis_recursive(s, arm, i, ui, 0)
                            if k < len(g) - 1:
                                s = s.split(factor=1.0 / (len(g) - (k + 1)), align=True)

class RRUG_PT_Props(bpy.types.Panel):
    bl_idname = "RRUG_PT_02_Props_New"
    bl_label = "Properties"
    bl_space_type = UI_SPACE_TYPE
    bl_region_type = UI_REGION_TYPE
    bl_context = UI_CONTEXT
    bl_parent_id = "RRUG_PT_Main"
    bl_order = 2

    @classmethod
    def poll(cls, context): 
        # Check if settings exist (Parent already checked for Pose Mode)
        ui = update_and_get_master_tree_data(context.object.data)
        return ui.get("found_settings", False)

    def draw(self, context):
        arm = context.object.data
        ui = update_and_get_master_tree_data(arm)
        layout = self.layout
        row = layout.row(align=True)
        row.prop(arm, "rrug_prop_search", text="", icon='VIEWZOOM')
        # Only show expand/collapse buttons if search is inactive
        if not arm.rrug_prop_search:
            _draw_expand_buttons(row, 'PROPS')
        layout.separator()
        if arm.rrug_prop_search:
            draw_props_filtered(layout, arm, ui, arm.rrug_prop_search)
        else:   
            if ui.get('has_links'):
                box = layout.box()
                row = box.row(align=True)
                s = row.split(factor=0.333, align=True)
                s.operator("rrug_ui.prop_symmetrize_all", text="", icon='TRIA_RIGHT').sync_left_to_right = True
                s = s.split(factor=0.5, align=True)
                s.operator("rrug_ui.dummy", text="Symmetrize", depress=True)
                s.operator("rrug_ui.prop_symmetrize_all", text="", icon='TRIA_LEFT').sync_left_to_right = False
                layout.separator()
            col = layout.column(align=True)
            for g in ui.get('props_others', []):
                if isinstance(g, list):
                    if len(g) == 1:
                        draw_props_recursive(col, arm, g[0], ui)
                    else:
                        s = col.row(align=True).split(factor=1.0 / len(g), align=True)
                        for k, i in enumerate(g):
                            draw_props_recursive(s, arm, i, ui)
                            if k < len(g) - 1:
                                s = s.split(factor=1.0 / (len(g) - (k + 1)), align=True)

class RRUG_PT_Snap(bpy.types.Panel):
    bl_idname = "RRUG_PT_03_Snap_New"
    bl_label = "Snapping"
    bl_space_type = UI_SPACE_TYPE
    bl_region_type = UI_REGION_TYPE
    bl_context = UI_CONTEXT
    bl_parent_id = "RRUG_PT_Main"
    bl_order = 3

    @classmethod
    def poll(cls, context):
        # Check if snaps exist (Parent already checked for Pose Mode)
        ui = update_and_get_master_tree_data(context.object.data)
        return bool(ui.get("snap_layout"))

    def draw(self, context):
        arm = context.object.data
        ui = update_and_get_master_tree_data(arm)
        layout = self.layout
        # --- Row 1: Search and Global Expansion ---
        row = layout.row(align=True)
        row.prop(arm, "rrug_snap_search", text="", icon='VIEWZOOM')
        if arm.rrug_snap_search:
            op = row.operator("rrug_ui.clear_search", text="", icon='X')
            op.prop_name = "rrug_snap_search"
        else:
            _draw_expand_buttons(row, 'SNAP')
        layout.separator()
        if arm.rrug_snap_search:
            draw_snap_filtered(layout, arm, ui, arm.rrug_snap_search)
        else:
            # --- Row 2: Alignment to the Right ---
            # Create a row and use alignment='RIGHT' to push all children to the right side
            row_utils = layout.row(align=True)
            row_utils.alignment = 'RIGHT'
            # 1. Cursor Rotation Popover
            row_utils.popover(panel="RRUG_PT_cursor_rotation_popover", text="", icon='ORIENTATION_GIMBAL')
            row_utils.separator(factor=0.5) 
            # 2. Cursor -> Selection Group
            grp_cur = row_utils.row(align=True)
            grp_cur.label(text="", icon='CURSOR')
            for a, i in [('CURS_TO_SEL_LOC','CON_LOCLIKE'),('CURS_TO_SEL_ROT','CON_ROTLIKE'),('CURS_TO_SEL_ALL','SNAP_ON')]:
                grp_cur.operator("rrug_ui.snap_cursor_utils", text="", icon=i).action = a
            row_utils.separator(factor=1.0)
            # 3. Selection -> Cursor Group
            grp_sel = row_utils.row(align=True)
            grp_sel.label(text="", icon='SNAP_PEEL_OBJECT') 
            for a, i in [('SEL_TO_CURS_LOC','CON_LOCLIKE'),('SEL_TO_CURS_ROT','CON_ROTLIKE'),('SEL_TO_CURS_ALL','SNAP_ON')]:
                grp_sel.operator("rrug_ui.snap_cursor_utils", text="", icon=i).action = a
            # 4. Spacing between Cursor Utils and Settings
            row_utils.separator(factor=2.0)
            # 5. Snap Settings (Auto Key and Mirror)
            grp_set = row_utils.row(align=True)
            grp_set.prop(arm, "rrug_auto_key", text="", icon='RECORD_ON' if arm.rrug_auto_key else 'RECORD_OFF', toggle=True)
            grp_set.prop(arm, "rrug_snap_mirror", text="", icon='MOD_MIRROR', toggle=True)
            layout.separator()
            # --- Row 3+: Snap Groups ---
            col = layout.column(align=True)
            for g in ui["snap_layout"]:
                if isinstance(g, list):
                    if len(g) == 1:
                        draw_snap_recursive(col, arm, g[0], ui)
                    else:
                        s = col.row(align=True).split(factor=1.0 / len(g), align=True)
                        for k, i in enumerate(g):
                            draw_snap_recursive(s, arm, i, ui)
                            if k < len(g) - 1:
                                s = s.split(factor=1.0 / (len(g) - (k + 1)), align=True)

class RRUG_PT_cursor_rotation_popover(bpy.types.Panel):
    bl_label = "Cursor Rotation"
    bl_idname = "RRUG_PT_cursor_rotation_popover"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW' 
    
    def draw(self, context):
        layout = self.layout
        cursor = context.scene.cursor
        rot_mode = cursor.rotation_mode
        layout.label(text=f"Mode: {rot_mode.replace('_', ' ').title()}", icon='ORIENTATION_GIMBAL')
        layout.separator()
        if rot_mode == 'QUATERNION':
            data_path = "rotation_quaternion"; components = [0, 1, 2, 3]; labels = ["W", "X", "Y", "Z"]
        elif rot_mode == 'AXIS_ANGLE':
            data_path = "rotation_axis_angle"; components = [0, 1, 2, 3]; labels = ["W", "X", "Y", "Z"]
        else:
            data_path = "rotation_euler"; components = [0, 1, 2]; labels = ["X", "Y", "Z"]
        for i, char in zip(components, labels):
            row = layout.row(align=True)
            row.prop(cursor, data_path, index=i, text=char)
            op = row.operator("rrug_ui.zero_cursor_axis", text="", icon='LOOP_BACK')
            op.axis = i
# ==============================================================================
# SECTION 8: REGISTRATION
# ==============================================================================

_CLASSES = (
    RRUG_PT_Main,
    RRUG_OT_reset_pose_transforms,
    RRUG_OT_expand_all,
    RRUG_OT_snap_hierarchy_batch,
    RRUG_OT_snap_cursor_utils,
    RRUG_OT_zero_cursor_axis,
    RRUG_PT_cursor_rotation_popover,
    RRUG_PT_auto_key_popover,
    RRUG_OT_select_replace,
    RRUG_OT_select_add,
    RRUG_OT_vis_toggle,
    RRUG_OT_vis_show_all,
    RRUG_OT_vis_unsolo_all,
    RRUG_OT_solo_toggle,
    RRUG_OT_prop_symmetrize,
    RRUG_OT_prop_symmetrize_all,
    RRUG_OT_reset,
    RRUG_OT_dummy,
    RRUG_OT_get_active_bone_to_search,
    RRUG_OT_select_from_search,
    RRUG_OT_clear_search,
    RRUG_PT_Workflow,
    RRUG_PT_Vis,
    RRUG_PT_Props,
    RRUG_PT_Snap
)

def register():
    # Properties
    bpy.types.Armature.rrug_vis_search = bpy.props.StringProperty(
        name="Search Bone", 
        search=_get_vis_candidates, 
        description=_TIPS["VIS_SEARCH"][1]
    )
    bpy.types.Armature.rrug_prop_search = bpy.props.StringProperty(
        name="Filter Settings", search=_get_prop_candidates, update=_update_prop_search, description="Filter Properties"
    )
    bpy.types.Armature.rrug_snap_search = bpy.props.StringProperty(
        name="Filter Snaps", search=_get_snap_candidates, update=_update_snap_search, description="Filter Snap Groups"
    )
    bpy.types.Armature.rrug_vis_is_filtered = bpy.props.BoolProperty(
        name="Isolate Search",
        default=False,
        description=_TIPS["VIS_ISOLATE"][1]
    )
    bpy.types.Armature.rrug_auto_key = bpy.props.BoolProperty(name="Auto Key", default=False)
    bpy.types.Armature.rrug_snap_mirror = bpy.props.BoolProperty(
        name="Mirror Snap", description="Mirror the snap action to the opposite side", default=False
    )
    # Classes
    for c in _CLASSES:
        bpy.utils.register_class(c)
    # App State
    if not bpy.app.timers.is_registered(rrug_ui_timer_update):
        bpy.app.timers.register(rrug_ui_timer_update, first_interval=0.25, persistent=True)
    if rrug_ui_load_handler not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(rrug_ui_load_handler)

def unregister():
    purge_rrug_cache()
    if bpy.app.timers.is_registered(rrug_ui_timer_update):
        bpy.app.timers.unregister(rrug_ui_timer_update)
    load_post = bpy.app.handlers.load_post
    to_remove = [h for h in load_post if h.__name__ == "rrug_ui_load_handler"]
    for h in to_remove: load_post.remove(h)
    # Cleanup Properties
    props = ["rrug_auto_key", "rrug_snap_mirror", "rrug_vis_search", 
             "rrug_prop_search", "rrug_snap_search", "rrug_vis_is_filtered"]
    for p in props:
        if hasattr(bpy.types.Armature, p): delattr(bpy.types.Armature, p)
    for c in reversed(_CLASSES):
        bpy.utils.unregister_class(c)

if __name__ == "__main__":
    import addon_utils
    is_global_active = False
    for mod in addon_utils.modules():
        if hasattr(mod, "bl_info") and mod.bl_info.get("name") == "RRUG UI":
            try:
                if addon_utils.check(mod.__name__)[1]:
                    is_global_active = True; break
            except: pass
    
    if is_global_active:
        print("RRUG Core: Global Addon is active. Embedded engine yielding.")
    else:
        try: unregister()
        except: pass
        register()
        print("RRUG Core: Active")
        print("""
                            ░░                         
                        ░░░░░░░░░░                     
                      ░░░░░░░░░░░░░                    
                    ░░░░░░░▓▓░░░░░░░░                  
                  ░░░░░░░░░▓▓▓▓░░░░░░░                 
                ░░░░░░░░░░░░▓▓▓▓▓░░░░░░░               
               ░░░░░░░░░░░░░░░▓▓▓░░░░░░░               
             ░░░░░▓▓▓░░░░░░░░░░░░░░░░░░░░              
            ░░░░░▓▓▓▓░░░░░▓▓▓▓░░░░░░░░░░░░░            
          ░░░░░░▓▓▓▓░░░░▓▓▓▓▓░░░░░░░░░░░░░░            
         ░░░░░░▓▓▓▓░░░░░▓▓▓▓░░░░░░▓▓▓░░░░░░░           
       ░░░░░░░▓▓▓░░░░░░░▓▓▓░░░░░░░▓▓▓▓▓░░░░░░░░        
      ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░▓▓▓▓▓▓░░░░░░░░      
      ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░     
       ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░      
         ░░░░░░░░░░░░▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░░░░░░░░░░       
            ░░░░░░░▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░░░░            
                     ▓▓▓▓▓▓▓▓▓▓                        
                     ▓▓▓▓▓▓▓▓▓▓                        
                     ▓▓▓▓▓▓▓▓▓▓                        
                     ▓▓▓▓▓▓▓▓▓▓                        
                    ▓▓▓▓▓▓▓▓▓▓▓▓                       
                   ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓                    
                 ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓                  
                 ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓                  
                  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓                    """)