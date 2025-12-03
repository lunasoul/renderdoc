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
    # IMPORTANT: Use VS Input index buffer (ib) instead of PostVS index buffer (mesh.indexResourceId)
    # This is because VS Input indices (IDX) are what we need to read VS Input data correctly
    pipe = controller.GetPipelineState()
    ib = pipe.GetIBuffer()
    
    if ib.resourceId != rd.ResourceId.Null() and action is not None and (action.flags & rd.ActionFlags.Indexed):
        # Use action values (VS Input indices)
        base_vertex = action.baseVertex
        index_offset = action.indexOffset
        
        # Following mesh_attribute_printer pattern: use ib.byteOffset + action.indexOffset * ib.byteStride
        buffer_offset = ib.byteOffset + index_offset * ib.byteStride
        buffer_size = ib.byteStride * action.numIndices
        
        debug_write("Using VS Input index buffer (ib) instead of PostVS index buffer")
        debug_write("IBuffer: resourceId={}, byteOffset={}, byteStride={}".format(
            ib.resourceId, ib.byteOffset, ib.byteStride))
        debug_write("Using baseVertex={} (from action), indexOffset={} (from action)".format(
            base_vertex, index_offset))
        debug_write("Calculated buffer_offset={} (ib.byteOffset={} + indexOffset={} * stride={})".format(
            buffer_offset, ib.byteOffset, index_offset, ib.byteStride))
        
        # Fetch the data
        ibdata = controller.GetBufferData(ib.resourceId, buffer_offset, buffer_size)
        debug_write("Fetched {} bytes from VS Input index buffer (requested {})".format(len(ibdata), buffer_size))
        
        # Determine format
        index_fmt = 'B'
        if ib.byteStride == 2:
            index_fmt = 'H'
        elif ib.byteStride == 4:
            index_fmt = 'I'
        
        index_fmt = '=' + index_fmt  # Use native byte order
        
        # Unpack all indices
        num_indices = action.numIndices
        indices = []
        
        for i in range(num_indices):
            idx_offset = i * ib.byteStride
            if idx_offset + ib.byteStride <= len(ibdata):
                idx = struct.unpack_from(index_fmt, ibdata, idx_offset)[0]
                indices.append(idx + base_vertex)
            else:
                # Not enough data, use index as fallback
                debug_write("WARNING: Not enough data for index {}, using fallback".format(i))
                indices.append(i + base_vertex)
        
        # Debug: show first 5 raw indices (with bounds checking)
        if len(ibdata) >= ib.byteStride:
            raw_indices_debug = []
            for i in range(min(5, len(indices))):
                idx_offset = i * ib.byteStride
                if idx_offset + ib.byteStride <= len(ibdata):
                    raw_indices_debug.append(struct.unpack_from(index_fmt, ibdata, idx_offset)[0])
                else:
                    break
            debug_write("First {} raw indices (before baseVertex): {}".format(len(raw_indices_debug), raw_indices_debug))
        else:
            debug_write("WARNING: Index buffer too small ({} bytes) to read indices".format(len(ibdata)))
        
        debug_write("First 5 indices (after baseVertex): {}".format(indices[:5] if len(indices) >= 5 else indices))
        return indices
    elif mesh.indexResourceId != rd.ResourceId.Null():
        # Fallback: use PostVS index buffer (less reliable for VS Input reading)
        debug_write("WARNING: Using PostVS index buffer (ib not available or not indexed)")
        # Use action values if provided, otherwise use mesh values
        base_vertex = action.baseVertex if action is not None else mesh.baseVertex
        index_offset = action.indexOffset if action is not None else mesh.indexOffset
        
        # Read entire buffer from mesh.indexByteOffset, then use indexOffset as offset within
        ibdata_full = controller.GetBufferData(mesh.indexResourceId, mesh.indexByteOffset, 0)
        offset_in_buffer = index_offset * mesh.indexByteStride
        
        debug_write("IBuffer: resourceId={}, byteOffset={}, byteStride={}".format(
            ib.resourceId, ib.byteOffset, ib.byteStride))
        debug_write("mesh.indexByteOffset={}, mesh.indexOffset={}".format(
            mesh.indexByteOffset, mesh.indexOffset))
        debug_write("Using baseVertex={} (from {}), indexOffset={} (from {})".format(
            base_vertex, "action" if action is not None else "mesh",
            index_offset, "action" if action is not None else "mesh"))
        debug_write("Read {} bytes from index buffer (starting from mesh.indexByteOffset={})".format(
            len(ibdata_full), mesh.indexByteOffset))
        debug_write("Offset within buffer: {} (indexOffset={} * stride={})".format(
            offset_in_buffer, index_offset, mesh.indexByteStride))
        
        # Check if we have enough data
        required_size = offset_in_buffer + mesh.indexByteStride * mesh.numIndices
        if len(ibdata_full) < required_size:
            debug_write("WARNING: Full buffer size {} < required size {}".format(len(ibdata_full), required_size))
            # Try approach 2: mesh_attribute_printer pattern
            buffer_offset = ib.byteOffset + index_offset * ib.byteStride
            buffer_size = ib.byteStride * mesh.numIndices
            debug_write("Trying alternative: buffer_offset={} (ib.byteOffset={} + indexOffset={} * stride={})".format(
                buffer_offset, ib.byteOffset, index_offset, ib.byteStride))
            ibdata = controller.GetBufferData(mesh.indexResourceId, buffer_offset, buffer_size)
            debug_write("Alternative read: {} bytes (requested {})".format(len(ibdata), buffer_size))
            if len(ibdata) == 0 or len(ibdata) < mesh.indexByteStride:
                # Fall back to using what we have from full buffer
                debug_write("Alternative failed, using full buffer with available data")
                ibdata = ibdata_full
                # Adjust to available size
                available_indices = (len(ibdata) - offset_in_buffer) // mesh.indexByteStride if len(ibdata) > offset_in_buffer else 0
                if available_indices < mesh.numIndices:
                    debug_write("Adjusting numIndices from {} to {} (available)".format(mesh.numIndices, available_indices))
                    num_indices = available_indices
                else:
                    num_indices = mesh.numIndices
            else:
                # Use alternative approach, offset is 0 in this data
                offset_in_buffer = 0
                num_indices = mesh.numIndices
        else:
            # Use full buffer approach
            ibdata = ibdata_full
            num_indices = mesh.numIndices
        
        debug_write("Fetched {} bytes from PostVS index buffer".format(len(ibdata)))
        
        # Check if we got any data
        if len(ibdata) == 0:
            raise RuntimeError("Failed to read index buffer: got 0 bytes")
        
        if len(ibdata) < offset_in_buffer + mesh.indexByteStride:
            raise RuntimeError("Index buffer too small: got {} bytes, need at least {} bytes (offset={})".format(
                len(ibdata), offset_in_buffer + mesh.indexByteStride, offset_in_buffer))
        
        # Unpack all indices (starting from offset_in_buffer in the fetched data)
        indices = []
        index_fmt = '=' + indexFormat[-1]  # Get format char (H, I, or B)
        
        for i in range(num_indices):
            idx_offset = offset_in_buffer + i * mesh.indexByteStride
            if idx_offset + mesh.indexByteStride <= len(ibdata):
                idx = struct.unpack_from(index_fmt, ibdata, idx_offset)[0]
                indices.append(idx + base_vertex)
            else:
                # Not enough data, use index as fallback
                debug_write("WARNING: Not enough data for index {}, using fallback".format(i))
                indices.append(i + base_vertex)
        
        # Debug: show first 5 raw indices (with bounds checking)
        if len(ibdata) >= mesh.indexByteStride:
            raw_indices_debug = []
            for i in range(min(5, len(indices))):
                idx_offset = offset_in_buffer + i * mesh.indexByteStride
                if idx_offset + mesh.indexByteStride <= len(ibdata):
                    raw_indices_debug.append(struct.unpack_from(index_fmt, ibdata, idx_offset)[0])
                else:
                    break
            debug_write("First {} raw indices (before baseVertex): {}".format(len(raw_indices_debug), raw_indices_debug))
        else:
            debug_write("WARNING: Index buffer too small ({} bytes) to read indices".format(len(ibdata)))
        
        debug_write("First 5 indices (after baseVertex): {}".format(indices[:5] if len(indices) >= 5 else indices))
        return indices
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


def extractMeshData(controller, meshData, action=None, debug_file=None):
    """Extract vertex positions, indices, and UVs from mesh data
    
    Args:
        controller: ReplayController instance
        meshData: List of MeshData objects from VS Output
        action: ActionDescription (optional, used to read VS Input position if needed)
        debug_file: File handle for writing debug information (optional)
    """
    def debug_write(msg):
        """Write debug message to file if provided"""
        if debug_file is not None:
            debug_file.write(msg + "\n")
            debug_file.flush()
    
    debug_write("=" * 60)
    debug_write("CaptureMeshAndExport: Extracting mesh data")
    debug_write("Number of mesh attributes: {}".format(len(meshData)))
    
    indices = getIndices(controller, meshData[0], action, debug_file)
    debug_write("Number of indices: {}".format(len(indices)))
    debug_write("meshData[0].baseVertex: {}".format(meshData[0].baseVertex))
    debug_write("meshData[0].indexOffset: {}".format(meshData[0].indexOffset))
    
    if len(indices) == 0:
        debug_write("WARNING: No indices found!")
        return [], [], []
    
    # Find position and UV attributes in VS Output
    # Prefer POSITION (local/world space) over SV_Position (screen space)
    # According to official docs, SV_POSITION has systemValue == ShaderBuiltin.Position
    # while POSITION is a regular output with systemValue == Undefined
    position_attr = None
    sv_position_attr = None  # Fallback to SV_Position if POSITION not available
    uv_attr = None
    
    # Debug: collect all available attributes
    available_attrs = []
    debug_write("\nAvailable VS Output attributes:")
    for attr in meshData:
        name_upper = attr.name.upper()
        system_val = getattr(attr, 'systemValue', rd.ShaderBuiltin.Undefined)
        attr_info = "{} (systemValue={}, compCount={})".format(
            attr.name, system_val, attr.format.compCount)
        available_attrs.append(attr_info)
        debug_write("  - {}".format(attr_info))
        
        # Check if this is a position attribute
        if name_upper.startswith('POSITION') and attr.format.compCount >= 3:
            # SV_POSITION has systemValue == ShaderBuiltin.Position
            # POSITION has systemValue != ShaderBuiltin.Position (usually Undefined)
            if hasattr(attr, 'systemValue') and attr.systemValue == rd.ShaderBuiltin.Position:
                # This is SV_POSITION (screen space coordinates)
                sv_position_attr = attr
                debug_write("    -> Found SV_POSITION (screen space)")
            else:
                # This is POSITION (local/world space coordinates)
                # Prefer the first POSITION we find
                if position_attr is None:
                    position_attr = attr
                    debug_write("    -> Found POSITION (local/world space)")
        elif 'TEXCOORD' in name_upper and attr.format.compCount >= 2:
            if uv_attr is None or 'TEXCOORD0' in name_upper:
                uv_attr = attr
    
    # If still no position found, try more flexible matching
    if position_attr is None and sv_position_attr is None:
        # Try to find any attribute with position-like name
        for attr in meshData:
            name_upper = attr.name.upper()
            if ('POS' in name_upper or 'POSITION' in name_upper) and attr.format.compCount >= 3:
                if hasattr(attr, 'systemValue') and attr.systemValue == rd.ShaderBuiltin.Position:
                    sv_position_attr = attr
                elif position_attr is None:
                    position_attr = attr
    
    # If no POSITION in VS Output, try to read from VS Input (original local coordinates)
    use_vs_input_position = False
    vs_input_position_data = None
    vs_input_position_attr = None
    vbs = None
    
    if position_attr is None and action is not None:
        debug_write("\nNo POSITION in VS Output, trying VS Input...")
        # Try to get position from VS Input
        pipe = controller.GetPipelineState()
        vbs = pipe.GetVBuffers()
        inputs = pipe.GetVertexInputs()
        
        debug_write("VS Input attributes:")
        for i, input_attr in enumerate(inputs):
            debug_write("  - {} (compCount={}, vertexBuffer={}, byteOffset={})".format(
                input_attr.name, input_attr.format.compCount, 
                input_attr.vertexBuffer, input_attr.byteOffset))
            
            # Check if this is POSITION by name
            if input_attr.name.upper() == 'POSITION' and input_attr.format.compCount >= 3:
                vs_input_position_attr = input_attr
                debug_write("    -> Found POSITION in VS Input by name!")
                break
        
        # If no explicit POSITION found, use the first attribute with 3+ components (usually position)
        if vs_input_position_attr is None:
            for i, input_attr in enumerate(inputs):
                if input_attr.format.compCount >= 3:
                    vs_input_position_attr = input_attr
                    debug_write("    -> Using first attribute with 3+ components: {} (compCount={}) as position".format(
                        input_attr.name, input_attr.format.compCount))
                    break
        
        if vs_input_position_attr is not None:
            # Batch read VS Input position buffer
            vb = vbs[vs_input_position_attr.vertexBuffer]
            if vb.resourceId != rd.ResourceId.Null():
                max_idx = max(indices) if indices else 0
                buffer_size = vb.byteOffset + vb.byteStride * (max_idx + action.vertexOffset + 1)
                debug_write("Reading VS Input position buffer: size={}".format(buffer_size))
                vs_input_position_data = controller.GetBufferData(vb.resourceId, 0, buffer_size)
                use_vs_input_position = True
                debug_write("Using POSITION from VS Input (original local coordinates)")
            else:
                debug_write("WARNING: VS Input position buffer resource ID is Null")
        else:
            debug_write("WARNING: No POSITION found in VS Input")
    
    # Use POSITION from VS Output if available, otherwise use VS Input, finally fall back to SV_Position
    if position_attr is None and not use_vs_input_position:
        position_attr = sv_position_attr
        if position_attr is not None:
            debug_write("\nUsing SV_POSITION from VS Output (screen space coordinates)")
        else:
            # Provide detailed error message with available attributes
            error_msg = "Could not find position attribute (POSITION or SV_Position) in mesh data.\n"
            error_msg += "Available attributes: " + ", ".join(available_attrs) if available_attrs else "None"
            debug_write("\nERROR: " + error_msg)
            raise RuntimeError(error_msg)
    elif position_attr is not None:
        debug_write("\nUsing POSITION from VS Output: {} (systemValue={})".format(
            position_attr.name, getattr(position_attr, 'systemValue', 'Unknown')))
    
    # Batch read the entire vertex buffer to avoid thousands of API calls
    # Only read VS Output position buffer if not using VS Input
    position_buffer = None
    if not use_vs_input_position and position_attr is not None:
        # Calculate the maximum index we need
        max_idx = max(indices) if indices else 0
        num_vertices = max_idx + 1
        
        # Calculate buffer size needed
        buffer_size = position_attr.vertexByteOffset + position_attr.vertexByteStride * num_vertices
        
        # Batch read position buffer from VS Output
        position_buffer = controller.GetBufferData(
            position_attr.vertexResourceId,
            position_attr.vertexByteOffset,
            buffer_size
        )
    
    # Try to read UV from VS Input first (Attribute5 with 2 components)
    # If not available, fall back to VS Output
    use_vs_input_uv = False
    vs_input_uv_data = None
    vs_input_uv_attr = None
    uv_buffer = None
    
    if action is not None and vbs is not None:
        debug_write("\nTrying to find UV in VS Input...")
        pipe = controller.GetPipelineState()
        inputs = pipe.GetVertexInputs()
        
        # Look for Attribute5 with 2 components (UV)
        for input_attr in inputs:
            if input_attr.name.upper() == 'ATTRIBUTE5' and input_attr.format.compCount == 2:
                vs_input_uv_attr = input_attr
                debug_write("Found Attribute5 (UV) in VS Input: compCount={}, vertexBuffer={}, byteOffset={}".format(
                    input_attr.format.compCount, input_attr.vertexBuffer, input_attr.byteOffset))
                break
        
        if vs_input_uv_attr is not None:
            # Batch read VS Input UV buffer
            vb = vbs[vs_input_uv_attr.vertexBuffer]
            if vb.resourceId != rd.ResourceId.Null():
                max_idx = max(indices) if indices else 0
                buffer_size = vb.byteOffset + vb.byteStride * (max_idx + action.vertexOffset + 1)
                debug_write("Reading VS Input UV buffer: size={}".format(buffer_size))
                vs_input_uv_data = controller.GetBufferData(vb.resourceId, 0, buffer_size)
                use_vs_input_uv = True
                debug_write("Using UV from VS Input (Attribute5)")
            else:
                debug_write("WARNING: VS Input UV buffer resource ID is Null")
        else:
            debug_write("No Attribute5 found in VS Input, will try VS Output")
    
    # Fall back to VS Output UV if VS Input UV not available
    if not use_vs_input_uv and uv_attr is not None:
        debug_write("Using UV from VS Output (TEXCOORD)")
        max_idx = max(indices) if indices else 0
        num_vertices = max_idx + 1
        uv_buffer_size = uv_attr.vertexByteOffset + uv_attr.vertexByteStride * num_vertices
        uv_buffer = controller.GetBufferData(
            uv_attr.vertexResourceId,
            uv_attr.vertexByteOffset,
            uv_buffer_size
        )
    
    # Key insight: VS Input uses IDX (original buffer index), VS Output uses VTX (display vertex index)
    # PostVS data is stored in VTX order (0, 1, 2, ...), not IDX order
    # Important: Each VTX may have different VS Output data even if they share the same IDX
    # So we need to process each VTX individually, not group by IDX
    
    num_vertices = len(indices)
    debug_write("\nProcessing {} vertices (VTX order)...".format(num_vertices))
    
    # Step 1: Extract vertex data for each VTX in order
    # For each VTX: read position from VS Input (using IDX), read UV from VS Output (using VTX)
    # Also read normal from VS Input Attribute1 (using IDX)
    vertex_data_by_vtx = {}  # Maps VTX -> (position, uv, normal)
    
    # Try to read normal from VS Input Attribute2
    # Attribute1 is likely TangentU, Attribute2 is likely Normal
    use_vs_input_normal = False
    vs_input_normal_data = None
    vs_input_normal_attr = None
    
    # Also try to read tangent from Attribute1
    use_vs_input_tangent = False
    vs_input_tangent_data = None
    vs_input_tangent_attr = None
    
    if action is not None and vbs is not None:
        debug_write("\nTrying to find Normal (Attribute2) and TangentU (Attribute1) in VS Input...")
        pipe = controller.GetPipelineState()
        inputs = pipe.GetVertexInputs()
        
        # Look for Attribute2 with 3 or 4 components (normal vector)
        for input_attr in inputs:
            if input_attr.name.upper() == 'ATTRIBUTE2' and input_attr.format.compCount >= 3:
                vs_input_normal_attr = input_attr
                debug_write("Found Attribute2 (Normal) in VS Input: compCount={}, vertexBuffer={}, byteOffset={}".format(
                    input_attr.format.compCount, input_attr.vertexBuffer, input_attr.byteOffset))
                break
        
        # Look for Attribute1 with 3 or 4 components (tangent vector)
        for input_attr in inputs:
            if input_attr.name.upper() == 'ATTRIBUTE1' and input_attr.format.compCount >= 3:
                vs_input_tangent_attr = input_attr
                debug_write("Found Attribute1 (TangentU) in VS Input: compCount={}, vertexBuffer={}, byteOffset={}".format(
                    input_attr.format.compCount, input_attr.vertexBuffer, input_attr.byteOffset))
                break
        
        if vs_input_normal_attr is not None:
            # Batch read VS Input normal buffer
            vb = vbs[vs_input_normal_attr.vertexBuffer]
            if vb.resourceId != rd.ResourceId.Null():
                max_idx = max(indices) if indices else 0
                buffer_size = vb.byteOffset + vb.byteStride * (max_idx + action.vertexOffset + 1)
                debug_write("Reading VS Input Normal buffer: size={}".format(buffer_size))
                vs_input_normal_data = controller.GetBufferData(vb.resourceId, 0, buffer_size)
                use_vs_input_normal = True
                debug_write("Using Normal from VS Input (Attribute2)")
            else:
                debug_write("WARNING: VS Input Normal buffer resource ID is Null")
        else:
            debug_write("No Attribute2 found in VS Input for normal")
        
        if vs_input_tangent_attr is not None:
            # Batch read VS Input tangent buffer
            vb = vbs[vs_input_tangent_attr.vertexBuffer]
            if vb.resourceId != rd.ResourceId.Null():
                max_idx = max(indices) if indices else 0
                buffer_size = vb.byteOffset + vb.byteStride * (max_idx + action.vertexOffset + 1)
                debug_write("Reading VS Input Tangent buffer: size={}".format(buffer_size))
                vs_input_tangent_data = controller.GetBufferData(vb.resourceId, 0, buffer_size)
                use_vs_input_tangent = True
                debug_write("Using TangentU from VS Input (Attribute1)")
            else:
                debug_write("WARNING: VS Input Tangent buffer resource ID is Null")
        else:
            debug_write("No Attribute1 found in VS Input for tangent")
    
    debug_write("Extracting vertex data for each VTX...")
    # Debug: log first few indices to understand the pattern
    if len(indices) > 0:
        debug_write("First 10 indices: {}".format(indices[:10]))
        debug_write("Last 10 indices: {}".format(indices[-10:]))
        if action is not None:
            debug_write("action.baseVertex: {}, action.vertexOffset: {}".format(
                getattr(action, 'baseVertex', 'N/A'), action.vertexOffset))
        if use_vs_input_position and vs_input_position_attr is not None:
            vb = vbs[vs_input_position_attr.vertexBuffer]
            debug_write("VS Input position buffer: stride={}, byteOffset={}, attr.byteOffset={}".format(
                vb.byteStride, vb.byteOffset, vs_input_position_attr.byteOffset))
    
    for vtx in range(num_vertices):
        idx = indices[vtx]
        
        # Get position from VS Input (using IDX)
        # According to official decode_mesh example:
        # - vertexByteOffset = attr.byteOffset + vb.byteOffset + draw.vertexOffset * vb.byteStride
        # - offset = vertexByteOffset + vb.byteStride * idx
        # - idx from getIndices already includes baseVertex
        # So: offset = (attr.byteOffset + vb.byteOffset + vertexOffset * stride) + stride * idx
        #    = attr.byteOffset + vb.byteOffset + stride * (idx + vertexOffset)
        if use_vs_input_position and vs_input_position_data is not None:
            # Read position from VS Input (original local coordinates) - use IDX
            vb = vbs[vs_input_position_attr.vertexBuffer]
            # Calculate offset following official example pattern
            # vertexByteOffset equivalent: attr.byteOffset + vb.byteOffset + vertexOffset * stride
            vertex_byte_offset = (vs_input_position_attr.byteOffset + vb.byteOffset + 
                                 action.vertexOffset * vb.byteStride)
            # Final offset: vertexByteOffset + stride * idx
            offset = vertex_byte_offset + vb.byteStride * idx
            if offset < len(vs_input_position_data):
                pos_data = vs_input_position_data[offset:offset + vs_input_position_attr.format.compByteWidth * vs_input_position_attr.format.compCount]
                pos_value = unpackData(vs_input_position_attr.format, pos_data)
            else:
                debug_write("WARNING: VTX {} (IDX {}): offset {} >= buffer size {}".format(
                    vtx, idx, offset, len(vs_input_position_data)))
                pos_value = (0.0, 0.0, 0.0)
        else:
            # Read position from VS Output (using VTX)
            if position_buffer is not None:
                pos_offset = position_attr.vertexByteStride * vtx
                if pos_offset + position_attr.format.compByteWidth * position_attr.format.compCount <= len(position_buffer):
                    pos_data = position_buffer[pos_offset:pos_offset + position_attr.vertexByteStride]
                    pos_value = unpackData(position_attr.format, pos_data)
                else:
                    pos_value = (0.0, 0.0, 0.0)
            else:
                pos_value = (0.0, 0.0, 0.0)
        
        # Take first 3 components for position
        pos = (float(pos_value[0]), float(pos_value[1]), float(pos_value[2]) if len(pos_value) > 2 else 0.0)
        
        # Get UV from VS Input (using IDX) or VS Output (using VTX)
        if use_vs_input_uv and vs_input_uv_attr is not None and vs_input_uv_data is not None:
            # Read UV from VS Input using IDX (same as position)
            vb = vbs[vs_input_uv_attr.vertexBuffer]
            uv_offset = (vb.byteOffset + vs_input_uv_attr.byteOffset + 
                        vb.byteStride * (idx + action.vertexOffset))
            if uv_offset + vs_input_uv_attr.format.compByteWidth * vs_input_uv_attr.format.compCount <= len(vs_input_uv_data):
                uv_data_bytes = vs_input_uv_data[uv_offset:uv_offset + vs_input_uv_attr.format.compByteWidth * vs_input_uv_attr.format.compCount]
                uv_value = unpackData(vs_input_uv_attr.format, uv_data_bytes)
                uv = (float(uv_value[0]), float(uv_value[1]) if len(uv_value) > 1 else 0.0)
            else:
                uv = (0.0, 0.0)
        elif uv_attr is not None and uv_buffer is not None:
            # Fall back to VS Output (using VTX, not IDX!)
            uv_offset = uv_attr.vertexByteStride * vtx  # VS Output uses VTX, not IDX!
            if uv_offset + uv_attr.format.compByteWidth * uv_attr.format.compCount <= len(uv_buffer):
                uv_data_bytes = uv_buffer[uv_offset:uv_offset + uv_attr.vertexByteStride]
                uv_value = unpackData(uv_attr.format, uv_data_bytes)
                uv = (float(uv_value[0]), float(uv_value[1]) if len(uv_value) > 1 else 0.0)
            else:
                uv = (0.0, 0.0)
        else:
            uv = (0.0, 0.0)
        
        # Get Normal from VS Input (using IDX, same as position)
        normal = (0.0, 0.0, 1.0)  # Default normal (up)
        if use_vs_input_normal and vs_input_normal_attr is not None and vs_input_normal_data is not None:
            # Read normal from VS Input using IDX (same as position)
            vb = vbs[vs_input_normal_attr.vertexBuffer]
            normal_offset = (vb.byteOffset + vs_input_normal_attr.byteOffset + 
                           vb.byteStride * (idx + action.vertexOffset))
            if normal_offset + vs_input_normal_attr.format.compByteWidth * vs_input_normal_attr.format.compCount <= len(vs_input_normal_data):
                normal_data_bytes = vs_input_normal_data[normal_offset:normal_offset + vs_input_normal_attr.format.compByteWidth * vs_input_normal_attr.format.compCount]
                normal_value = unpackData(vs_input_normal_attr.format, normal_data_bytes)
                # Take first 3 components for normal (ignore w component if present)
                normal = (float(normal_value[0]), float(normal_value[1]), float(normal_value[2]) if len(normal_value) > 2 else 0.0)
            else:
                debug_write("WARNING: VTX {} (IDX {}): normal offset {} >= buffer size {}".format(
                    vtx, idx, normal_offset, len(vs_input_normal_data)))
        
        # Get Tangent from VS Input (using IDX, same as position and normal)
        tangent = (1.0, 0.0, 0.0)  # Default tangent (right)
        if use_vs_input_tangent and vs_input_tangent_attr is not None and vs_input_tangent_data is not None:
            # Read tangent from VS Input using IDX (same as position and normal)
            vb = vbs[vs_input_tangent_attr.vertexBuffer]
            tangent_offset = (vb.byteOffset + vs_input_tangent_attr.byteOffset + 
                            vb.byteStride * (idx + action.vertexOffset))
            if tangent_offset + vs_input_tangent_attr.format.compByteWidth * vs_input_tangent_attr.format.compCount <= len(vs_input_tangent_data):
                tangent_data_bytes = vs_input_tangent_data[tangent_offset:tangent_offset + vs_input_tangent_attr.format.compByteWidth * vs_input_tangent_attr.format.compCount]
                tangent_value = unpackData(vs_input_tangent_attr.format, tangent_data_bytes)
                # Take first 3 components for tangent (ignore w component if present)
                tangent = (float(tangent_value[0]), float(tangent_value[1]), float(tangent_value[2]) if len(tangent_value) > 2 else 0.0)
            else:
                debug_write("WARNING: VTX {} (IDX {}): tangent offset {} >= buffer size {}".format(
                    vtx, idx, tangent_offset, len(vs_input_tangent_data)))
        
        # Store vertex data by VTX
        vertex_data_by_vtx[vtx] = (pos, uv, normal, tangent)
    
    # Step 2: Deduplicate vertices based on (position, uv) combination
    # This ensures vertices with same position AND same UV are merged
    # Note: We don't include normal/tangent in deduplication key, as same vertex position can have different normals/tangents
    vertex_key_to_index = {}  # Maps (pos, uv) -> vertex index
    vertices = []
    uv_data = []
    normal_data = []  # Store normals for each vertex
    tangent_data = []  # Store tangents for each vertex
    vtx_to_vertex_idx = {}  # Maps VTX -> vertex index in deduplicated list
    
    debug_write("Deduplicating vertices based on (position, uv)...")
    for vtx in range(num_vertices):
        pos, uv, normal, tangent = vertex_data_by_vtx[vtx]
        key = (pos, uv)
        
        if key not in vertex_key_to_index:
            # New unique vertex
            vertex_idx = len(vertices)
            vertices.append(pos)
            uv_data.append(uv)
            normal_data.append(normal)
            tangent_data.append(tangent)
            vertex_key_to_index[key] = vertex_idx
        else:
            # Existing vertex - use its normal/tangent (or average if needed, but for now just use the first one)
            # In practice, if position and UV are the same, normal/tangent should also be the same
            pass
        
        vtx_to_vertex_idx[vtx] = vertex_key_to_index[key]
    
    debug_write("Unique vertices after deduplication: {} (out of {} total VTX)".format(len(vertices), num_vertices))
    
    # Step 3: Create polygon indices by mapping VTX to vertex indices
    polygon_indices = []
    for vtx in range(num_vertices):
        vertex_idx = vtx_to_vertex_idx[vtx]
        polygon_indices.append(vertex_idx)
    
    debug_write("Extraction complete:")
    debug_write("  - Vertices: {}".format(len(vertices)))
    debug_write("  - Polygon indices: {}".format(len(polygon_indices)))
    debug_write("  - UV data: {}".format(len(uv_data)))
    debug_write("  - Normal data: {}".format(len(normal_data)))
    debug_write("  - Tangent data: {}".format(len(tangent_data)))
    debug_write("=" * 60)
    
    return vertices, polygon_indices, uv_data, normal_data, tangent_data


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
        # This allows each polygon vertex to reference a unique UV, even if vertices share positions
        if uv_data and len(uv_data) > 0:
            # Create unique UV list and UVIndex array
            # UVIndex maps each polygon vertex to a UV in the UV array
            unique_uvs = []
            uv_to_index = {}
            uv_indices = []
            
            # Build unique UV list and index mapping
            for uv in uv_data:
                # Flip V coordinate for FBX convention
                uv_flipped = (uv[0], 1.0 - uv[1])
                if uv_flipped not in uv_to_index:
                    uv_to_index[uv_flipped] = len(unique_uvs)
                    unique_uvs.append(uv_flipped)
                uv_indices.append(uv_to_index[uv_flipped])
            
            # UVIndex should match polygon_indices (one UV index per polygon vertex)
            # Since we deduplicated vertices, each polygon_indices[i] corresponds to uv_data[polygon_indices[i]]
            # But we need to map polygon vertices to UV indices
            # For ByPolygonVertex, we need one UV index per polygon vertex (same order as polygon_indices)
            polygon_uv_indices = []
            for idx in polygon_indices:
                # idx is the vertex index in the deduplicated vertices list
                # uv_data[idx] is the UV for that vertex
                uv = uv_data[idx]
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
        # Use ByPolygonVertex + IndexToDirect (same as UV)
        if normal_data and len(normal_data) > 0:
            # Create unique normal list and NormalIndex array
            unique_normals = []
            normal_to_index = {}
            
            # Build unique normal list and index mapping
            for normal in normal_data:
                # Normalize the normal vector
                nx, ny, nz = normal[0], normal[1], normal[2]
                length = (nx*nx + ny*ny + nz*nz) ** 0.5
                if length > 0.0001:
                    nx, ny, nz = nx/length, ny/length, nz/length
                else:
                    nx, ny, nz = 0.0, 0.0, 1.0  # Default to up if zero length
                
                normal_tuple = (nx, ny, nz)
                if normal_tuple not in normal_to_index:
                    normal_to_index[normal_tuple] = len(unique_normals)
                    unique_normals.append(normal_tuple)
            
            # NormalIndex should match polygon_indices (one normal index per polygon vertex)
            polygon_normal_indices = []
            for idx in polygon_indices:
                # idx is the vertex index in the deduplicated vertices list
                # normal_data[idx] is the normal for that vertex
                normal = normal_data[idx]
                nx, ny, nz = normal[0], normal[1], normal[2]
                length = (nx*nx + ny*ny + nz*nz) ** 0.5
                if length > 0.0001:
                    nx, ny, nz = nx/length, ny/length, nz/length
                else:
                    nx, ny, nz = 0.0, 0.0, 1.0
                
                normal_tuple = (nx, ny, nz)
                if normal_tuple not in normal_to_index:
                    normal_to_index[normal_tuple] = len(unique_normals)
                    unique_normals.append(normal_tuple)
                polygon_normal_indices.append(normal_to_index[normal_tuple])
            
            f.write("\t\tLayerElementNormal: 0 {\n")
            f.write("\t\t\tVersion: 101\n")
            f.write("\t\t\tName: \"\"\n")
            f.write("\t\t\tMappingInformationType: \"ByPolygonVertex\"\n")
            f.write("\t\t\tReferenceInformationType: \"IndexToDirect\"\n")
            f.write("\t\t\tNormals: *{} {{\n".format(len(unique_normals) * 3))
            f.write("\t\t\t\ta: ")
            normal_strs = []
            for normal in unique_normals:
                normal_strs.append("{:.6f},{:.6f},{:.6f}".format(normal[0], normal[1], normal[2]))
            f.write(",".join(normal_strs))
            f.write("\n")
            f.write("\t\t\t}\n")
            f.write("\t\t\tNormalsIndex: *{} {{\n".format(len(polygon_normal_indices)))
            f.write("\t\t\t\ta: ")
            f.write(",".join(str(idx) for idx in polygon_normal_indices))
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
                
                # Extract mesh data
                debug_file.write("\nExtracting mesh data...\n")
                vertices, polygon_indices, uv_data, normal_data, tangent_data = extractMeshData(r, meshOutputs, action, debug_file)
                
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

