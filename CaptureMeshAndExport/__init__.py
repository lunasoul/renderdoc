###############################################################################
# CaptureMeshAndExport Extension
#
# This extension captures mesh data from the current event using RenderDoc API
# and exports it to FBX format, following the official decode_mesh example.
###############################################################################

import qrenderdoc as qrd
import renderdoc as rd
import struct
import os

extiface_version = ''


# MeshData class based on MeshFormat, with additional properties
class MeshData(rd.MeshFormat):
    indexOffset = 0
    name = ''
    systemValue = rd.ShaderBuiltin.Undefined  # Store systemValue to distinguish POSITION from SV_POSITION


def unpackData(fmt, data):
    """Unpack data from bytes using ResourceFormat, following official example"""
    # We don't handle 'special' formats - typically bit-packed such as 10:10:10:2
    if fmt.Special():
        raise RuntimeError("Packed formats are not supported!")

    formatChars = {}
    #                                 012345678
    formatChars[rd.CompType.UInt]  = "xBHxIxxxL"
    formatChars[rd.CompType.SInt]  = "xbhxixxxl"
    formatChars[rd.CompType.Float] = "xxexfxxxd"  # only 2, 4 and 8 are valid

    # These types have identical decodes, but we might post-process them
    formatChars[rd.CompType.UNorm] = formatChars[rd.CompType.UInt]
    formatChars[rd.CompType.UScaled] = formatChars[rd.CompType.UInt]
    formatChars[rd.CompType.SNorm] = formatChars[rd.CompType.SInt]
    formatChars[rd.CompType.SScaled] = formatChars[rd.CompType.SInt]

    # We need to fetch compCount components
    vertexFormat = str(fmt.compCount) + formatChars[fmt.compType][fmt.compByteWidth]

    # Unpack the data
    value = struct.unpack_from(vertexFormat, data, 0)

    # If the format needs post-processing such as normalisation, do that now
    if fmt.compType == rd.CompType.UNorm:
        divisor = float((2 ** (fmt.compByteWidth * 8)) - 1)
        value = tuple(float(i) / divisor for i in value)
    elif fmt.compType == rd.CompType.SNorm:
        maxNeg = -float(2 ** (fmt.compByteWidth * 8)) / 2
        divisor = float(-(maxNeg-1))
        value = tuple((float(i) if (i == maxNeg) else (float(i) / divisor)) for i in value)

    # If the format is BGRA, swap the two components
    if fmt.BGRAOrder():
        value = tuple(value[i] for i in [2, 1, 0, 3])

    return value


def getIndices(controller, mesh, action=None, debug_file=None):
    """Get indices from mesh, following official example
    If action is provided, use action.baseVertex and action.indexOffset instead of mesh values
    """
    def debug_write(msg):
        if debug_file is not None:
            debug_file.write(msg + "\n")
            debug_file.flush()
    
    # Get the character for the width of index
    indexFormat = 'B'
    if mesh.indexByteStride == 2:
        indexFormat = 'H'
    elif mesh.indexByteStride == 4:
        indexFormat = 'I'

    # Duplicate the format by the number of indices
    indexFormat = str(mesh.numIndices) + indexFormat

    # If we have an index buffer
    # Simplified approach like BatchExport: read entire buffer, then unpack from offset
    if mesh.indexResourceId != rd.ResourceId.Null():
        # Use action values if provided, otherwise use mesh values
        base_vertex = action.baseVertex if action is not None else mesh.baseVertex
        index_offset = action.indexOffset if action is not None else mesh.indexOffset
        
        # Fetch the entire index buffer data (simplified like BatchExport)
        ibdata = controller.GetBufferData(mesh.indexResourceId, mesh.indexByteOffset, 0)
        debug_write("Fetched {} bytes from index buffer (starting from byteOffset={})".format(
            len(ibdata), mesh.indexByteOffset))
        
        # Unpack all indices, starting from the first index to fetch
        offset = index_offset * mesh.indexByteStride
        debug_write("Using baseVertex={}, indexOffset={}, offset in buffer={}".format(
            base_vertex, index_offset, offset))
        
        try:
            indices = struct.unpack_from(indexFormat, ibdata, offset)
            # Apply the baseVertex offset
            result = [i + base_vertex for i in indices]
            debug_write("First 5 raw indices (before baseVertex): {}".format(list(indices[:5])))
            debug_write("First 5 indices (after baseVertex): {}".format(result[:5]))
            return result
        except struct.error as e:
            debug_write("WARNING: Failed to unpack indices: {}. Buffer size: {}, offset: {}, required: {}".format(
                str(e), len(ibdata), offset, offset + mesh.indexByteStride * mesh.numIndices))
            # Fallback: try to read what we can
            result = []
            index_fmt = '=' + indexFormat[-1]  # Get format char (H, I, or B)
            for i in range(mesh.numIndices):
                idx_offset = offset + i * mesh.indexByteStride
                if idx_offset + mesh.indexByteStride <= len(ibdata):
                    idx = struct.unpack_from(index_fmt, ibdata, idx_offset)[0]
                    result.append(idx + base_vertex)
                else:
                    debug_write("WARNING: Not enough data for index {}, using fallback".format(i))
                    result.append(i + base_vertex)
            return result
    else:
        # With no index buffer, just generate a range
        debug_write("No index buffer, generating range 0-{}".format(mesh.numIndices - 1))
        return tuple(range(mesh.numIndices))


def getMeshOutputs(controller, postvs):
    """Get mesh outputs configuration, following official example"""
    meshOutputs = []
    posidx = 0

    vs = controller.GetPipelineState().GetShaderReflection(rd.ShaderStage.Vertex)
    if vs is None:
        return meshOutputs

    # Repeat the process, but this time sourcing the data from postvs.
    # Since these are outputs, we iterate over the list of outputs from the
    # vertex shader's reflection data
    pipe = controller.GetPipelineState()
    
    for attr in vs.outputSignature:
        # Skip if not on rasterized stream (like mesh_attribute_printer does)
        if pipe.GetRasterizedStream() >= 0:
            if attr.stream != pipe.GetRasterizedStream():
                continue
        else:
            if attr.stream != 0:
                continue
        
        # Skip output indices (like mesh_attribute_printer does)
        if attr.systemValue == rd.ShaderBuiltin.OutputIndices:
            continue
        
        # Copy most properties from the postvs struct
        meshOutput = MeshData()
        meshOutput.indexResourceId = postvs.indexResourceId
        meshOutput.indexByteOffset = postvs.indexByteOffset
        meshOutput.indexByteStride = postvs.indexByteStride
        meshOutput.baseVertex = postvs.baseVertex
        meshOutput.indexOffset = 0
        meshOutput.numIndices = postvs.numIndices

        # The total offset is the attribute offset from the base of the vertex,
        # as calculated by the stride per index
        meshOutput.vertexByteOffset = postvs.vertexByteOffset
        meshOutput.vertexResourceId = postvs.vertexResourceId
        meshOutput.vertexByteStride = postvs.vertexByteStride

        # Construct a resource format for this element
        meshOutput.format = rd.ResourceFormat()
        meshOutput.format.compByteWidth = rd.VarTypeByteSize(attr.varType)
        meshOutput.format.compCount = attr.compCount
        meshOutput.format.compType = rd.VarTypeCompType(attr.varType)
        meshOutput.format.type = rd.ResourceFormatType.Regular

        meshOutput.name = attr.semanticIdxName if attr.varName == '' else attr.varName
        meshOutput.systemValue = attr.systemValue  # Store systemValue to distinguish POSITION from SV_POSITION

        if attr.systemValue == rd.ShaderBuiltin.Position:
            posidx = len(meshOutputs)

        meshOutputs.append(meshOutput)
    
    # Shuffle the position element to the front
    if posidx > 0:
        pos = meshOutputs[posidx]
        del meshOutputs[posidx]
        meshOutputs.insert(0, pos)

    accumOffset = 0

    for i in range(0, len(meshOutputs)):
        meshOutputs[i].vertexByteOffset = accumOffset

        # Note that some APIs such as Vulkan will pad the size of the attribute here
        # while others will tightly pack
        fmt = meshOutputs[i].format

        accumOffset += (8 if fmt.compByteWidth > 4 else 4) * fmt.compCount

    return meshOutputs


def showAttributeMappingDialog(ctx, inputs):
    """Show attribute mapping dialog and return user's mapping choices
    
    Args:
        ctx: CaptureContext instance
        inputs: List of VertexInput attributes from VS Input
    
    Returns:
        Dictionary mapping attribute names to selected VS Input attribute names, or None if cancelled
        Format: {'position': 'ATTRIBUTE0', 'normal': 'ATTRIBUTE2', 'tangent': 'ATTRIBUTE1', 'uv': 'ATTRIBUTE5'}
    """
    mqt = ctx.Extensions().GetMiniQtHelper()
    
    # Create dialog widget
    dialog_widget = mqt.CreateToplevelWidget("Attribute Mapping", None)
    dialog_widget.setWindowTitle("Attribute Mapping")
    
    # Create main vertical container
    main_container = mqt.CreateVerticalContainer()
    mqt.AddWidget(dialog_widget, main_container)
    
    # Get available VS Input attributes (non-instance attributes)
    available_attrs = []
    for attr in inputs:
        if not attr.perInstance:
            attr_display = "{} ({} components)".format(attr.name, attr.format.compCount)
            available_attrs.append((attr.name, attr_display))
    
    if len(available_attrs) == 0:
        ctx.Extensions().ErrorDialog("No vertex attributes found in VS Input", "Attribute Mapping Error")
        return None
    
    # Create attribute options list (including "None" option)
    attr_options = ["None"]
    attr_name_map = {"None": None}  # Map display name to actual attribute name
    for attr_name, attr_display in available_attrs:
        attr_options.append(attr_display)
        attr_name_map[attr_display] = attr_name
    
    # Store combo boxes and their selected values for later retrieval
    combo_boxes = {}
    combo_selected_values = {}  # Track selected values for each combo
    
    # Define attribute mappings to show
    attribute_mappings = [
        ("position", "Vertex Position", True, 3),  # (key, label, required, min_components)
        ("normal", "Vertex Normal", False, 3),
        ("tangent", "Vertex Tangent", False, 3),
        ("uv", "UV", False, 2),
    ]
    
    # Create mapping rows
    for key, label, required, min_components in attribute_mappings:
        # Create horizontal container for label and combo
        row = mqt.CreateHorizontalContainer()
        mqt.AddWidget(main_container, row)
        
        # Create label
        label_widget = mqt.CreateLabel()
        mqt.SetWidgetText(label_widget, label + ("" if not required else " *"))
        mqt.AddWidget(row, label_widget)
        
        # Create combo box with callback to track selected value
        def make_combo_changed(key=key):
            def combo_changed(ctx, widget, data):
                # data contains the selected text
                combo_selected_values[key] = data
            return combo_changed
        
        combo = mqt.CreateComboBox(False, make_combo_changed(key))
        mqt.SetComboOptions(combo, attr_options)
        
        # Set default selection based on common patterns
        default_attr = None
        if key == "position":
            # Try to find ATTRIBUTE0
            for attr_name, attr_display in available_attrs:
                if attr_name.upper() == "ATTRIBUTE0":
                    default_attr = attr_display
                    break
        elif key == "normal":
            # Try to find ATTRIBUTE2
            for attr_name, attr_display in available_attrs:
                if attr_name.upper() == "ATTRIBUTE2":
                    default_attr = attr_display
                    break
        elif key == "tangent":
            # Try to find ATTRIBUTE1
            for attr_name, attr_display in available_attrs:
                if attr_name.upper() == "ATTRIBUTE1":
                    default_attr = attr_display
                    break
        elif key == "uv":
            # Try to find ATTRIBUTE5
            for attr_name, attr_display in available_attrs:
                if attr_name.upper() == "ATTRIBUTE5":
                    default_attr = attr_display
                    break
        
        if default_attr:
            mqt.SelectComboOption(combo, default_attr)
            combo_selected_values[key] = default_attr  # Initialize selected value
        elif required:
            # For required attributes, select first non-None option
            if len(attr_options) > 1:
                mqt.SelectComboOption(combo, attr_options[1])
                combo_selected_values[key] = attr_options[1]  # Initialize selected value
        else:
            # Initialize with "None" for optional attributes
            combo_selected_values[key] = "None"
        
        mqt.AddWidget(row, combo)
        combo_boxes[key] = combo
    
    # Dialog result storage (use list to allow modification in nested functions)
    dialog_result = [True, {}]  # [cancelled, mapping]
    
    # Set up button callbacks
    def on_cancel(ctx, widget, data):
        dialog_result[0] = True
        mqt.CloseCurrentDialog(False)
    
    def on_export(ctx, widget, data):
        # Validate required attributes
        mapping = {}
        for key, label, required, min_components in attribute_mappings:
            # Get selected text from tracked values (set by combo callback)
            selected_text = combo_selected_values.get(key, "None")
            if selected_text == "None":
                if required:
                    ctx.Extensions().ErrorDialog(
                        "{} is required. Please select an attribute.".format(label),
                        "Attribute Mapping Error"
                    )
                    return
                mapping[key] = None
            else:
                attr_name = attr_name_map.get(selected_text)
                if attr_name:
                    # Verify component count
                    for attr in inputs:
                        if attr.name == attr_name and attr.format.compCount < min_components:
                            ctx.Extensions().ErrorDialog(
                                "{} requires at least {} components, but {} has only {}.".format(
                                    label, min_components, attr_name, attr.format.compCount
                                ),
                                "Attribute Mapping Error"
                            )
                            return
                    mapping[key] = attr_name
                else:
                    mapping[key] = None
        
        dialog_result[0] = False
        dialog_result[1] = mapping
        mqt.CloseCurrentDialog(True)
    
    # Create button container
    button_container = mqt.CreateHorizontalContainer()
    mqt.AddWidget(main_container, button_container)
    
    # Create Cancel button with callback
    cancel_button = mqt.CreateButton(on_cancel)
    mqt.SetWidgetText(cancel_button, "Cancel")
    
    # Create Export button with callback
    export_button = mqt.CreateButton(on_export)
    mqt.SetWidgetText(export_button, "Export")
    
    mqt.AddWidget(button_container, cancel_button)
    mqt.AddWidget(button_container, export_button)
    
    # Show dialog
    if mqt.ShowWidgetAsDialog(dialog_widget):
        if not dialog_result[0]:  # Not cancelled
            return dialog_result[1]  # Return mapping
    
    return None


def extractMeshData(controller, meshData, action=None, attribute_mapping=None, debug_file=None):
    """Extract vertex positions, indices, UVs, normals, and tangents from VS Input
    Following BatchExport approach: all data from VS Input, not VS Output
    
    Args:
        controller: ReplayController instance
        meshData: List of MeshData objects from VS Output (used for index buffer info)
        action: ActionDescription (required to read VS Input data)
        attribute_mapping: Dictionary mapping attribute names to VS Input attribute names
                         Format: {'position': 'ATTRIBUTE0', 'normal': 'ATTRIBUTE2', 'tangent': 'ATTRIBUTE1', 'uv': 'ATTRIBUTE5'}
                         If None, uses default hardcoded mapping
        debug_file: File handle for writing debug information (optional)
    """
    def debug_write(msg):
        """Write debug message to file if provided"""
        if debug_file is not None:
            debug_file.write(msg + "\n")
            debug_file.flush()
    
    debug_write("=" * 60)
    debug_write("CaptureMeshAndExport: Extracting mesh data from VS Input")
    debug_write("Following BatchExport approach: all attributes from VS Input")
    
    if action is None:
        raise RuntimeError("Action is required to read VS Input data")
    
    # Get VS Input information
    pipe = controller.GetPipelineState()
    vbs = pipe.GetVBuffers()
    inputs = pipe.GetVertexInputs()
    ib = pipe.GetIBuffer()
    
    # Create MeshData-like structure for index buffer (like BatchExport)
    class MeshInput:
        def __init__(self):
            self.indexResourceId = ib.resourceId
            self.indexByteOffset = ib.byteOffset
            self.indexByteStride = ib.byteStride
            self.baseVertex = action.baseVertex
            self.indexOffset = action.indexOffset
            self.numIndices = action.numIndices
    
    mesh_input = MeshInput()
    
    # Get indices using simplified method
    indices = getIndices(controller, mesh_input, action, debug_file)
    debug_write("Number of indices: {}".format(len(indices)))
    
    if len(indices) == 0:
        debug_write("WARNING: No indices found!")
        return [], [], [], [], []
    
    # Find all VS Input attributes we need (like BatchExport)
    # Use attribute_mapping if provided, otherwise use default hardcoded mapping
    if attribute_mapping is None:
        # Default hardcoded mapping
        attribute_mapping = {
            'position': 'ATTRIBUTE0',
            'normal': 'ATTRIBUTE2',
            'tangent': 'ATTRIBUTE1',
            'uv': 'ATTRIBUTE5'
        }
    
    position_attr = None
    uv_attr = None
    normal_attr = None
    tangent_attr = None
    
    debug_write("\nScanning VS Input attributes...")
    debug_write("Using attribute mapping: {}".format(attribute_mapping))
    
    # Build a map of attribute names to attributes
    attr_map = {}
    for attr in inputs:
        if attr.perInstance:
            continue
        
        debug_write("  - {}: compCount={}, vertexBuffer={}, byteOffset={}".format(
            attr.name, attr.format.compCount, attr.vertexBuffer, attr.byteOffset))
        attr_map[attr.name.upper()] = attr
    
    # Find attributes based on mapping
    if attribute_mapping.get('position'):
        attr_name = attribute_mapping['position'].upper()
        if attr_name in attr_map:
            attr = attr_map[attr_name]
            if attr.format.compCount >= 3:
                position_attr = attr
                debug_write("    -> Found POSITION ({})".format(attr.name))
            else:
                debug_write("    -> WARNING: {} has only {} components, need at least 3".format(
                    attr.name, attr.format.compCount))
    
    if attribute_mapping.get('uv'):
        attr_name = attribute_mapping['uv'].upper()
        if attr_name in attr_map:
            attr = attr_map[attr_name]
            if attr.format.compCount >= 2:
                uv_attr = attr
                debug_write("    -> Found UV ({})".format(attr.name))
            else:
                debug_write("    -> WARNING: {} has only {} components, need at least 2".format(
                    attr.name, attr.format.compCount))
    
    if attribute_mapping.get('normal'):
        attr_name = attribute_mapping['normal'].upper()
        if attr_name in attr_map:
            attr = attr_map[attr_name]
            if attr.format.compCount >= 3:
                normal_attr = attr
                debug_write("    -> Found NORMAL ({})".format(attr.name))
            else:
                debug_write("    -> WARNING: {} has only {} components, need at least 3".format(
                    attr.name, attr.format.compCount))
    
    if attribute_mapping.get('tangent'):
        attr_name = attribute_mapping['tangent'].upper()
        if attr_name in attr_map:
            attr = attr_map[attr_name]
            if attr.format.compCount >= 3:
                tangent_attr = attr
                debug_write("    -> Found TANGENT ({})".format(attr.name))
            else:
                debug_write("    -> WARNING: {} has only {} components, need at least 3".format(
                    attr.name, attr.format.compCount))
    
    if position_attr is None:
        raise RuntimeError("Could not find position attribute ({}) in VS Input".format(
            attribute_mapping.get('position', 'ATTRIBUTE0')))
    
    # Batch read all vertex buffers (like BatchExport)
    debug_write("\nBatch reading vertex buffers...")
    # Note: indices already include baseVertex
    base_vertex = action.baseVertex
    max_idx = max(indices) if indices else 0
    # Calculate relative indices (without baseVertex) for buffer size calculation
    max_relative_idx = max_idx - base_vertex if max_idx >= base_vertex else 0
    
    # Read position buffer - need to read full buffer to access by idx (like CSV export)
    position_buffer = None
    position_vb = None
    position_offset_base = 0
    if position_attr:
        position_vb = vbs[position_attr.vertexBuffer]
        # Calculate base offset (like CSV export: position_attr.byteOffset + vb.byteOffset)
        position_offset_base = position_attr.byteOffset + position_vb.byteOffset
        # Read full buffer (need max_idx + vertexOffset + 1 to cover all indices)
        max_idx_with_offset = max_idx + action.vertexOffset if indices else 0
        buffer_size = position_offset_base + position_vb.byteStride * (max_idx_with_offset + 1)
        position_buffer = controller.GetBufferData(position_vb.resourceId, 0, buffer_size)
        debug_write("Position buffer: size={}, offset_base={}, max_idx={}, vertexOffset={}".format(
            len(position_buffer), position_offset_base, max_idx, action.vertexOffset))
    
    # Read UV buffer - need to read full buffer to access by idx (like CSV export)
    uv_buffer = None
    uv_vb = None
    uv_offset_base = 0
    if uv_attr:
        uv_vb = vbs[uv_attr.vertexBuffer]
        uv_offset_base = uv_attr.byteOffset + uv_vb.byteOffset
        max_idx_with_offset = max_idx + action.vertexOffset if indices else 0
        buffer_size = uv_offset_base + uv_vb.byteStride * (max_idx_with_offset + 1)
        uv_buffer = controller.GetBufferData(uv_vb.resourceId, 0, buffer_size)
        debug_write("UV buffer: size={}, offset_base={}".format(len(uv_buffer), uv_offset_base))
    
    # Read normal buffer - need to read full buffer to access by idx (like CSV export)
    normal_buffer = None
    normal_vb = None
    normal_offset_base = 0
    if normal_attr:
        normal_vb = vbs[normal_attr.vertexBuffer]
        normal_offset_base = normal_attr.byteOffset + normal_vb.byteOffset
        max_idx_with_offset = max_idx + action.vertexOffset if indices else 0
        buffer_size = normal_offset_base + normal_vb.byteStride * (max_idx_with_offset + 1)
        normal_buffer = controller.GetBufferData(normal_vb.resourceId, 0, buffer_size)
        debug_write("Normal buffer: size={}, offset_base={}".format(len(normal_buffer), normal_offset_base))
    
    # Read tangent buffer - need to read full buffer to access by idx (like CSV export)
    tangent_buffer = None
    tangent_vb = None
    tangent_offset_base = 0
    if tangent_attr:
        tangent_vb = vbs[tangent_attr.vertexBuffer]
        tangent_offset_base = tangent_attr.byteOffset + tangent_vb.byteOffset
        max_idx_with_offset = max_idx + action.vertexOffset if indices else 0
        buffer_size = tangent_offset_base + tangent_vb.byteStride * (max_idx_with_offset + 1)
        tangent_buffer = controller.GetBufferData(tangent_vb.resourceId, 0, buffer_size)
        debug_write("Tangent buffer: size={}, offset_base={}".format(len(tangent_buffer), tangent_offset_base))
    
    # Extract vertex data for each index (like BatchExport)
    debug_write("\nExtracting vertex data for each index...")
    debug_write("baseVertex={}, max_idx={}, max_relative_idx={}".format(base_vertex, max_idx, max_relative_idx))
    vertex_data_by_idx = {}  # Maps IDX -> (position, uv, normal, tangent)
    
    for idx in indices:
        if idx not in vertex_data_by_idx:
            # idx already includes baseVertex
            # Calculate offset like CSV export: position_offset_base + vb.byteStride * (idx + action.vertexOffset)
            if position_buffer and position_vb and position_attr:
                offset_in_buffer = position_offset_base + position_vb.byteStride * (idx + action.vertexOffset)
                if offset_in_buffer + position_attr.format.compByteWidth * position_attr.format.compCount <= len(position_buffer):
                    pos_data = position_buffer[offset_in_buffer:offset_in_buffer + position_attr.format.compByteWidth * position_attr.format.compCount]
                    pos_value = unpackData(position_attr.format, pos_data)
                    pos = (float(pos_value[0]), float(pos_value[1]), float(pos_value[2]) if len(pos_value) > 2 else 0.0)
                else:
                    debug_write("WARNING: Position offset {} out of bounds (buffer size: {}, idx: {}, vertexOffset: {})".format(
                        offset_in_buffer, len(position_buffer), idx, action.vertexOffset))
                    pos = (0.0, 0.0, 0.0)
            else:
                pos = (0.0, 0.0, 0.0)
            
            # Read UV (same offset calculation as position)
            uv = (0.0, 0.0)
            if uv_attr and uv_buffer and uv_vb:
                uv_offset_base = uv_attr.byteOffset + uv_vb.byteOffset
                offset_in_buffer = uv_offset_base + uv_vb.byteStride * (idx + action.vertexOffset)
                if offset_in_buffer + uv_attr.format.compByteWidth * uv_attr.format.compCount <= len(uv_buffer):
                    uv_data_bytes = uv_buffer[offset_in_buffer:offset_in_buffer + uv_attr.format.compByteWidth * uv_attr.format.compCount]
                    uv_value = unpackData(uv_attr.format, uv_data_bytes)
                    uv = (float(uv_value[0]), float(uv_value[1]) if len(uv_value) > 1 else 0.0)
            
            # Read normal (same offset calculation as position)
            normal = (0.0, 0.0, 1.0)
            if normal_attr and normal_buffer and normal_vb:
                normal_offset_base = normal_attr.byteOffset + normal_vb.byteOffset
                offset_in_buffer = normal_offset_base + normal_vb.byteStride * (idx + action.vertexOffset)
                if offset_in_buffer + normal_attr.format.compByteWidth * normal_attr.format.compCount <= len(normal_buffer):
                    normal_data_bytes = normal_buffer[offset_in_buffer:offset_in_buffer + normal_attr.format.compByteWidth * normal_attr.format.compCount]
                    normal_value = unpackData(normal_attr.format, normal_data_bytes)
                    normal = (float(normal_value[0]), float(normal_value[1]), float(normal_value[2]) if len(normal_value) > 2 else 0.0)
            
            # Read tangent (same offset calculation as position)
            tangent = (1.0, 0.0, 0.0)
            if tangent_attr and tangent_buffer and tangent_vb:
                tangent_offset_base = tangent_attr.byteOffset + tangent_vb.byteOffset
                offset_in_buffer = tangent_offset_base + tangent_vb.byteStride * (idx + action.vertexOffset)
                if offset_in_buffer + tangent_attr.format.compByteWidth * tangent_attr.format.compCount <= len(tangent_buffer):
                    tangent_data_bytes = tangent_buffer[offset_in_buffer:offset_in_buffer + tangent_attr.format.compByteWidth * tangent_attr.format.compCount]
                    tangent_value = unpackData(tangent_attr.format, tangent_data_bytes)
                    tangent = (float(tangent_value[0]), float(tangent_value[1]), float(tangent_value[2]) if len(tangent_value) > 2 else 0.0)
            
            vertex_data_by_idx[idx] = (pos, uv, normal, tangent)
    
    # Deduplicate vertices based on position only (not UV)
    # This allows different UVs at the same position (for proper texture mapping)
    vertex_key_to_index = {}
    vertices = []
    normal_data = []
    tangent_data = []
    idx_to_vertex_idx = {}
    
    # Store UV data per polygon vertex (in index order, before deduplication)
    polygon_uv_data = []
    polygon_normal_data = []
    
    debug_write("\nDeduplicating vertices based on position only...")
    debug_write("First 10 indices: {}".format(indices[:10]))
    
    # Use rounded position for key to avoid floating point precision issues
    # Round to 6 decimal places (same as FBX export precision)
    EPSILON = 1e-6
    def make_key(pos):
        return (round(pos[0] / EPSILON) * EPSILON, 
                round(pos[1] / EPSILON) * EPSILON, 
                round(pos[2] / EPSILON) * EPSILON)
    
    for idx in indices:
        pos, uv, normal, tangent = vertex_data_by_idx[idx]
        # Use rounded position as key for deduplication to avoid precision issues
        key = make_key(pos)
        
        if key not in vertex_key_to_index:
            vertex_idx = len(vertices)
            vertices.append(pos)
            normal_data.append(normal)
            tangent_data.append(tangent)
            vertex_key_to_index[key] = vertex_idx
            if len(vertices) <= 5:
                debug_write("  New vertex {}: idx={}, pos={}".format(vertex_idx, idx, pos))
        
        idx_to_vertex_idx[idx] = vertex_key_to_index[key]
        
        # Store UV and normal for each polygon vertex (in index order)
        polygon_uv_data.append(uv)
        polygon_normal_data.append(normal)
    
    debug_write("First 10 polygon indices: {}".format([idx_to_vertex_idx[idx] for idx in indices[:10]]))
    
    # Create polygon indices
    polygon_indices = [idx_to_vertex_idx[idx] for idx in indices]
    
    # Don't reverse triangle winding - keep the original order from indices
    # The indices order from RenderDoc should match the CSV export order
    debug_write("Extraction complete:")
    debug_write("  - Vertices: {}".format(len(vertices)))
    debug_write("  - Polygon indices: {}".format(len(polygon_indices)))
    debug_write("  - Polygon UV data: {}".format(len(polygon_uv_data)))
    debug_write("  - Normal data: {}".format(len(normal_data)))
    debug_write("  - Tangent data: {}".format(len(tangent_data)))
    debug_write("=" * 60)
    
    # Return polygon UV data (one per polygon vertex) instead of deduplicated UV data
    return vertices, polygon_indices, polygon_uv_data, polygon_normal_data, tangent_data


def writeFBX(vertices, polygon_indices, uv_data, normal_data, tangent_data, filepath):
    """Write mesh data to FBX ASCII format"""
    num_vertices = len(vertices)
    num_polygons = len(polygon_indices) // 3  # Assuming triangles
    
    with open(filepath, 'w', encoding='utf-8') as f:
        # FBX Header
        f.write("; FBX 7.4.0 project file\n")
        f.write("; Created by RenderDoc CaptureMeshAndExport Extension\n")
        f.write("; ----------------------------------------------------\n\n")
        
        f.write("FBXHeaderExtension:  {\n")
        f.write("\tFBXHeaderVersion: 1003\n")
        f.write("\tFBXVersion: 7400\n")
        f.write("}\n\n")
        
        # Definitions
        f.write("Definitions:  {\n")
        f.write("\tVersion: 100\n")
        f.write("\tCount: 2\n")
        f.write("\tObjectType: \"Geometry\" {\n")
        f.write("\t\tCount: 1\n")
        f.write("\t\tPropertyTemplate: \"FbxMesh\" {\n")
        f.write("\t\t\tProperties70:  {\n")
        f.write("\t\t\t\tP: \"Color\", \"ColorRGB\", \"Color\", \"\",0.8,0.8,0.8\n")
        f.write("\t\t\t\tP: \"BBoxMin\", \"Vector3D\", \"Vector\", \"\",0,0,0\n")
        f.write("\t\t\t\tP: \"BBoxMax\", \"Vector3D\", \"Vector\", \"\",0,0,0\n")
        f.write("\t\t\t\tP: \"Primary Visibility\", \"bool\", \"\", \"\",1\n")
        f.write("\t\t\t\tP: \"Casts Shadows\", \"bool\", \"\", \"\",1\n")
        f.write("\t\t\t\tP: \"Receive Shadows\", \"bool\", \"\", \"\",1\n")
        f.write("\t\t\t}\n")
        f.write("\t\t}\n")
        f.write("\t}\n")
        f.write("\tObjectType: \"Model\" {\n")
        f.write("\t\tCount: 1\n")
        f.write("\t}\n")
        f.write("}\n\n")
        
        # Objects - Geometry
        f.write("Objects:  {\n")
        f.write("\tGeometry: 1000, \"Geometry::\", \"Mesh\" {\n")
        f.write("\t\tProperties70:  {\n")
        f.write("\t\t\tP: \"Color\", \"ColorRGB\", \"Color\", \"\",0.8,0.8,0.8\n")
        f.write("\t\t}\n")
        
        # Vertices
        f.write("\t\tVertices: *{} {{\n".format(num_vertices * 3))
        f.write("\t\t\ta: ")
        vertex_strs = []
        for v in vertices:
            vertex_strs.append("{:.6f},{:.6f},{:.6f}".format(v[0], v[1], v[2]))
        f.write(",".join(vertex_strs))
        f.write("\n")
        f.write("\t\t}\n")
        
        # Polygon Vertex Indices
        f.write("\t\tPolygonVertexIndex: *{} {{\n".format(len(polygon_indices)))
        f.write("\t\t\ta: ")
        # FBX uses negative indices to mark end of polygon
        # Format: -(idx + 1) to mark end of polygon
        # For triangles, every 3rd index (i % 3 == 2) should be negative
        index_strs = []
        for i, idx in enumerate(polygon_indices):
            if i % 3 == 2:  # Every 3rd index (end of triangle)
                index_strs.append(str(-(idx + 1)))  # FBX format: -(idx + 1)
            else:
                index_strs.append(str(idx))
        f.write(",".join(index_strs))
        f.write("\n")
        f.write("\t\t}\n")
        
        # Edges (empty for now)
        f.write("\t\tEdges: *0 {\n")
        f.write("\t\t\ta: \n")
        f.write("\t\t}\n")
        
        f.write("\t\tGeometryVersion: 124\n")
        
        # UV Layer
        # Use ByPolygonVertex + IndexToDirect (like UE exports)
        # uv_data is now per-polygon-vertex (same order as polygon_indices)
        if uv_data and len(uv_data) > 0:
            # Create unique UV list and UVIndex array
            # UVIndex maps each polygon vertex to a UV in the UV array
            unique_uvs = []
            uv_to_index = {}
            
            # Build unique UV list and index mapping from polygon vertex UVs
            polygon_uv_indices = []
            for uv in uv_data:
                # Flip V coordinate for FBX convention
                uv_flipped = (uv[0], 1.0 - uv[1])
                if uv_flipped not in uv_to_index:
                    uv_to_index[uv_flipped] = len(unique_uvs)
                    unique_uvs.append(uv_flipped)
                polygon_uv_indices.append(uv_to_index[uv_flipped])
            
            f.write("\t\tLayerElementUV: 0 {\n")
            f.write("\t\t\tVersion: 101\n")
            f.write("\t\t\tName: \"map1\"\n")
            f.write("\t\t\tMappingInformationType: \"ByPolygonVertex\"\n")
            f.write("\t\t\tReferenceInformationType: \"IndexToDirect\"\n")
            f.write("\t\t\tUV: *{} {{\n".format(len(unique_uvs) * 2))
            f.write("\t\t\t\ta: ")
            uv_strs = []
            for uv in unique_uvs:
                uv_strs.append("{:.6f},{:.6f}".format(uv[0], uv[1]))
            f.write(",".join(uv_strs))
            f.write("\n")
            f.write("\t\t\t}\n")
            f.write("\t\t\tUVIndex: *{} {{\n".format(len(polygon_uv_indices)))
            f.write("\t\t\t\ta: ")
            f.write(",".join(str(idx) for idx in polygon_uv_indices))
            f.write("\n")
            f.write("\t\t\t}\n")
            f.write("\t\t}\n")
        
        # Normal Layer
        # Use ByPolygonVertex + Direct (like BatchExport)
        # normal_data is now per-polygon-vertex (same order as polygon_indices)
        if normal_data and len(normal_data) > 0:
            # For Direct mode, we need normals in polygon vertex order
            polygon_normals = []
            for normal in normal_data:
                nx, ny, nz = normal[0], normal[1], normal[2]
                length = (nx*nx + ny*ny + nz*nz) ** 0.5
                if length > 0.0001:
                    nx, ny, nz = nx/length, ny/length, nz/length
                else:
                    nx, ny, nz = 0.0, 0.0, 1.0  # Default to up if zero length
                polygon_normals.append((nx, ny, nz))
            
            f.write("\t\tLayerElementNormal: 0 {\n")
            f.write("\t\t\tVersion: 101\n")
            f.write("\t\t\tName: \"\"\n")
            f.write("\t\t\tMappingInformationType: \"ByPolygonVertex\"\n")
            f.write("\t\t\tReferenceInformationType: \"Direct\"\n")
            f.write("\t\t\tNormals: *{} {{\n".format(len(polygon_normals) * 3))
            f.write("\t\t\t\ta: ")
            normal_strs = []
            for normal in polygon_normals:
                normal_strs.append("{:.6f},{:.6f},{:.6f}".format(normal[0], normal[1], normal[2]))
            f.write(",".join(normal_strs))
            f.write("\n")
            f.write("\t\t\t}\n")
            f.write("\t\t}\n")
        
        # Write Layer section (combine UV and Normal if both exist)
        f.write("\t\tLayer: 0 {\n")
        f.write("\t\t\tVersion: 100\n")
        if uv_data and len(uv_data) > 0:
            f.write("\t\t\tLayerElement:  {\n")
            f.write("\t\t\t\tType: \"LayerElementUV\"\n")
            f.write("\t\t\t\tTypedIndex: 0\n")
            f.write("\t\t\t}\n")
        if normal_data and len(normal_data) > 0:
            f.write("\t\t\tLayerElement:  {\n")
            f.write("\t\t\t\tType: \"LayerElementNormal\"\n")
            f.write("\t\t\t\tTypedIndex: 0\n")
            f.write("\t\t\t}\n")
        f.write("\t\t}\n")
        
        f.write("\t}\n")
        
        # Model
        f.write("\tModel: 2000, \"Model::Mesh\", \"Mesh\" {\n")
        f.write("\t\tVersion: 232\n")
        f.write("\t\tProperties70:  {\n")
        f.write("\t\t\tP: \"RotationActive\", \"bool\", \"\", \"\",1\n")
        f.write("\t\t\tP: \"InheritType\", \"enum\", \"\", \"\",1\n")
        f.write("\t\t\tP: \"ScalingMax\", \"Vector3D\", \"Vector\", \"\",0,0,0\n")
        f.write("\t\t\tP: \"DefaultAttributeIndex\", \"int\", \"Integer\", \"\",0\n")
        f.write("\t\t}\n")
        f.write("\t\tShading: T\n")
        f.write("\t\tCulling: \"CullingOff\"\n")
        f.write("\t}\n")
        f.write("}\n\n")
        
        # Connections
        f.write("Connections:  {\n")
        f.write("\tC: \"OO\",2000,0\n")
        f.write("\tC: \"OO\",1000,2000\n")
        f.write("}\n\n")
        
        f.write("; End of FBX file\n")


def capture_mesh_and_export_callback(ctx: qrd.CaptureContext, data):
    """Callback for the CaptureMeshAndExport menu item"""
    try:
        # Check if we have a capture loaded
        if not ctx.HasEventBrowser():
            ctx.Extensions().MessageDialog(
                "No capture loaded. Please open a capture file first.",
                "CaptureMeshAndExport"
            )
            return
        
        # Get current selected event
        event_id = ctx.CurSelectedEvent()
        if event_id == 0:
            ctx.Extensions().MessageDialog(
                "No event selected. Please select a drawcall in the Event Browser.",
                "CaptureMeshAndExport"
            )
            return
        
        # Get action to verify it's a drawcall
        action = ctx.GetAction(event_id)
        if action is None:
            ctx.Extensions().ErrorDialog(
                "Could not get action for event {}".format(event_id),
                "CaptureMeshAndExport Error"
            )
            return
        
        if not (action.flags & (rd.ActionFlags.Drawcall | rd.ActionFlags.MeshDispatch)):
            ctx.Extensions().ErrorDialog(
                "Selected event is not a drawcall",
                "CaptureMeshAndExport Error"
            )
            return
        
        # Get file path
        file_path = ctx.Extensions().SaveFileName(
            "Export Mesh to FBX",
            "",
            "FBX Files (*.fbx);;All Files (*.*)"
        )
        
        if not file_path:
            return
        
        # Ensure .fbx extension
        if not file_path.lower().endswith('.fbx'):
            file_path += '.fbx'
        
        # Get MiniQtHelper for UI thread invocation
        mqt = ctx.Extensions().GetMiniQtHelper()
        
        # Create debug file path (same directory as FBX file)
        debug_file_path = os.path.splitext(file_path)[0] + "_debug.txt"
        
        # Get VS Input attributes in replay thread to show mapping dialog
        vs_inputs = None
        
        def get_vs_inputs(r: rd.ReplayController):
            """Get VS Input attributes for mapping dialog"""
            nonlocal vs_inputs
            try:
                r.SetFrameEvent(event_id, True)
                pipe = r.GetPipelineState()
                vs_inputs = pipe.GetVertexInputs()
            except Exception as e:
                ctx.Extensions().ErrorDialog(
                    "Failed to get VS Input attributes: {}".format(str(e)),
                    "CaptureMeshAndExport Error"
                )
        
        # Get VS Input attributes synchronously
        ctx.Replay().BlockInvoke(get_vs_inputs)
        
        if vs_inputs is None:
            return  # Failed to get VS Input
        
        # Show attribute mapping dialog
        attribute_mapping = showAttributeMappingDialog(ctx, vs_inputs)
        
        # Check if user cancelled the dialog
        if attribute_mapping is None:
            return  # User cancelled
        
        # Perform export in replay thread (async to avoid blocking UI)
        def do_export(r: rd.ReplayController):
            debug_file = None
            try:
                # Open debug file for writing
                debug_file = open(debug_file_path, 'w', encoding='utf-8')
                debug_file.write("CaptureMeshAndExport Debug Information\n")
                debug_file.write("=" * 60 + "\n")
                debug_file.write("Event ID: {}\n".format(event_id))
                debug_file.write("FBX File: {}\n".format(file_path))
                debug_file.write("Attribute Mapping: {}\n".format(attribute_mapping))
                debug_file.write("=" * 60 + "\n\n")
                
                # Set frame event (required for GetPostVSData)
                debug_file.write("Setting frame event to {}...\n".format(event_id))
                r.SetFrameEvent(event_id, True)
                
                # Get PostVS data (VS Output)
                debug_file.write("Getting PostVS data...\n")
                postvs = r.GetPostVSData(0, 0, rd.MeshDataStage.VSOut)
                debug_file.write("PostVS numIndices: {}\n".format(postvs.numIndices))
                debug_file.write("PostVS baseVertex: {}\n".format(postvs.baseVertex))
                debug_file.write("PostVS indexByteOffset: {}\n".format(postvs.indexByteOffset))
                
                if postvs.numIndices == 0:
                    raise RuntimeError("No VS output data available (numIndices = 0)")
                
                # Get mesh outputs configuration
                debug_file.write("Getting mesh outputs configuration...\n")
                meshOutputs = getMeshOutputs(r, postvs)
                debug_file.write("Number of mesh outputs: {}\n".format(len(meshOutputs)))
                
                if len(meshOutputs) == 0:
                    raise RuntimeError("No mesh outputs found")
                
                # Get action for VS Input position reading and index buffer reading
                action = ctx.GetAction(event_id)
                debug_file.write("Action baseVertex: {}, indexOffset: {}, vertexOffset: {}\n".format(
                    action.baseVertex, action.indexOffset, action.vertexOffset))
                
                # Extract mesh data with attribute mapping
                debug_file.write("\nExtracting mesh data...\n")
                vertices, polygon_indices, uv_data, normal_data, tangent_data = extractMeshData(
                    r, meshOutputs, action, attribute_mapping, debug_file)
                
                if len(vertices) == 0:
                    raise RuntimeError("No vertices extracted")
                
                # Write FBX file
                debug_file.write("\nWriting FBX file...\n")
                debug_file.write("  - Vertices: {}\n".format(len(vertices)))
                debug_file.write("  - Polygon indices: {}\n".format(len(polygon_indices)))
                debug_file.write("  - UV data: {}\n".format(len(uv_data)))
                debug_file.write("  - Normal data: {}\n".format(len(normal_data)))
                debug_file.write("  - Tangent data: {}\n".format(len(tangent_data)))
                writeFBX(vertices, polygon_indices, uv_data, normal_data, tangent_data, file_path)
                debug_file.write("FBX file written successfully!\n")
                
                # Close debug file
                if debug_file:
                    debug_file.close()
                    debug_file = None
                
                # Invoke message dialog on UI thread
                mqt.InvokeOntoUIThread(
                    lambda: ctx.Extensions().MessageDialog(
                        "Mesh exported successfully to:\n{}\n\nDebug info saved to:\n{}".format(
                            file_path, debug_file_path),
                        "CaptureMeshAndExport"
                    )
                )
                
            except Exception as e:
                import traceback
                error_msg = "Error exporting mesh: {}\n{}".format(str(e), traceback.format_exc())
                
                # Write error to debug file
                if debug_file:
                    debug_file.write("\n" + "=" * 60 + "\n")
                    debug_file.write("ERROR:\n")
                    debug_file.write(error_msg + "\n")
                    debug_file.write("=" * 60 + "\n")
                    debug_file.close()
                    debug_file = None
                
                # Invoke error dialog on UI thread
                mqt.InvokeOntoUIThread(
                    lambda: ctx.Extensions().ErrorDialog(
                        error_msg + "\n\nDebug info saved to:\n{}".format(debug_file_path),
                        "CaptureMeshAndExport Error"
                    )
                )
        
        # Execute in replay thread asynchronously (non-blocking)
        ctx.Replay().AsyncInvoke('', do_export)
        
    except Exception as e:
        ctx.Extensions().ErrorDialog(
            "Error in CaptureMeshAndExport: {}".format(str(e)),
            "CaptureMeshAndExport Error"
        )


def register(version: str, ctx: qrd.CaptureContext):
    """Register the extension"""
    global extiface_version
    extiface_version = version
    
    try:
        # Register menu item in Tools menu
        ctx.Extensions().RegisterWindowMenu(
            qrd.WindowMenu.Tools, 
            ["CaptureMeshAndExport"], 
            capture_mesh_and_export_callback
        )
    except Exception as e:
        import traceback
        error_msg = "Error registering extension: {}\n{}".format(str(e), traceback.format_exc())
        ctx.Extensions().ErrorDialog(error_msg, "Extension Registration Error")


def unregister():
    """Unregister the extension"""
    pass

