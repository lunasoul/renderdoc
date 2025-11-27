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
            
            # Show export options dialog
            print("Showing export options dialog")
            self._show_export_options_dialog(event_id)
        except Exception as e:
            import traceback
            error_msg = "Error in show_export_dialog: {}\n{}".format(str(e), traceback.format_exc())
            print(error_msg)
            self.ctx.Extensions().ErrorDialog(error_msg, "Export Mesh to FBX Error")
    
    def _show_export_options_dialog(self, event_id: int):
        """Show dialog to select export options"""
        try:
            print("_show_export_options_dialog called with event_id: {}".format(event_id))
            # Use a simple approach: show a question dialog to select export mode
            # Then get file path and export
            
            # Show mode selection dialog
            mode_text = (
                "Select export mode:\n\n"
                "1. VS Input Only - Export vertex shader input attributes\n"
                "2. VS Input Position + VS Output - Use input position with output attributes\n"
                "3. VS Output Only - Export vertex shader output attributes\n\n"
                "Click Yes for VS Input Only, No for Mixed, or Cancel for VS Output Only"
            )
            
            print("Showing question dialog")
            result = self.ctx.Extensions().QuestionDialog(
                mode_text,
                [qrd.DialogButton.Yes, qrd.DialogButton.No, qrd.DialogButton.Cancel],
                "Export Mesh to FBX - Select Mode"
            )
            
            print("Question dialog result: {}".format(result))
            
            # Determine export mode
            if result == qrd.DialogButton.Yes:
                export_mode = ExportMode.VS_INPUT_ONLY
            elif result == qrd.DialogButton.No:
                export_mode = ExportMode.VS_INPUT_POSITION_VS_OUTPUT
            else:  # Cancel or close
                export_mode = ExportMode.VS_OUTPUT_ONLY
            
            print("Selected export mode: {}".format(export_mode))
            
            # Get file path
            print("Showing save file dialog")
            file_path = self.ctx.Extensions().SaveFileName(
                "Export Mesh to FBX",
                "",
                "FBX Files (*.fbx);;All Files (*.*)"
            )
            
            print("File path selected: {}".format(file_path))
            if not file_path:
                print("No file path selected, aborting")
                return
            
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
            
            # Perform export
            print("Starting async export")
            def do_export(r: rd.ReplayController):
                try:
                    print("do_export called in replay thread")
                    self._export_mesh(r, action, export_mode, file_path)
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
            print("AsyncInvoke called")
        except Exception as e:
            import traceback
            error_msg = "Error in _show_export_options_dialog: {}\n{}".format(str(e), traceback.format_exc())
            print(error_msg)
            self.ctx.Extensions().ErrorDialog(error_msg, "Export Mesh to FBX Error")
    
    def _export_mesh(self, controller: rd.ReplayController, action: rd.ActionDescription,
                     export_mode: ExportMode, file_path: str):
        """Export mesh data to FBX file"""
        try:
            event_id = action.eventId
            print("_export_mesh called: event_id={}, mode={}, file={}".format(event_id, export_mode, file_path))
            # Set the event
            print("Setting frame event")
            controller.SetFrameEvent(event_id, True)
            
            # Get mesh data based on export mode
            print("Getting mesh data, mode: {}".format(export_mode))
            vertices = []
            indices = []
            
            if export_mode == ExportMode.VS_INPUT_ONLY:
                print("Getting VS input mesh")
                vertices, indices = self._get_vs_input_mesh(controller, action)
            elif export_mode == ExportMode.VS_INPUT_POSITION_VS_OUTPUT:
                print("Getting mixed mesh")
                vertices, indices = self._get_mixed_mesh(controller, action)
            elif export_mode == ExportMode.VS_OUTPUT_ONLY:
                print("Getting VS output mesh")
                vertices, indices = self._get_vs_output_mesh(controller, action)
            
            print("Got {} vertices and {} indices".format(len(vertices), len(indices)))
            
            # Export to FBX
            print("Writing FBX file")
            self._write_fbx(file_path, vertices, indices)
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
        min_idx = min(sorted_indices) if sorted_indices else 0
        display_indices = [idx_to_vertex_idx[indices[vtx_idx]] - idx_to_vertex_idx[min_idx] for vtx_idx in range(num_indices)]
        
        return vertices, display_indices
    
    def _get_vs_output_mesh(self, controller: rd.ReplayController,
                           action: rd.ActionDescription) -> Tuple[List[Dict], List[int]]:
        """Get VS output mesh data"""
        # Get post-VS data
        postvs = controller.GetPostVSData(0, 0, rd.MeshDataStage.VSOut)
        
        if postvs.numIndices == 0:
            raise RuntimeError("No VS output data available")
        
        # Get VS output attributes
        vs = controller.GetPipelineState().GetShaderReflection(rd.ShaderStage.Vertex)
        if vs is None:
            raise RuntimeError("Could not get vertex shader reflection")
        
        # Build attribute list
        attrs = []
        posidx = -1
        
        for sig in vs.outputSignature:
            attr = MeshAttribute()
            attr.mesh = postvs
            attr.format = rd.ResourceFormat()
            attr.format.compByteWidth = rd.VarTypeByteSize(sig.varType)
            attr.format.compCount = sig.compCount
            attr.format.compType = rd.VarTypeCompType(sig.varType)
            attr.format.type = rd.ResourceFormatType.Regular
            attr.name = sig.semanticIdxName if sig.varName == '' else sig.varName
            
            if sig.systemValue == rd.ShaderBuiltin.Position:
                posidx = len(attrs)
            
            attrs.append(attr)
        
        # Move position to front
        if posidx > 0:
            pos = attrs[posidx]
            del attrs[posidx]
            attrs.insert(0, pos)
        
        # Calculate offsets
        accum_offset = 0
        for attr in attrs:
            fmt = attr.format
            elem_size = (8 if fmt.compByteWidth > 4 else 4)
            alignment = elem_size
            if fmt.compCount == 2:
                alignment = elem_size * 2
            elif fmt.compCount > 2:
                alignment = elem_size * 4
            
            pipe = controller.GetPipelineState()
            if pipe.HasAlignedPostVSData(rd.MeshDataStage.VSOut) and (accum_offset % alignment) != 0:
                accum_offset += alignment - (accum_offset % alignment)
            
            attr.mesh.vertexByteOffset = postvs.vertexByteOffset + accum_offset
            accum_offset += elem_size * fmt.compCount
        
        # Get indices (these are the original buffer indices, IDX)
        indices = self._get_indices_from_mesh(controller, postvs)
        
        # Get entire vertex buffer once
        # PostVS data is in VTX order, so we need buffer size for numIndices vertices
        num_vertices = postvs.numIndices
        buffer_size = postvs.vertexByteOffset + postvs.vertexByteStride * num_vertices
        buffer_data = controller.GetBufferData(postvs.vertexResourceId, 0, buffer_size)
        
        # Pre-calculate which attribute is position
        position_attr_idx = 0  # Position is moved to front
        if posidx > 0:
            position_attr_idx = 0
        
        # Pre-calculate offsets for all attributes
        attr_offsets = []
        for attr in attrs:
            attr_offsets.append(attr.mesh.vertexByteOffset)
        
        # Get vertex data - use IDX as unique vertex identifier (like reference script)
        # PostVS data is stored in VTX order, but we should read by IDX
        # For each unique IDX, find its VTX position and read PostVS data
        vertex_data_by_idx = {}  # {idx: vertex_dict}
        num_indices = len(indices)
        
        # Create mapping: IDX -> list of VTX positions where this IDX appears
        idx_to_vtx_positions = {}
        for vtx in range(num_indices):
            idx = indices[vtx]
            if idx not in idx_to_vtx_positions:
                idx_to_vtx_positions[idx] = []
            idx_to_vtx_positions[idx].append(vtx)
        
        # Get vertex data for each unique IDX
        for idx in idx_to_vtx_positions.keys():
            # Use the first VTX position for this IDX to read PostVS data
            # (all VTX positions for same IDX should have same data)
            vtx = idx_to_vtx_positions[idx][0]
            
            vertex = {}
            
            # Process all attributes - use VTX index to read from PostVS buffer
            for attr_idx, attr in enumerate(attrs):
                offset = attr_offsets[attr_idx] + attr.mesh.vertexByteStride * vtx
                
                if offset < len(buffer_data):
                    value = self._unpack_data(attr.format, buffer_data, offset)
                    if value:
                        # Check if this is position attribute
                        if attr_idx == position_attr_idx:
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
        
        # Create index mapping: IDX -> vertex index in sorted list (0-based)
        idx_to_vertex_idx = {idx: i for i, idx in enumerate(sorted_indices)}
        
        # Create display indices: for each IDX in the original index array, map to vertex index
        # This preserves the triangle structure (3 IDX per triangle)
        display_indices = [idx_to_vertex_idx[indices[i]] for i in range(num_indices)]
        
        return vertices, display_indices
    
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
        
        # Build VS output attributes (excluding position)
        output_attrs = []
        for sig in vs.outputSignature:
            if sig.systemValue == rd.ShaderBuiltin.Position:
                continue  # Skip position, use input instead
            
            attr = MeshAttribute()
            attr.mesh = postvs
            attr.format = rd.ResourceFormat()
            attr.format.compByteWidth = rd.VarTypeByteSize(sig.varType)
            attr.format.compCount = sig.compCount
            attr.format.compType = rd.VarTypeCompType(sig.varType)
            attr.format.type = rd.ResourceFormatType.Regular
            attr.name = sig.semanticIdxName if sig.varName == '' else sig.varName
            output_attrs.append(attr)
        
        # Calculate offsets for output attributes
        accum_offset = 0
        for attr in output_attrs:
            fmt = attr.format
            elem_size = (8 if fmt.compByteWidth > 4 else 4)
            alignment = elem_size
            if fmt.compCount == 2:
                alignment = elem_size * 2
            elif fmt.compCount > 2:
                alignment = elem_size * 4
            
            pipe = controller.GetPipelineState()
            if pipe.HasAlignedPostVSData(rd.MeshDataStage.VSOut) and (accum_offset % alignment) != 0:
                accum_offset += alignment - (accum_offset % alignment)
            
            attr.mesh.vertexByteOffset = postvs.vertexByteOffset + accum_offset
            accum_offset += elem_size * fmt.compCount
        
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
        
        # Pre-calculate output attribute offsets
        output_attr_offsets = []
        for attr in output_attrs:
            output_attr_offsets.append(attr.mesh.vertexByteOffset)
        
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
            for attr_idx, attr in enumerate(output_attrs):
                offset = output_attr_offsets[attr_idx] + attr.mesh.vertexByteStride * vtx
                
                if offset < len(output_buffer):
                    value = self._unpack_data(attr.format, output_buffer, offset)
                    if value:
                        vertex[attr.name] = value
            
            vertex_data_by_idx[idx] = vertex
        
        # Sort vertices by IDX and create vertex list
        sorted_indices = sorted(vertex_data_by_idx.keys())
        vertices = [vertex_data_by_idx[idx] for idx in sorted_indices]
        
        # Create index mapping: IDX -> vertex index in sorted list (0-based)
        idx_to_vertex_idx = {idx: i for i, idx in enumerate(sorted_indices)}
        
        # Create display indices: for each IDX in the original index array, map to vertex index
        # This preserves the triangle structure (3 IDX per triangle)
        display_indices = [idx_to_vertex_idx[indices[i]] for i in range(num_indices)]
        
        return vertices, display_indices
    
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
    
    def _write_fbx(self, file_path: str, vertices: List[Dict], indices: List[int]):
        """Write mesh data to FBX file (ASCII format)"""
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
            
            # Write layer (minimal - no normals or UVs for now)
            f.write("\t\tLayer: 0 {\n")
            f.write("\t\t\tVersion: 100\n")
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

