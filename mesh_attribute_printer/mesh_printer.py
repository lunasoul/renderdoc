###############################################################################
# Mesh Attribute Printer Module
#
# Handles printing all vertex attributes from Mesh Viewer to text file
###############################################################################

import qrenderdoc as qrd
import renderdoc as rd
import struct
from typing import List, Dict, Tuple, Optional
import os


class MeshAttributePrinter:
    """Main class for printing mesh attributes to text file"""
    
    def __init__(self, ctx: qrd.CaptureContext):
        self.ctx = ctx
        self.mqt = ctx.Extensions().GetMiniQtHelper()
    
    def cleanup(self):
        """Cleanup resources"""
        pass
    
    def print_mesh_attributes(self):
        """Print all mesh attributes to text file"""
        try:
            print("print_mesh_attributes called")
            
            # Check if we have a capture loaded
            if not self.ctx.HasEventBrowser():
                print("No event browser")
                self.ctx.Extensions().MessageDialog(
                    "No capture loaded. Please open a capture file first.",
                    "Print Mesh Attributes"
                )
                return
            
            # Get current selected event
            event_id = self.ctx.CurSelectedEvent()
            print("Selected event ID: {}".format(event_id))
            if event_id == 0:
                print("No event selected")
                self.ctx.Extensions().MessageDialog(
                    "No event selected. Please select a drawcall in the Event Browser.",
                    "Print Mesh Attributes"
                )
                return
            
            # Get base file path for output (will generate 3 files)
            default_path = os.path.join(os.path.expanduser("~"), "mesh_attributes")
            base_path = self.ctx.Extensions().SaveFileName(
                "Save Mesh Attributes (Base Path)",
                default_path,
                "Text Files (*.txt);;All Files (*.*)"
            )
            
            if not base_path:
                print("User cancelled file selection")
                return
            
            # Generate file paths for CSV and text outputs
            base_dir = os.path.dirname(base_path)
            base_name = os.path.splitext(os.path.basename(base_path))[0]
            if not base_name:
                base_name = "mesh_attributes"
            
            vs_input_csv = os.path.join(base_dir, "{}_vs_input.csv".format(base_name))
            vs_output_csv = os.path.join(base_dir, "{}_vs_output.csv".format(base_name))
            vs_input_path = os.path.join(base_dir, "{}_vs_input.txt".format(base_name))
            vs_output_path = os.path.join(base_dir, "{}_vs_output.txt".format(base_name))
            debug_path = os.path.join(base_dir, "{}_debug.txt".format(base_name))
            
            print("Output file paths:")
            print("  VS Input CSV: {}".format(vs_input_csv))
            print("  VS Output CSV: {}".format(vs_output_csv))
            print("  VS Input TXT: {}".format(vs_input_path))
            print("  VS Output TXT: {}".format(vs_output_path))
            print("  Debug: {}".format(debug_path))
            
            # Get action first (needs to be on UI thread)
            print("Getting action for event {}".format(event_id))
            action = self.ctx.GetAction(event_id)
            if action is None:
                self.ctx.Extensions().ErrorDialog(
                    "Could not get action for event {}".format(event_id),
                    "Print Mesh Attributes Error"
                )
                return
            
            print("Action flags: {}".format(action.flags))
            if not (action.flags & (rd.ActionFlags.Drawcall | rd.ActionFlags.MeshDispatch)):
                self.ctx.Extensions().ErrorDialog(
                    "Selected event is not a drawcall",
                    "Print Mesh Attributes Error"
                )
                return
            
            # Perform print operation in async replay thread
            print("Starting async print operation")
            def do_print(r: rd.ReplayController):
                try:
                    print("do_print called in replay thread")
                    # IMPORTANT: Set frame event before getting PostVS data
                    event_id = action.eventId
                    print("Setting frame event to {}".format(event_id))
                    r.SetFrameEvent(event_id, True)
                    print("Frame event set, now exporting mesh data")
                    self._export_mesh_data_to_csv(r, action, vs_input_csv, vs_output_csv, 
                                                  vs_input_path, vs_output_path, debug_path)
                    print("Export completed successfully")
                    self.mqt.InvokeOntoUIThread(
                        lambda: self.ctx.Extensions().MessageDialog(
                            "Mesh attributes have been exported:\n\n"
                            "VS Input CSV: {}\n"
                            "VS Output CSV: {}\n"
                            "VS Input TXT: {}\n"
                            "VS Output TXT: {}\n"
                            "Debug: {}".format(vs_input_csv, vs_output_csv, 
                                             vs_input_path, vs_output_path, debug_path),
                            "Export Complete"
                        )
                    )
                except Exception as e:
                    import traceback
                    error_msg = "Export failed:\n{}\n{}".format(str(e), traceback.format_exc())
                    print(error_msg)
                    self.mqt.InvokeOntoUIThread(
                        lambda: self.ctx.Extensions().ErrorDialog(
                            error_msg,
                            "Print Mesh Attributes Error"
                        )
                    )
            
            self.ctx.Replay().AsyncInvoke('', do_print)
            print("AsyncInvoke called")
            
            
        except Exception as e:
            import traceback
            error_msg = "Error in print_mesh_attributes: {}\n{}".format(str(e), traceback.format_exc())
            print(error_msg)
            self.ctx.Extensions().ErrorDialog(error_msg, "Print Mesh Attributes Error")
    
    def _export_mesh_data_to_csv(self, controller: rd.ReplayController, 
                                 action: rd.ActionDescription,
                                 vs_input_csv: str, vs_output_csv: str,
                                 vs_input_path: str, vs_output_path: str, debug_path: str):
        """Export mesh data to CSV files (like RenderDoc's export) and convert to text"""
        debug_lines = []
        
        def debug_write(msg):
            """Helper to write debug message"""
            debug_lines.append(msg)
            print(msg)
        
        try:
            debug_write("=== Starting mesh data export ===")
            debug_write("Event ID: {}".format(action.eventId))
            debug_write("Action: {}".format(action.GetName(controller.GetStructuredFile())))
            
            # Export VS Input to CSV
            debug_write("Exporting VS Input to CSV: {}".format(vs_input_csv))
            self._export_vs_input_csv(controller, action, vs_input_csv, debug_write)
            debug_write("VS Input CSV exported successfully")
            
            # Export VS Output to CSV
            debug_write("Exporting VS Output to CSV: {}".format(vs_output_csv))
            self._export_vs_output_csv(controller, action, vs_output_csv, debug_write)
            debug_write("VS Output CSV exported successfully")
            
            # Convert CSV files to text format
            debug_write("Converting CSV files to text format...")
            self._convert_csv_to_text(vs_input_csv, vs_output_csv, vs_input_path, vs_output_path, debug_path, debug_lines)
            debug_write("CSV to text conversion completed")
            
            debug_write("=== Mesh data export completed ===")
                
        except Exception as e:
            import traceback
            error_msg = "Error exporting mesh data: {}\n{}".format(str(e), traceback.format_exc())
            debug_write("ERROR: {}".format(error_msg))
            # Try to write error to debug file
            try:
                with open(debug_path, 'a', encoding='utf-8') as f:
                    f.write("\n\nERROR: {}\n".format(error_msg))
            except:
                pass
            raise
    
    def _print_all_mesh_data(self, controller: rd.ReplayController, 
                            action: rd.ActionDescription, 
                            vs_input_path: str, vs_output_path: str, debug_path: str):
        """Print all mesh data to separate files"""
        debug_lines = []
        
        def debug_write(msg):
            """Helper to write debug message"""
            debug_lines.append(msg)
            print(msg)  # Also print to console for immediate feedback
        
        try:
            debug_write("=== Starting mesh data export ===")
            debug_write("Event ID: {}".format(action.eventId))
            debug_write("Action: {}".format(action.GetName(controller.GetStructuredFile())))
            
            # Print VS Input data to separate file
            debug_write("Writing VS Input data to: {}".format(vs_input_path))
            with open(vs_input_path, 'w', encoding='utf-8') as f:
                f.write("VS INPUT\n")
                f.write("=" * 100 + "\n")
                self._print_vs_input_table(controller, action, f, debug_write)
            debug_write("VS Input data written successfully")
            
            # Print VS Output data to separate file
            debug_write("Writing VS Output data to: {}".format(vs_output_path))
            with open(vs_output_path, 'w', encoding='utf-8') as f:
                f.write("VS OUTPUT\n")
                f.write("=" * 100 + "\n")
                self._print_vs_output_table(controller, action, f, debug_write)
            debug_write("VS Output data written successfully")
            
            # Write debug information to separate file
            debug_write("Writing debug information to: {}".format(debug_path))
            with open(debug_path, 'w', encoding='utf-8') as f:
                f.write("=== Mesh Attribute Printer Debug Information ===\n")
                f.write("Event ID: {}\n".format(action.eventId))
                f.write("Action: {}\n".format(action.GetName(controller.GetStructuredFile())))
                f.write("\n")
                f.write("\n".join(debug_lines))
            debug_write("Debug information written successfully")
            
            debug_write("=== Mesh data export completed ===")
                
        except Exception as e:
            import traceback
            error_msg = "Error writing mesh attributes files: {}\n{}".format(str(e), traceback.format_exc())
            debug_write("ERROR: {}".format(error_msg))
            # Try to write error to debug file
            try:
                with open(debug_path, 'a', encoding='utf-8') as f:
                    f.write("\n\nERROR: {}\n".format(error_msg))
            except:
                pass
            raise
    
    def _export_vs_input_csv(self, controller: rd.ReplayController, 
                            action: rd.ActionDescription, csv_path: str, debug_write):
        """Export VS Input data to CSV file (same format as RenderDoc export)"""
        try:
            pipe = controller.GetPipelineState()
            vbs = pipe.GetVBuffers()
            ib = pipe.GetIBuffer()
            inputs = pipe.GetVertexInputs()
            
            # Get indices
            indices = self._get_indices(controller, ib, action)
            num_vertices = len(indices)
            
            if num_vertices == 0:
                debug_write("No vertices in VS Input")
                return
            
            # Pre-fetch all vertex buffers
            vertex_buffers = {}
            for vb_idx, vb in enumerate(vbs):
                if vb.resourceId != rd.ResourceId.Null():
                    max_idx = max(indices) if indices else 0
                    buffer_size = vb.byteOffset + vb.byteStride * (max_idx + action.vertexOffset + 1)
                    vertex_buffers[vb_idx] = controller.GetBufferData(vb.resourceId, 0, buffer_size)
                else:
                    vertex_buffers[vb_idx] = b''
            
            # Get attribute names (sorted, like RenderDoc)
            attr_names = sorted([inp.name for inp in inputs])
            
            # Build CSV header: VTX, IDX, then each attribute with .x, .y, .z, .w suffixes
            header_parts = ["VTX", "IDX"]
            for attr_name in attr_names:
                # Find the input attribute to get compCount
                input_attr = None
                for inp in inputs:
                    if inp.name == attr_name:
                        input_attr = inp
                        break
                
                if input_attr:
                    comp_count = input_attr.format.compCount
                    if comp_count == 1:
                        header_parts.append(attr_name)
                    else:
                        comp_names = ['x', 'y', 'z', 'w']
                        for i in range(comp_count):
                            header_parts.append("{}.{}".format(attr_name, comp_names[i]))
            
            # Write CSV file
            with open(csv_path, 'w', encoding='utf-8') as f:
                # Write header
                f.write(", ".join(header_parts) + "\n")
                
                # Write each vertex
                for vtx in range(num_vertices):
                    idx = indices[vtx]
                    row_parts = [str(vtx), str(idx)]
                    
                    # Get vertex data for this IDX
                    vertex = {}
                    for input_attr in inputs:
                        if input_attr.vertexBuffer < len(vbs):
                            vb = vbs[input_attr.vertexBuffer]
                            buffer_data = vertex_buffers.get(input_attr.vertexBuffer, b'')
                            offset = (vb.byteOffset + input_attr.byteOffset + 
                                     vb.byteStride * (idx + action.vertexOffset))
                            
                            if offset < len(buffer_data):
                                value = self._unpack_data(input_attr.format, buffer_data, offset)
                                if value:
                                    vertex[input_attr.name] = value
                    
                    # Add attribute values to row
                    for attr_name in attr_names:
                        if attr_name in vertex:
                            value = vertex[attr_name]
                            if isinstance(value, tuple):
                                # Format each component
                                for v in value:
                                    row_parts.append("  {:.5f}".format(float(v)).rstrip())
                            else:
                                row_parts.append(str(value))
                        else:
                            # Missing attribute - add empty values based on compCount
                            input_attr = None
                            for inp in inputs:
                                if inp.name == attr_name:
                                    input_attr = inp
                                    break
                            if input_attr:
                                comp_count = input_attr.format.compCount
                                for _ in range(comp_count):
                                    row_parts.append("")
                    
                    f.write(", ".join(row_parts) + "\n")
            
            debug_write("VS Input CSV exported: {} vertices".format(num_vertices))
            
        except Exception as e:
            import traceback
            error_msg = "Error exporting VS Input CSV: {}\n{}".format(str(e), traceback.format_exc())
            debug_write("ERROR: {}".format(error_msg))
            raise
    
    def _export_vs_output_csv(self, controller: rd.ReplayController,
                             action: rd.ActionDescription, csv_path: str, debug_write):
        """Export VS Output data to CSV file (same format as RenderDoc export)"""
        try:
            # Get PostVS data
            postvs = controller.GetPostVSData(0, 0, rd.MeshDataStage.VSOut)
            
            if postvs.numIndices == 0:
                debug_write("No VS Output data available")
                return
            
            # Get shader reflection
            pipe = controller.GetPipelineState()
            vs = pipe.GetShaderReflection(rd.ShaderStage.Vertex)
            if vs is None:
                debug_write("No vertex shader reflection available")
                return
            
            # Get indices for IDX column
            ib = pipe.GetIBuffer()
            indices = self._get_indices(controller, ib, action)
            num_vertices = postvs.numIndices
            
            # Build attribute list from shader output signature (keep original order for offset calculation)
            attrs = []
            position_attr_idx = -1
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
                attr.name = sig.semanticIdxName if sig.semanticIdxName != '' else sig.varName
                attr.format = rd.ResourceFormat()
                attr.format.compByteWidth = rd.VarTypeByteSize(sig.varType)
                attr.format.compCount = sig.compCount
                attr.format.compType = rd.VarTypeCompType(sig.varType)
                attr.format.type = rd.ResourceFormatType.Regular
                attr.mesh = rd.MeshFormat(postvs)
                
                # Track position attribute index
                if sig.systemValue == rd.ShaderBuiltin.Position:
                    position_attr_idx = len(attrs)
                
                attrs.append(attr)
            
            if len(attrs) == 0:
                debug_write("No output attributes found")
                return
            
            # Calculate attribute offsets using ORIGINAL order (data is stored in original order)
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
            
            # Create display order: Position first (like RenderDoc CSV export)
            attrs_for_reading = list(attrs)  # Keep original order for reading
            display_attrs = list(attrs)  # Copy for display reordering
            if position_attr_idx > 0:
                position_attr = display_attrs[position_attr_idx]
                del display_attrs[position_attr_idx]
                display_attrs.insert(0, position_attr)
            
            # Get output buffer
            output_buffer_size = postvs.vertexByteOffset + postvs.vertexByteStride * num_vertices
            output_buffer = controller.GetBufferData(postvs.vertexResourceId, 0, output_buffer_size)
            
            # Build CSV header: VTX, IDX, then each attribute with .x, .y, .z, .w suffixes
            header_parts = ["VTX", "IDX"]
            for attr in display_attrs:
                comp_count = attr.format.compCount
                if comp_count == 1:
                    header_parts.append(attr.name)
                else:
                    comp_names = ['x', 'y', 'z', 'w']
                    for i in range(comp_count):
                        header_parts.append("{}.{}".format(attr.name, comp_names[i]))
            
            # Write CSV file
            with open(csv_path, 'w', encoding='utf-8') as f:
                # Write header
                f.write(", ".join(header_parts) + "\n")
                
                # Write each vertex
                for vtx in range(num_vertices):
                    idx = indices[vtx] if vtx < len(indices) else vtx
                    row_parts = [str(vtx), str(idx)]
                    
                    # Read attribute values using display order, but lookup offset from original order
                    for display_attr in display_attrs:
                        # Find corresponding attr in original order to get correct offset
                        original_attr = None
                        for orig_attr in attrs_for_reading:
                            if orig_attr.name == display_attr.name:
                                original_attr = orig_attr
                                break
                        
                        if original_attr is None:
                            # Missing attribute - add empty values
                            for _ in range(display_attr.format.compCount):
                                row_parts.append("")
                            continue
                        
                        offset = original_attr.offset + postvs.vertexByteStride * vtx
                        if offset < len(output_buffer):
                            value = self._unpack_data(original_attr.format, output_buffer, offset)
                            if value:
                                # Format each component (with spacing like RenderDoc)
                                for v in value:
                                    row_parts.append("  {:.5f}".format(float(v)).rstrip())
                            else:
                                # Missing value - add empty values
                                for _ in range(original_attr.format.compCount):
                                    row_parts.append("")
                        else:
                            # Out of bounds - add empty values
                            for _ in range(original_attr.format.compCount):
                                row_parts.append("")
                    
                    f.write(", ".join(row_parts) + "\n")
            
            debug_write("VS Output CSV exported: {} vertices".format(num_vertices))
            
        except Exception as e:
            import traceback
            error_msg = "Error exporting VS Output CSV: {}\n{}".format(str(e), traceback.format_exc())
            debug_write("ERROR: {}".format(error_msg))
            raise
    
    def _convert_csv_to_text(self, vs_input_csv: str, vs_output_csv: str,
                            vs_input_path: str, vs_output_path: str, debug_path: str, debug_lines: list):
        """Convert CSV files to text format"""
        import csv
        
        try:
            # Convert VS Input CSV to text
            with open(vs_input_csv, 'r', encoding='utf-8') as csv_file:
                with open(vs_input_path, 'w', encoding='utf-8') as txt_file:
                    txt_file.write("VS INPUT\n")
                    txt_file.write("=" * 100 + "\n")
                    
                    csv_reader = csv.reader(csv_file)
                    for row in csv_reader:
                        # Convert CSV row to tab-separated format
                        txt_file.write("\t".join(row) + "\n")
            
            # Convert VS Output CSV to text
            with open(vs_output_csv, 'r', encoding='utf-8') as csv_file:
                with open(vs_output_path, 'w', encoding='utf-8') as txt_file:
                    txt_file.write("VS OUTPUT\n")
                    txt_file.write("=" * 100 + "\n")
                    
                    csv_reader = csv.reader(csv_file)
                    for row in csv_reader:
                        # Convert CSV row to tab-separated format
                        txt_file.write("\t".join(row) + "\n")
            
            # Write debug information
            with open(debug_path, 'w', encoding='utf-8') as f:
                f.write("=== Mesh Attribute Printer Debug Information ===\n")
                f.write("VS Input CSV: {}\n".format(vs_input_csv))
                f.write("VS Output CSV: {}\n".format(vs_output_csv))
                f.write("\n")
                f.write("\n".join(debug_lines))
            
        except Exception as e:
            import traceback
            error_msg = "Error converting CSV files: {}\n{}".format(str(e), traceback.format_exc())
            debug_lines.append("ERROR: {}".format(error_msg))
            raise
    
    def _print_vs_input_table(self, controller: rd.ReplayController, 
                              action: rd.ActionDescription, f, debug_write=None):
        """Print VS Input data as table (like Mesh Viewer)"""
        if debug_write is None:
            def debug_write(msg):
                pass
        try:
            pipe = controller.GetPipelineState()
            vbs = pipe.GetVBuffers()
            ib = pipe.GetIBuffer()
            inputs = pipe.GetVertexInputs()
            
            # Get indices
            indices = self._get_indices(controller, ib, action)
            num_vertices = len(indices)
            
            if num_vertices == 0:
                f.write("No vertices\n")
                return
            
            # Pre-fetch all vertex buffers
            vertex_buffers = {}
            for vb_idx, vb in enumerate(vbs):
                if vb.resourceId != rd.ResourceId.Null():
                    max_idx = max(indices) if indices else 0
                    buffer_size = vb.byteOffset + vb.byteStride * (max_idx + action.vertexOffset + 1)
                    vertex_buffers[vb_idx] = controller.GetBufferData(vb.resourceId, 0, buffer_size)
                else:
                    vertex_buffers[vb_idx] = b''
            
            # Get attribute names (sorted)
            attr_names = sorted([inp.name for inp in inputs])
            
            # Print header
            header = "VTX\tIDX"
            for attr_name in attr_names:
                header += "\t{}".format(attr_name)
            f.write(header + "\n")
            
            # Print each vertex (in VTX order, which is the order of indices)
            for vtx in range(num_vertices):
                idx = indices[vtx]
                row = "{}\t{}".format(vtx, idx)
                
                # Get vertex data for this IDX
                vertex = {}
                for input_attr in inputs:
                    if input_attr.vertexBuffer < len(vbs):
                        vb = vbs[input_attr.vertexBuffer]
                        buffer_data = vertex_buffers.get(input_attr.vertexBuffer, b'')
                        offset = (vb.byteOffset + input_attr.byteOffset + 
                                 vb.byteStride * (idx + action.vertexOffset))
                        
                        if offset < len(buffer_data):
                            value = self._unpack_data(input_attr.format, buffer_data, offset)
                            if value:
                                vertex[input_attr.name] = value
                
                # Add attribute values to row
                for attr_name in attr_names:
                    if attr_name in vertex:
                        value = vertex[attr_name]
                        if isinstance(value, tuple):
                            # Format as space-separated values
                            row += "\t{}".format(" ".join(["{:.5f}".format(float(v)) for v in value]))
                        else:
                            row += "\t{}".format(value)
                    else:
                        row += "\t"
                
                f.write(row + "\n")
            
        except Exception as e:
            import traceback
            error_msg = "Error printing VS input data: {}\n{}".format(str(e), traceback.format_exc())
            f.write("\nERROR: {}\n".format(error_msg))
            debug_write("ERROR in _print_vs_input_table: {}".format(error_msg))
    
    def _print_vs_output_table(self, controller: rd.ReplayController,
                               action: rd.ActionDescription, f, debug_write=None):
        """Print VS Output data as table (like Mesh Viewer)"""
        if debug_write is None:
            def debug_write(msg):
                pass
        
        try:
            debug_write("_print_vs_output_table: Getting PostVS data for event {}".format(action.eventId))
            
            # Get PostVS data using correct API
            # Parameters: instance (0), view (0), stage (VSOut)
            postvs = controller.GetPostVSData(0, 0, rd.MeshDataStage.VSOut)
            
            debug_write("_print_vs_output_table: PostVS numIndices = {}".format(postvs.numIndices))
            
            if postvs.numIndices == 0:
                f.write("No VS Output data available (numIndices = 0).\n")
                debug_write("_print_vs_output_table: No VS Output data available")
                return
            
            # Get shader reflection
            pipe = controller.GetPipelineState()
            vs = pipe.GetShaderReflection(rd.ShaderStage.Vertex)
            if vs is None:
                f.write("No vertex shader reflection available.\n")
                return
            
            # Get indices for IDX column
            ib = pipe.GetIBuffer()
            indices = self._get_indices(controller, ib, action)
            num_vertices = postvs.numIndices
            
            # Build attribute list from shader output signature (keep original order for offset calculation)
            attrs = []
            position_attr_idx = -1
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
                # Use semanticIdxName (like RenderDoc Mesh Viewer does)
                # Only use varName if semanticIdxName is empty
                attr.name = sig.semanticIdxName if sig.semanticIdxName != '' else sig.varName
                attr.format = rd.ResourceFormat()
                attr.format.compByteWidth = rd.VarTypeByteSize(sig.varType)
                attr.format.compCount = sig.compCount
                attr.format.compType = rd.VarTypeCompType(sig.varType)
                attr.format.type = rd.ResourceFormatType.Regular
                attr.mesh = rd.MeshFormat(postvs)
                # Store original signature info for debugging
                attr._sig_varName = sig.varName
                attr._sig_semanticIdxName = sig.semanticIdxName
                attr._sig_semanticName = sig.semanticName
                
                # Track position attribute index
                if sig.systemValue == rd.ShaderBuiltin.Position:
                    position_attr_idx = len(attrs)
                
                attrs.append(attr)
            
            if len(attrs) == 0:
                f.write("No output attributes found.\n")
                return
            
            # Calculate attribute offsets using ORIGINAL order (data is stored in original order)
            # IMPORTANT: PostVS buffer data is stored in shader output signature order, NOT display order
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
            
            # Create display order: Position first (like RenderDoc CSV export)
            # But we need to keep original order for reading, so create a mapping
            display_attrs = list(attrs)  # Copy for display
            if position_attr_idx > 0:
                position_attr = display_attrs[position_attr_idx]
                del display_attrs[position_attr_idx]
                display_attrs.insert(0, position_attr)
            
            # Use display order for output, but original order (attrs) for reading
            attrs_for_reading = attrs  # Original order for reading
            attrs = display_attrs  # Display order for output
            
            # Get output buffer
            output_buffer_size = postvs.vertexByteOffset + postvs.vertexByteStride * num_vertices
            output_buffer = controller.GetBufferData(postvs.vertexResourceId, 0, output_buffer_size)
            
            # Write debug information about attributes to debug file
            debug_write("=== VS Output Attribute Debug Info ===")
            debug_write("Total attributes: {}".format(len(attrs_for_reading)))
            debug_write("vertexByteOffset: {}".format(postvs.vertexByteOffset))
            debug_write("vertexByteStride: {}".format(postvs.vertexByteStride))
            debug_write("numIndices: {}".format(num_vertices))
            debug_write("\nAttribute details (original order for reading):")
            for i, attr in enumerate(attrs_for_reading):
                debug_write("  [{}] Name: '{}', offset={}, compCount={}, compByteWidth={}, compType={}".format(
                    i, attr.name, attr.offset, attr.format.compCount, 
                    attr.format.compByteWidth, attr.format.compType))
            debug_write("\nAttribute display order:")
            for i, attr in enumerate(display_attrs):
                debug_write("  [{}] Display name: '{}'".format(i, attr.name))
            debug_write("")
            
            # Print header using display order
            header = "VTX\tIDX"
            for attr in display_attrs:
                header += "\t{}".format(attr.name)
            f.write(header + "\n")
            
            # Print each vertex (in VTX order)
            for vtx in range(num_vertices):
                # Get IDX for this VTX (if available)
                idx = indices[vtx] if vtx < len(indices) else vtx
                row = "{}\t{}".format(vtx, idx)
                
                # Read attribute values using display order, but lookup offset from original order
                for display_attr in attrs:
                    # Find corresponding attr in original order to get correct offset
                    original_attr = None
                    for orig_attr in attrs_for_reading:
                        if orig_attr.name == display_attr.name:
                            original_attr = orig_attr
                            break
                    
                    if original_attr is None:
                        row += "\t"
                        continue
                    
                    offset = original_attr.offset + postvs.vertexByteStride * vtx
                    if offset < len(output_buffer):
                        value = self._unpack_data(original_attr.format, output_buffer, offset)
                        if value:
                            # Format as space-separated values
                            row += "\t{}".format(" ".join(["{:.5f}".format(float(v)) for v in value]))
                            
                            # Debug: Write first vertex's raw data for TEXCOORD0
                            if vtx == 0 and 'TEXCOORD0' in display_attr.name.upper():
                                debug_write("=== Debug: First vertex TEXCOORD0 ===")
                                debug_write("Attribute name: '{}'".format(display_attr.name))
                                debug_write("Original offset: {}".format(original_attr.offset))
                                debug_write("Read offset: {}".format(offset))
                                debug_write("Raw value: {}".format(value))
                                debug_write("Formatted: {}".format(" ".join(["{:.5f}".format(float(v)) for v in value])))
                                debug_write("")
                        else:
                            row += "\t"
                    else:
                        row += "\t"
                
                f.write(row + "\n")
            
        except Exception as e:
            import traceback
            error_msg = "Error printing VS output data: {}\n{}".format(str(e), traceback.format_exc())
            f.write("\nERROR: {}\n".format(error_msg))
            debug_write("ERROR in _print_vs_output_table: {}".format(error_msg))
    
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
    
    def _format_to_string(self, fmt: rd.ResourceFormat) -> str:
        """Convert format to string representation"""
        type_names = {
            rd.CompType.UInt: "UInt",
            rd.CompType.SInt: "SInt",
            rd.CompType.Float: "Float",
            rd.CompType.UNorm: "UNorm",
            rd.CompType.SNorm: "SNorm",
            rd.CompType.UScaled: "UScaled",
            rd.CompType.SScaled: "SScaled",
        }
        
        comp_type = type_names.get(fmt.compType, "Unknown")
        return "{}[{}] x{} bytes".format(comp_type, fmt.compCount, fmt.compByteWidth)

