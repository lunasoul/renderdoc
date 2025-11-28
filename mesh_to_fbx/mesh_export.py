###############################################################################
# Mesh Export Module
#
# Handles mesh data extraction and FBX export
###############################################################################

import qrenderdoc as qrd
import renderdoc as rd
import struct
from typing import List, Dict, Tuple, Optional
from enum import IntEnum


class ExportMode(IntEnum):
    """Export mode enumeration"""
    VS_INPUT_ONLY = 0
    VS_INPUT_POSITION_VS_OUTPUT = 1
    VS_OUTPUT_ONLY = 2


class MeshAttribute:
    """Represents a mesh attribute with its format and data"""
    def __init__(self):
        self.name = ''
        self.mesh = rd.MeshFormat()
        self.format = rd.ResourceFormat()


class MeshExporter:
    """Main class for exporting mesh data to FBX"""
    
    def __init__(self, ctx: qrd.CaptureContext):
        self.ctx = ctx
        self.mqt = ctx.Extensions().GetMiniQtHelper()
    
    def cleanup(self):
        """Cleanup resources"""
        pass
    
    def show_export_dialog(self):
        """Show the export dialog"""
        try:
            print("show_export_dialog called")
            # Check if we have a capture loaded
            if not self.ctx.HasEventBrowser():
                print("No event browser")
                self.ctx.Extensions().MessageDialog(
                    "No capture loaded. Please open a capture file first.",
                    "Export Mesh to FBX"
                )
                return
            
            # Get current selected event
            event_id = self.ctx.CurSelectedEvent()
            print("Selected event ID: {}".format(event_id))
            if event_id == 0:
                print("No event selected")
                self.ctx.Extensions().MessageDialog(
                    "No event selected. Please select a drawcall in the Event Browser.",
                    "Export Mesh to FBX"
                )
                return
            
            # Get file path
            print("Showing save file dialog")
            file_path = self.ctx.Extensions().SaveFileName(
                "Export Mesh to FBX",
                "",
                "FBX Files (*.fbx);;All Files (*.*)"
            )
            
            if not file_path:
                print("User cancelled file selection")
                return
            
            print("Selected file: {}".format(file_path))
            
            # Get the action before async call (needs to be on UI thread)
            print("Getting action for event {}".format(event_id))
            action = self.ctx.GetAction(event_id)
            if action is None:
                self.ctx.Extensions().ErrorDialog(
                    "Could not get action for event {}".format(event_id),
                    "Export Mesh to FBX"
                )
                return
            
            print("Action flags: {}".format(action.flags))
            if not (action.flags & (rd.ActionFlags.Drawcall | rd.ActionFlags.MeshDispatch)):
                self.ctx.Extensions().ErrorDialog(
                    "Selected event is not a drawcall",
                    "Export Mesh to FBX"
                )
                return
            
            # Perform export (VS Output only)
            print("Starting async export")
            def do_export(r: rd.ReplayController):
                try:
                    print("do_export called in replay thread")
                    self._export_mesh(r, action, file_path)
                    print("Export completed successfully")
                    self.mqt.InvokeOntoUIThread(
                        lambda: self.ctx.Extensions().MessageDialog(
                            "Mesh exported successfully to:\n{}".format(file_path),
                            "Export Mesh to FBX"
                        )
                    )
                except Exception as e:
                    import traceback
                    error_msg = "Export failed:\n{}\n{}".format(str(e), traceback.format_exc())
                    print(error_msg)
                    self.mqt.InvokeOntoUIThread(
                        lambda: self.ctx.Extensions().ErrorDialog(
                            error_msg,
                            "Export Mesh to FBX"
                        )
                    )
            
            self.ctx.Replay().AsyncInvoke('', do_export)
        except Exception as e:
            import traceback
            error_msg = "Error in show_export_dialog: {}\n{}".format(str(e), traceback.format_exc())
            print(error_msg)
            self.ctx.Extensions().ErrorDialog(error_msg, "Export Mesh to FBX Error")
    
    
    def _export_mesh(self, controller: rd.ReplayController, action: rd.ActionDescription, file_path: str):
        """Export mesh data to FBX file (VS Output only)"""
        try:
            event_id = action.eventId
            print("_export_mesh called: event_id={}, file={}".format(event_id, file_path))
            # Set the event
            print("Setting frame event")
            controller.SetFrameEvent(event_id, True)
            
            # For now, only support VS Output mode to verify UV correctness
            print("Reading VS Output mesh data (refactored version)")
            vertices, indices, raw_uv_data = self._read_vs_output(controller, action)
            
            print("Got {} vertices and {} indices".format(len(vertices), len(indices)))
            if raw_uv_data:
                print("Got {} UV coordinates".format(len(raw_uv_data)))
                # Print first few UV values for verification
                for i in range(min(5, len(raw_uv_data))):
                    print("  UV[{}] = ({}, {})".format(i, raw_uv_data[i][0], raw_uv_data[i][1]))
            
            # Export to FBX
            print("Writing FBX file")
            self._write_fbx(file_path, vertices, indices, raw_uv_data)
            print("FBX file written successfully")
        except Exception as e:
            import traceback
            error_msg = "Error in _export_mesh: {}\n{}".format(str(e), traceback.format_exc())
            print(error_msg)
            raise
    
    def _get_vs_input_mesh(self, controller: rd.ReplayController, 
                           action: rd.ActionDescription) -> Tuple[List[Dict], List[int]]:
        """Get VS input mesh data"""
        state = controller.GetPipelineState()
        
        # Get vertex inputs
        ib = state.GetIBuffer()
        vbs = state.GetVBuffers()
        attrs = state.GetVertexInputs()
        
        if len(attrs) == 0:
            raise RuntimeError("No vertex inputs found")
        
        # Find position attribute
        position_attr = None
        for attr in attrs:
            if 'position' in attr.name.lower():
                position_attr = attr
                break
        
        if position_attr is None and len(attrs) > 0:
            # Use first attribute as position
            position_attr = attrs[0]
        
        # Get indices
        indices = self._get_indices(controller, ib, action)
        
        # Pre-fetch all vertex buffers to avoid per-vertex API calls
        vertex_buffers = {}
        for vb_idx, vb in enumerate(vbs):
            if vb.resourceId != rd.ResourceId.Null():
                # Get entire buffer (or at least enough for max index)
                max_idx = max(indices) if indices else 0
                buffer_size = vb.byteOffset + vb.byteStride * (max_idx + action.vertexOffset + 1)
                vertex_buffers[vb_idx] = controller.GetBufferData(vb.resourceId, 0, buffer_size)
            else:
                vertex_buffers[vb_idx] = b''
        
        # Pre-calculate position attribute index
        position_attr_idx = -1
        if position_attr:
            for i, attr in enumerate(attrs):
                if attr == position_attr:
                    position_attr_idx = i
                    break
        
        # Get vertex data - use IDX as unique vertex identifier (like reference script)
        vertex_data_by_idx = {}  # {idx: vertex_dict}
        num_indices = len(indices)
        
        # Get vertex data for each index position
        for vtx_idx in range(num_indices):
            idx = indices[vtx_idx]  # IDX (original buffer index)
            
            # If we already have this vertex (same IDX), skip
            if idx in vertex_data_by_idx:
                continue
            
            vertex = {}
            
            # Process all attributes
            for attr_idx, attr in enumerate(attrs):
                if attr.vertexBuffer >= len(vbs):
                    continue
                
                vb = vbs[attr.vertexBuffer]
                buffer_data = vertex_buffers.get(attr.vertexBuffer, b'')
                
                # Calculate offset using IDX
                offset = vb.byteOffset + attr.byteOffset + vb.byteStride * (idx + action.vertexOffset)
                
                if offset < len(buffer_data):
                    value = self._unpack_data(attr.format, buffer_data, offset)
                    if value:
                        # Check if this is position attribute
                        if attr_idx == position_attr_idx or (position_attr_idx == -1 and attr_idx == 0):
                            vertex['position'] = (value[0], value[1], value[2] if len(value) > 2 else 0.0)
                        else:
                            vertex[attr.name] = value
            
            # Ensure position exists
            if 'position' not in vertex:
                vertex['position'] = (0.0, 0.0, 0.0)
            
            vertex_data_by_idx[idx] = vertex
        
        # Sort vertices by IDX and create vertex list
        sorted_indices = sorted(vertex_data_by_idx.keys())
        vertices = [vertex_data_by_idx[idx] for idx in sorted_indices]
        
        # Create index mapping: IDX -> vertex index in sorted list
        idx_to_vertex_idx = {idx: i for i, idx in enumerate(sorted_indices)}
        
        # Create display indices: for each index position, map its IDX to vertex index
        display_indices = [idx_to_vertex_idx[indices[vtx_idx]] for vtx_idx in range(num_indices)]
        
        # VS input typically doesn't have UV data, return empty list
        raw_uv_data = [(0.0, 0.0)] * num_indices
        
        return vertices, display_indices, raw_uv_data
    
    def _read_vs_output(self, controller: rd.ReplayController, action: rd.ActionDescription):
        """
        Read VS Output data exactly like mesh_attribute_printer does.
        Returns: (vertices, indices, uv_data)
        - vertices: List of vertex dicts, each with position and other attributes
        - indices: List of vertex indices for triangles
        - uv_data: List of (u, v) tuples in VTX order
        """
        # Get PostVS data
        postvs = controller.GetPostVSData(0, 0, rd.MeshDataStage.VSOut)
        
        if postvs.numIndices == 0:
            raise RuntimeError("No VS output data available")
        
        # Get shader reflection
        pipe = controller.GetPipelineState()
        vs = pipe.GetShaderReflection(rd.ShaderStage.Vertex)
        if vs is None:
            raise RuntimeError("Could not get vertex shader reflection")
        
        # Get indices for IDX column (from VS Input)
        ib = pipe.GetIBuffer()
        indices = self._get_indices(controller, ib, action)
        num_vertices = postvs.numIndices
        
        # Build attribute list from shader output signature (exactly like mesh_attribute_printer)
        attrs = []
        for sig in vs.outputSignature:
            # Skip if not on rasterized stream
            if pipe.GetRasterizedStream() >= 0:
                if sig.stream != pipe.GetRasterizedStream():
                    continue
            else:
                if sig.stream != 0:
                    continue
            
            # Skip output indices
            if sig.systemValue == rd.ShaderBuiltin.OutputIndices:
                continue
            
            attr = type('Attr', (), {})()
            attr.name = sig.semanticIdxName if sig.varName == '' else sig.varName
            attr.format = rd.ResourceFormat()
            attr.format.compByteWidth = rd.VarTypeByteSize(sig.varType)
            attr.format.compCount = sig.compCount
            attr.format.compType = rd.VarTypeCompType(sig.varType)
            attr.format.type = rd.ResourceFormatType.Regular
            attr.mesh = rd.MeshFormat(postvs)
            attrs.append(attr)
        
        if len(attrs) == 0:
            raise RuntimeError("No output attributes found")
        
        # Calculate attribute offsets (exactly like mesh_attribute_printer)
        accum_offset = 0
        for attr in attrs:
            fmt = attr.format
            elem_size = (8 if fmt.compByteWidth > 4 else 4)
            
            # Alignment
            alignment = elem_size * 4
            if pipe.HasAlignedPostVSData(rd.MeshDataStage.VSOut) and (accum_offset % alignment) != 0:
                padding = alignment - (accum_offset % alignment)
                accum_offset += padding
            
            attr.offset = postvs.vertexByteOffset + accum_offset
            accum_offset += elem_size * fmt.compCount
        
        # Get output buffer
        output_buffer_size = postvs.vertexByteOffset + postvs.vertexByteStride * num_vertices
        output_buffer = controller.GetBufferData(postvs.vertexResourceId, 0, output_buffer_size)
        
        # Find Position and TEXCOORD0 attributes
        # Position is usually the first attribute or named SV_Position
        position_attr = None
        texcoord0_attr = None
        
        for i, attr in enumerate(attrs):
            attr_name_lower = attr.name.lower()
            # Check for Position (usually first or named SV_Position)
            if position_attr is None:
                if attr_name_lower in ('sv_position', 'position') or i == 0:
                    position_attr = attr
            # Check for TEXCOORD0
            if texcoord0_attr is None:
                if attr_name_lower in ('texcoord0', 'texcoordo') and attr.format.compCount >= 2:
                    texcoord0_attr = attr
        
        # If no explicit Position found, use first attribute
        if position_attr is None and len(attrs) > 0:
            position_attr = attrs[0]
        
        print("VS Output attributes:")
        for i, attr in enumerate(attrs):
            print("  [{}] '{}': offset={}, compCount={}, compType={}, compByteWidth={}".format(
                i, attr.name, attr.offset, attr.format.compCount, 
                attr.format.compType, attr.format.compByteWidth))
        
        if position_attr:
            print("  Position: '{}' at offset={}".format(position_attr.name, position_attr.offset))
        if texcoord0_attr:
            print("  TEXCOORD0: '{}' at offset={}, compCount={}".format(
                texcoord0_attr.name, texcoord0_attr.offset, texcoord0_attr.format.compCount))
        else:
            print("  TEXCOORD0: NOT FOUND")
            # List all TEXCOORD-like attributes
            print("  Available TEXCOORD attributes:")
            for attr in attrs:
                if 'texcoord' in attr.name.lower():
                    print("    - '{}' (compCount={})".format(attr.name, attr.format.compCount))
        
        # Read vertex data in VTX order (exactly like mesh_attribute_printer)
        vertices_data = []  # List of vertex dicts in VTX order
        uv_data = []  # List of (u, v) tuples in VTX order
        
        # Debug: Print first vertex's all attribute values for comparison
        print("\n=== Debug: First vertex (VTX 0) attribute values ===")
        
        for vtx in range(num_vertices):
            vertex = {}
            
            # Read all attributes
            for attr in attrs:
                offset = attr.offset + postvs.vertexByteStride * vtx
                if offset < len(output_buffer):
                    value = self._unpack_data(attr.format, output_buffer, offset)
                    if value:
                        vertex[attr.name] = value
                        # Debug first vertex
                        if vtx == 0:
                            print("  {}: {} (offset={})".format(attr.name, value, offset))
            
            if vtx == 0:
                print("=== End debug ===\n")
            
            # Extract position
            if position_attr and position_attr.name in vertex:
                pos_value = vertex[position_attr.name]
                vertex['position'] = (
                    float(pos_value[0]),
                    float(pos_value[1]),
                    float(pos_value[2]) if len(pos_value) > 2 else 0.0
                )
            else:
                vertex['position'] = (0.0, 0.0, 0.0)
            
            # Extract UV
            uv_value = (0.0, 0.0)
            if texcoord0_attr and texcoord0_attr.name in vertex:
                uv_data_value = vertex[texcoord0_attr.name]
                if uv_data_value and len(uv_data_value) >= 2:
                    uv_value = (float(uv_data_value[0]), float(uv_data_value[1]))
                    if vtx < 10:  # Debug first few
                        print("  VTX {}: TEXCOORD0[{}] = {} -> UV = ({}, {})".format(
                            vtx, texcoord0_attr.name, uv_data_value, uv_value[0], uv_value[1]))
                else:
                    if vtx < 5:
                        print("  VTX {}: TEXCOORD0 data invalid: {}".format(vtx, uv_data_value))
            else:
                if vtx < 5:
                    print("  VTX {}: TEXCOORD0 not found in vertex. Available keys: {}".format(
                        vtx, list(vertex.keys())))
            
            vertices_data.append(vertex)
            uv_data.append(uv_value)
        
        # Now deduplicate vertices by IDX (like reference C++ code)
        # Create mapping: IDX -> vertex data
        vertex_data_by_idx = {}
        for vtx in range(num_vertices):
            idx = indices[vtx] if vtx < len(indices) else vtx
            if idx not in vertex_data_by_idx:
                vertex_data_by_idx[idx] = vertices_data[vtx]
        
        # Sort vertices by IDX
        sorted_indices = sorted(vertex_data_by_idx.keys())
        vertices = [vertex_data_by_idx[idx] for idx in sorted_indices]
        
        # Create index mapping: IDX -> vertex index in sorted list
        idx_to_vertex_idx = {idx: i for i, idx in enumerate(sorted_indices)}
        
        # Create display indices: map original IDX to sorted vertex index
        display_indices = []
        for vtx in range(num_vertices):
            idx = indices[vtx] if vtx < len(indices) else vtx
            display_indices.append(idx_to_vertex_idx[idx])
        
        # UV data should be in VTX order (already collected above)
        # But we need to map it to sorted vertex order for ByControlPoint mapping
        # Actually, for ByControlPoint, we need UV per control point (sorted by IDX)
        uv_data_by_idx = {}
        for vtx in range(num_vertices):
            idx = indices[vtx] if vtx < len(indices) else vtx
            if idx not in uv_data_by_idx:
                uv_data_by_idx[idx] = uv_data[vtx]
        
        # Create UV data in sorted order
        raw_uv_data = [uv_data_by_idx[idx] for idx in sorted_indices]
        
        return vertices, display_indices, raw_uv_data
    
    def _get_mixed_mesh(self, controller: rd.ReplayController,
                       action: rd.ActionDescription) -> Tuple[List[Dict], List[int]]:
        """Get mixed mesh: VS input position + VS output attributes"""
        # Get VS input position
        state = controller.GetPipelineState()
        ib = state.GetIBuffer()
        vbs = state.GetVBuffers()
        input_attrs = state.GetVertexInputs()
        
        # Find position input
        position_input = None
        for attr in input_attrs:
            if 'position' in attr.name.lower():
                position_input = attr
                break
        
        if position_input is None and len(input_attrs) > 0:
            position_input = input_attrs[0]
        
        # Get VS output data
        postvs = controller.GetPostVSData(0, 0, rd.MeshDataStage.VSOut)
        vs = controller.GetPipelineState().GetShaderReflection(rd.ShaderStage.Vertex)
        
        if vs is None:
            raise RuntimeError("Could not get vertex shader reflection")
        
        # Build all VS output attributes first to calculate correct offsets
        # IMPORTANT: Filter attributes like mesh_attribute_printer does
        all_attrs = []
        position_attr = None
        
        pipe = controller.GetPipelineState()
        
        for sig in vs.outputSignature:
            # Skip if not on rasterized stream (like mesh_attribute_printer)
            if pipe.GetRasterizedStream() >= 0:
                if sig.stream != pipe.GetRasterizedStream():
                    continue
            else:
                if sig.stream != 0:
                    continue
            
            # Skip output indices (like mesh_attribute_printer)
            if sig.systemValue == rd.ShaderBuiltin.OutputIndices:
                continue
            
            attr = MeshAttribute()
            attr.mesh = postvs
            attr.format = rd.ResourceFormat()
            attr.format.compByteWidth = rd.VarTypeByteSize(sig.varType)
            attr.format.compCount = sig.compCount
            attr.format.compType = rd.VarTypeCompType(sig.varType)
            attr.format.type = rd.ResourceFormatType.Regular
            attr.name = sig.semanticIdxName if sig.varName == '' else sig.varName
            
            if sig.systemValue == rd.ShaderBuiltin.Position:
                position_attr = attr
            
            all_attrs.append(attr)
        
        # Do NOT reorder Position - keep original shader output signature order
        # This matches mesh_attribute_printer's approach
        
        # Calculate offsets for ALL attributes (including position)
        # Use same alignment calculation as mesh_attribute_printer
        accum_offset = 0
        print("Calculating PostVS offsets:")
        for attr in all_attrs:
            fmt = attr.format
            elem_size = (8 if fmt.compByteWidth > 4 else 4)
            
            # Use fixed 4x alignment like mesh_attribute_printer
            alignment = elem_size * 4
            
            # Check alignment
            if pipe.HasAlignedPostVSData(rd.MeshDataStage.VSOut) and (accum_offset % alignment) != 0:
                padding = alignment - (accum_offset % alignment)
                accum_offset += padding
                print("  Padding: {} bytes".format(padding))
            
            attr.mesh.vertexByteOffset = postvs.vertexByteOffset + accum_offset
            print("  Attribute '{}' (compCount={}): offset={}, accum_offset={}".format(
                attr.name, fmt.compCount, attr.mesh.vertexByteOffset, accum_offset))
            
            accum_offset += elem_size * fmt.compCount
        
        print("Calculated stride: {}, Actual stride: {}".format(accum_offset, postvs.vertexByteStride))
            
        # Now filter out Position for output_attrs (since we use VS Input for position)
        # But keep the calculated offsets!
        output_attrs = []
        for attr in all_attrs:
            # We identify position by checking if it was the one we found as system value Position
            # Or by name if system value wasn't set (fallback)
            is_position = False
            if position_attr and attr == position_attr:
                is_position = True
            elif 'position' in attr.name.lower():
                is_position = True
                
            if not is_position:
                output_attrs.append(attr)
        
        # Pre-calculate output attribute offsets
        output_attr_offsets = []
        print("Output attributes and their offsets:")
        for attr_idx, attr in enumerate(output_attrs):
            offset = attr.mesh.vertexByteOffset
            output_attr_offsets.append(offset)
            print("  [{}] {}: offset={}, compCount={}".format(
                attr_idx, attr.name, offset, attr.format.compCount))
            
        # Get indices from VS INPUT (not PostVS) - we need VS input indices to read VS input positions correctly
        # These are the original buffer indices (IDX) that we'll use to read from VS input buffers
        input_indices = self._get_indices(controller, ib, action)
        
        # Use input_indices for both position lookup and vertex ordering
        # PostVS data is in VTX order (0, 1, 2, ...), so we'll use VTX index (vtx) to read VS output attributes
        indices = input_indices
        
        # Pre-fetch all vertex buffers for VS input
        vertex_buffers = {}
        for vb_idx, vb in enumerate(vbs):
            if vb.resourceId != rd.ResourceId.Null():
                max_idx = max(indices) if indices else 0
                buffer_size = vb.byteOffset + vb.byteStride * (max_idx + action.vertexOffset + 1)
                vertex_buffers[vb_idx] = controller.GetBufferData(vb.resourceId, 0, buffer_size)
            else:
                vertex_buffers[vb_idx] = b''
        
        # Pre-fetch VS output buffer
        # PostVS data is in VTX order, so we need buffer size for numIndices vertices
        num_vertices = postvs.numIndices
        output_buffer_size = postvs.vertexByteOffset + postvs.vertexByteStride * num_vertices
        output_buffer = controller.GetBufferData(postvs.vertexResourceId, 0, output_buffer_size)
        
        # Pre-calculate position input offset
        position_offset = 0
        if position_input and position_input.vertexBuffer < len(vbs):
            vb = vbs[position_input.vertexBuffer]
            position_offset_base = vb.byteOffset + position_input.byteOffset
        
        # Get vertex data - use IDX as unique vertex identifier
        # For position: use IDX to get from VS input buffer
        # For other attributes: find VTX position for this IDX and read from PostVS buffer
        vertex_data_by_idx = {}  # {idx: vertex_dict}
        num_indices = len(indices)
        
        # Create mapping: IDX -> list of VTX positions where this IDX appears
        idx_to_vtx_positions = {}
        for vtx in range(num_indices):
            idx = indices[vtx]
            if idx not in idx_to_vtx_positions:
                idx_to_vtx_positions[idx] = []
            idx_to_vtx_positions[idx].append(vtx)
        
        # Also collect raw UV data in VTX order (for FBX export)
        raw_uv_data = []  # UV data for each VTX position in order
        
        # Get vertex data for each unique IDX
        for idx in idx_to_vtx_positions.keys():
            # Use the first VTX position for this IDX to read PostVS data
            vtx = idx_to_vtx_positions[idx][0]
            
            vertex = {}
            
            # Get position from VS input (using IDX - original buffer index)
            if position_input and position_input.vertexBuffer < len(vbs):
                vb = vbs[position_input.vertexBuffer]
                buffer_data = vertex_buffers.get(position_input.vertexBuffer, b'')
                offset = position_offset_base + vb.byteStride * (idx + action.vertexOffset)
                
                if offset < len(buffer_data):
                    pos = self._unpack_data(position_input.format, buffer_data, offset)
                    if pos:
                        vertex['position'] = (pos[0], pos[1], pos[2] if len(pos) > 2 else 0.0)
            
            if 'position' not in vertex:
                vertex['position'] = (0.0, 0.0, 0.0)
            
            # Get other attributes from VS output (using VTX position - PostVS is in VTX order)
            # Use exactly the same method as mesh_attribute_printer
            for attr_idx, attr in enumerate(output_attrs):
                # Calculate offset exactly like mesh_attribute_printer: attr.offset + postvs.vertexByteStride * vtx
                # where attr.offset = postvs.vertexByteOffset + accum_offset
                offset = output_attr_offsets[attr_idx] + postvs.vertexByteStride * vtx
                
                if offset < len(output_buffer):
                    value = self._unpack_data(attr.format, output_buffer, offset)
                    if value:
                        vertex[attr.name] = value
            
            vertex_data_by_idx[idx] = vertex
        
        # Collect raw UV data for each VTX position (in original order)
        # Find TEXCOORD0 attribute (exact match only)
        print("Available attributes in VS output (for mixed mesh):")
        for attr_idx, attr in enumerate(output_attrs):
            print("  [{}] {} (compCount={})".format(attr_idx, attr.name, attr.format.compCount))
        
        texcoord0_attr_idx = None
        for attr_idx, attr in enumerate(output_attrs):
            attr_name = attr.name.strip()
            attr_name_lower = attr_name.lower()
            # Exact match: TEXCOORD0 or TEXCOORDO (common typo)
            # Also check compCount >= 2 to ensure it's a valid UV attribute
            if (attr_name_lower == 'texcoord0' or attr_name_lower == 'texcoordo') and attr.format.compCount >= 2:
                texcoord0_attr_idx = attr_idx
                print("Found TEXCOORD0 attribute: '{}' at index {} (compCount={})".format(
                    attr.name, attr_idx, attr.format.compCount))
                break
        
        # Extract UV data directly from PostVS buffer using the same method as mesh_attribute_printer
        # This ensures we read from the correct offset
        uv_data_by_idx = {}  # {idx: uv_value}
        
        if texcoord0_attr_idx is not None:
            texcoord0_attr = output_attrs[texcoord0_attr_idx]
            texcoord0_offset = output_attr_offsets[texcoord0_attr_idx]
            print("TEXCOORD0 attribute: '{}' at offset {} (compCount={})".format(
                texcoord0_attr.name, texcoord0_offset, texcoord0_attr.format.compCount))
            
            # Read UV data for each unique IDX using the same VTX position as vertex_data_by_idx
            for idx in vertex_data_by_idx.keys():
                # Use the same VTX position that was used to read vertex data
                vtx = idx_to_vtx_positions[idx][0]
                
                # Calculate offset exactly like mesh_attribute_printer does
                # mesh_attribute_printer uses: attr.offset + postvs.vertexByteStride * vtx
                # where attr.offset = postvs.vertexByteOffset + accum_offset
                offset = texcoord0_offset + postvs.vertexByteStride * vtx
                
                uv_value = (0.0, 0.0)
                if offset < len(output_buffer):
                    value = self._unpack_data(texcoord0_attr.format, output_buffer, offset)
                    if value and len(value) >= 2:
                        uv_value = (float(value[0]), float(value[1]))
                        print("  IDX {} (VTX {}): UV = ({}, {})".format(idx, vtx, uv_value[0], uv_value[1]))
                
                uv_data_by_idx[idx] = uv_value
        else:
            print("TEXCOORD0 not found, skipping UV data")
        
        # Sort vertices by IDX and create vertex list
        sorted_indices = sorted(vertex_data_by_idx.keys())
        vertices = [vertex_data_by_idx[idx] for idx in sorted_indices]
        
        # Create index mapping: IDX -> vertex index in sorted list (0-based)
        idx_to_vertex_idx = {idx: i for i, idx in enumerate(sorted_indices)}
        
        # Create display indices: for each IDX in the original index array, map to vertex index
        # This preserves the triangle structure (3 IDX per triangle)
        display_indices = [idx_to_vertex_idx[indices[i]] for i in range(num_indices)]
        
        # Create raw_uv_data in the same order as sorted vertices (by IDX)
        raw_uv_data = []
        for idx in sorted_indices:
            if idx in uv_data_by_idx:
                raw_uv_data.append(uv_data_by_idx[idx])
            else:
                raw_uv_data.append((0.0, 0.0))
        
        return vertices, display_indices, raw_uv_data
    
    def _get_indices(self, controller: rd.ReplayController, ib: rd.BufferDescription,
                    action: rd.ActionDescription) -> List[int]:
        """Get indices from index buffer"""
        if ib.resourceId == rd.ResourceId.Null() or not (action.flags & rd.ActionFlags.Indexed):
            # No index buffer, generate sequential indices
            return list(range(action.numIndices))
        
        # Determine format
        if ib.byteStride == 2:
            index_fmt = 'H'
        elif ib.byteStride == 4:
            index_fmt = 'I'
        else:
            index_fmt = 'B'
        
        # Get entire index buffer at once
        offset = ib.byteOffset + action.indexOffset * ib.byteStride
        index_data = controller.GetBufferData(ib.resourceId, offset, ib.byteStride * action.numIndices)
        
        # Batch unpack all indices
        num_indices = action.numIndices
        indices = []
        base_vertex = action.baseVertex
        
        for i in range(num_indices):
            idx_offset = i * ib.byteStride
            if idx_offset + ib.byteStride <= len(index_data):
                idx = struct.unpack_from('=' + index_fmt, index_data, idx_offset)[0]
                indices.append(idx + base_vertex)
            else:
                indices.append(i)
        
        return indices
    
    def _get_indices_from_mesh(self, controller: rd.ReplayController, mesh: rd.MeshFormat) -> List[int]:
        """Get indices from mesh format"""
        if mesh.indexResourceId == rd.ResourceId.Null():
            return list(range(mesh.numIndices))
        
        # Determine format
        if mesh.indexByteStride == 2:
            index_fmt = 'H'
        elif mesh.indexByteStride == 4:
            index_fmt = 'I'
        else:
            index_fmt = 'B'
        
        # Get entire index buffer at once
        index_data = controller.GetBufferData(
            mesh.indexResourceId,
            mesh.indexByteOffset,
            mesh.indexByteStride * mesh.numIndices
        )
        
        # Batch unpack all indices
        num_indices = mesh.numIndices
        indices = []
        base_vertex = mesh.baseVertex
        
        for i in range(num_indices):
            idx_offset = i * mesh.indexByteStride
            if idx_offset + mesh.indexByteStride <= len(index_data):
                idx = struct.unpack_from('=' + index_fmt, index_data, idx_offset)[0]
                indices.append(idx + base_vertex)
            else:
                indices.append(i)
        
        return indices
    
    def _get_vertex_attribute(self, controller: rd.ReplayController,
                              attr: rd.VertexInputAttribute, vbs: List[rd.BoundVBuffer],
                              action: rd.ActionDescription, idx: int) -> Optional[Tuple]:
        """Get a vertex attribute value from VS input"""
        if attr.vertexBuffer >= len(vbs):
            return None
        
        vb = vbs[attr.vertexBuffer]
        # Calculate offset: base buffer offset + attribute offset + vertex stride * index
        offset = (vb.byteOffset + attr.byteOffset + 
                 vb.byteStride * (idx + action.vertexOffset))
        
        data = controller.GetBufferData(vb.resourceId, offset, 0)
        return self._unpack_data(attr.format, data, 0)
    
    def _unpack_data(self, fmt: rd.ResourceFormat, data: bytes, 
                    data_offset: int) -> Optional[Tuple]:
        """Unpack data from buffer using format"""
        if fmt.Special():
            return None
        
        format_chars = {
            rd.CompType.UInt:  "xBHxIxxxQ",
            rd.CompType.SInt:  "xbhxixxxq",
            rd.CompType.Float: "xxexfxxxd",
        }
        
        format_chars[rd.CompType.UNorm] = format_chars[rd.CompType.UInt]
        format_chars[rd.CompType.UScaled] = format_chars[rd.CompType.UInt]
        format_chars[rd.CompType.SNorm] = format_chars[rd.CompType.SInt]
        format_chars[rd.CompType.SScaled] = format_chars[rd.CompType.SInt]
        
        vertex_format = '=' + str(fmt.compCount) + format_chars[fmt.compType][fmt.compByteWidth]
        
        if data_offset >= len(data):
            return None
        
        try:
            value = struct.unpack_from(vertex_format, data, data_offset)
        except struct.error:
            return None
        
        # Post-process normalized values
        if fmt.compType == rd.CompType.UNorm:
            divisor = float((1 << (fmt.compByteWidth*8)) - 1)
            value = tuple(float(i) / divisor for i in value)
        elif fmt.compType == rd.CompType.SNorm:
            max_neg = -(1 << (fmt.compByteWidth*8 - 1))
            divisor = -float(max_neg+1)
            value = tuple(-1.0 if (i == max_neg) else float(i / divisor) for i in value)
        elif fmt.compType in (rd.CompType.UScaled, rd.CompType.SScaled):
            value = tuple(float(i) for i in value)
        
        # Handle BGRA order
        if fmt.BGRAOrder():
            value = tuple(value[i] for i in [2, 1, 0, 3])
        
        return value
    
    def _write_fbx(self, file_path: str, vertices: List[Dict], indices: List[int], 
                   raw_uv_data: Optional[List[Tuple]] = None):
        """Write mesh data to FBX file (ASCII format)
        
        Args:
            vertices: List of unique vertices (sorted by IDX)
            indices: Display indices mapping to vertices
            raw_uv_data: Optional list of UV data in original polygon vertex order
        """
        if len(vertices) == 0:
            raise RuntimeError("No vertices to export")
        
        # For FBX, vertices list is already in the correct order (matching indices)
        # indices should be 0, 1, 2, ... (display indices from VTX)
        # Each vertex in vertices list corresponds to one polygon vertex
        # NO DEDUPLICATION - we need all vertices, even if they have the same position
        
        # vertices list is already in the order of indices
        # Each index in indices corresponds to vertices[index]
        # So we can use vertices directly and indices as-is
        
        # Ensure vertices list has enough entries
        max_idx = max(indices) if indices else 0
        if max_idx >= len(vertices):
            # Pad vertices if needed
            while len(vertices) <= max_idx:
                vertices.append({'position': (0.0, 0.0, 0.0)})
        
        # Use vertices directly - no deduplication
        vertex_list = vertices
        normalized_indices = indices
        
        with open(file_path, 'w', encoding='utf-8') as f:
            # Write FBX header
            f.write("; FBX 7.4.0 project file\n")
            f.write("; Created by RenderDoc Mesh to FBX Exporter\n")
            f.write("; ----------------------------------------------------\n\n")
            
            # Write FBX version
            f.write("FBXHeaderExtension:  {\n")
            f.write("\tFBXHeaderVersion: 1003\n")
            f.write("\tFBXVersion: 7400\n")
            f.write("}\n\n")
            
            # Write definitions
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
            
            # Write objects
            f.write("Objects:  {\n")
            
            # Write geometry
            f.write("\tGeometry: 1000, \"Geometry::\", \"Mesh\" {\n")
            f.write("\t\tProperties70:  {\n")
            f.write("\t\t\tP: \"Color\", \"ColorRGB\", \"Color\", \"\",0.8,0.8,0.8\n")
            f.write("\t\t}\n")
            
            # Write vertices (no deduplication - each vertex is preserved)
            vertex_data = []
            for v in vertex_list:
                pos = v.get('position', (0.0, 0.0, 0.0))
                vertex_data.extend([float(pos[0]), float(pos[1]), float(pos[2]) if len(pos) > 2 else 0.0])
            
            f.write("\t\tVertices: *{} {{\n".format(len(vertex_data)))
            f.write("\t\t\ta: ")
            f.write(",".join("{:.6f}".format(x) for x in vertex_data))
            f.write("\n")
            f.write("\t\t}\n")
            
            # Write polygon vertex indices
            # FBX uses negative indices (idx ^ -1 = -(idx + 1)) to mark end of polygon
            # For triangle list, we need to mark every 3rd index as negative
            polygon_indices = []
            for i, idx in enumerate(normalized_indices):
                # Every 3rd index (i % 3 == 2) should be negative to mark triangle end
                # FBX format: negative index = -(idx + 1) to mark end of polygon
                if i % 3 == 2:
                    polygon_indices.append(-(idx + 1))  # Fixed: use -(idx + 1) instead of idx ^ -1
                else:
                    polygon_indices.append(idx)
            
            f.write("\t\tPolygonVertexIndex: *{} {{\n".format(len(polygon_indices)))
            f.write("\t\t\ta: ")
            f.write(",".join(str(i) for i in polygon_indices))
            f.write("\n")
            f.write("\t\t}\n")
            
            # Write edges (empty for now)
            f.write("\t\tEdges: *0 {\n")
            f.write("\t\t\ta: \n")
            f.write("\t\t}\n")
            
            # Write GeometryVersion
            f.write("\t\tGeometryVersion: 124\n")
            
            # Write UV data using ByControlPoint mapping
            if raw_uv_data and len(raw_uv_data) > 0:
                # Prepare UV data list
                # Since ByControlPoint maps one-to-one with vertices, we just flatten the raw_uv_data
                uv_data_flat = []
                for uv in raw_uv_data:
                    # Flip V coordinate (FBX convention)
                    # Ensure we have valid float values
                    u = float(uv[0]) if uv else 0.0
                    v = float(uv[1]) if uv and len(uv) > 1 else 0.0
                    uv_data_flat.extend([u, 1.0 - v])
                
                f.write("\t\tLayerElementUV: 0 {\n")
                f.write("\t\t\tVersion: 101\n")
                f.write("\t\t\tName: \"map1\"\n")
                f.write("\t\t\tMappingInformationType: \"ByControlPoint\"\n")
                f.write("\t\t\tReferenceInformationType: \"Direct\"\n")
                f.write("\t\t\tUV: *{} {{\n".format(len(uv_data_flat)))
                f.write("\t\t\t\ta: ")
                f.write(",".join("{:.6f}".format(x) for x in uv_data_flat))
                f.write("\n")
                f.write("\t\t\t}\n")
                f.write("\t\t}\n")
            
            # Write layer
            f.write("\t\tLayer: 0 {\n")
            f.write("\t\t\tVersion: 100\n")
            if raw_uv_data and len(raw_uv_data) > 0:
                f.write("\t\t\tLayerElement:  {\n")
                f.write("\t\t\t\tType: \"LayerElementUV\"\n")
                f.write("\t\t\t\tTypedIndex: 0\n")
                f.write("\t\t\t}\n")
            f.write("\t\t}\n")
            
            f.write("\t}\n")
            
            # Write model
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
            
            # Write connections
            # Connect Model to RootNode (0), then Geometry to Model
            f.write("Connections:  {\n")
            f.write("\tC: \"OO\",2000,0\n")
            f.write("\tC: \"OO\",1000,2000\n")
            f.write("}\n\n")
            
            # Write footer
            f.write("; End of FBX file\n")

