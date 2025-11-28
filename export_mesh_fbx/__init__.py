###############################################################################
# Export Mesh to FBX Extension
#
# This extension exports VS Input and VS Output to CSV files, then builds FBX from CSV data.
###############################################################################

import qrenderdoc as qrd
import renderdoc as rd
import os
import csv
import tempfile

extiface_version = ''


def export_mesh_fbx_callback(ctx: qrd.CaptureContext, data):
    """Callback for the export mesh to FBX menu item"""
    try:
        # Check if we have a capture loaded
        if not ctx.HasEventBrowser():
            ctx.Extensions().MessageDialog(
                "No capture loaded. Please open a capture file first.",
                "Export Mesh to FBX"
            )
            return
        
        # Get current selected event
        event_id = ctx.CurSelectedEvent()
        if event_id == 0:
            ctx.Extensions().MessageDialog(
                "No event selected. Please select a drawcall in the Event Browser.",
                "Export Mesh to FBX"
            )
            return
        
        # Get action to verify it's a drawcall
        action = ctx.GetAction(event_id)
        if action is None:
            ctx.Extensions().ErrorDialog(
                "Could not get action for event {}".format(event_id),
                "Export Mesh to FBX Error"
            )
            return
        
        if not (action.flags & (rd.ActionFlags.Drawcall | rd.ActionFlags.MeshDispatch)):
            ctx.Extensions().ErrorDialog(
                "Selected event is not a drawcall",
                "Export Mesh to FBX Error"
            )
            return
        
        # Get FBX file path
        default_path = os.path.join(os.path.expanduser("~"), "mesh_export.fbx")
        fbx_path = ctx.Extensions().SaveFileName(
            "Export Mesh to FBX",
            default_path,
            "FBX Files (*.fbx);;All Files (*.*)"
        )
        
        if not fbx_path:
            return
        
        # Get Mesh Preview (BufferViewer)
        mesh_viewer = ctx.GetMeshPreview()
        if mesh_viewer is None:
            ctx.Extensions().ErrorDialog(
                "Could not get Mesh Preview window",
                "Export Mesh to FBX Error"
            )
            return
        
        # Export using RenderDoc's built-in model data
        try:
            from PySide2 import QtWidgets, QtCore
            import time
            
            # Create temporary CSV files
            base_dir = os.path.dirname(fbx_path)
            base_name = os.path.splitext(os.path.basename(fbx_path))[0]
            if not base_name:
                base_name = "mesh_export"
            
            vs_input_csv = os.path.join(base_dir, "{}_vs_input.csv".format(base_name))
            vs_output_csv = os.path.join(base_dir, "{}_vs_output.csv".format(base_name))
            
            # Step 1: Export VS Input CSV
            _export_mesh_stage_to_csv(ctx, mesh_viewer, rd.MeshDataStage.VSIn, vs_input_csv)
            time.sleep(0.1)
            
            # Step 2: Export VS Output CSV
            _export_mesh_stage_to_csv(ctx, mesh_viewer, rd.MeshDataStage.VSOut, vs_output_csv)
            time.sleep(0.1)
            
            # Step 3: Parse CSV files and build FBX
            _build_fbx_from_csv(vs_input_csv, vs_output_csv, fbx_path)
            
            ctx.Extensions().MessageDialog(
                "FBX file exported successfully:\n\n"
                "FBX: {}\n\n"
                "CSV files (for reference):\n"
                "VS Input: {}\n"
                "VS Output: {}".format(fbx_path, vs_input_csv, vs_output_csv),
                "Export Complete"
            )
            
        except ImportError:
            ctx.Extensions().ErrorDialog(
                "PySide2 is required for this extension. Please ensure PySide2 is installed.",
                "Export Mesh to FBX Error"
            )
        except Exception as e:
            import traceback
            error_msg = "Error exporting FBX: {}\n{}".format(str(e), traceback.format_exc())
            ctx.Extensions().ErrorDialog(error_msg, "Export Mesh to FBX Error")
            
    except Exception as e:
        import traceback
        error_msg = "Error in export_mesh_fbx_callback: {}\n{}".format(str(e), traceback.format_exc())
        ctx.Extensions().ErrorDialog(error_msg, "Export Mesh to FBX Error")


def _export_mesh_stage_to_csv(ctx: qrd.CaptureContext, mesh_viewer, 
                              stage: rd.MeshDataStage, csv_path: str):
    """Export mesh data for a specific stage to CSV file using RenderDoc's BufferItemModel"""
    from PySide2 import QtWidgets, QtCore
    import time
    
    # Switch to the specified stage
    mesh_viewer.ShowMeshData(stage)
    
    # Small delay to ensure UI updates and model is populated
    time.sleep(0.1)
    
    # Process events to ensure UI updates
    QtWidgets.QApplication.processEvents()
    
    # Get the widget and access BufferItemModel through PySide2
    widget = mesh_viewer.Widget()
    
    # Find the table view for this stage
    table_view = None
    if stage == rd.MeshDataStage.VSIn:
        tables = widget.findChildren(QtWidgets.QTableView)
        for table in tables:
            if table.objectName() == "inTable":
                table_view = table
                break
    elif stage == rd.MeshDataStage.VSOut:
        tables = widget.findChildren(QtWidgets.QTableView)
        for table in tables:
            if table.objectName() == "out1Table":
                table_view = table
                break
    else:
        tables = widget.findChildren(QtWidgets.QTableView)
        for table in tables:
            if table.objectName() in ["out1Table", "out2Table"]:
                table_view = table
                break
    
    if table_view is None:
        raise RuntimeError("Could not find table view for stage {}".format(stage))
    
    # Get the model (should be BufferItemModel)
    model = table_view.model()
    if model is None:
        raise RuntimeError("Table view has no model")
    
    # Export to CSV using the model's data (same logic as BufferViewer::exportData)
    with open(csv_path, 'w', encoding='utf-8') as f:
        # Write header
        header_parts = []
        for col in range(model.columnCount()):
            header_data = model.headerData(col, QtCore.Qt.Horizontal, QtCore.Qt.DisplayRole)
            header_str = str(header_data) if header_data else ""
            header_parts.append(header_str)
        
        f.write(", ".join(header_parts) + "\n")
        
        # Write data rows
        for row in range(model.rowCount()):
            row_parts = []
            for col in range(model.columnCount()):
                index = model.index(row, col)
                cell_data = model.data(index, QtCore.Qt.DisplayRole)
                cell_str = str(cell_data) if cell_data else ""
                
                # Handle multi-line cells
                lines = cell_str.split("\n")
                if len(lines) > 1:
                    quoted_lines = []
                    for line in lines:
                        quoted_lines.append(line.strip())
                    cell_str = '"' + "\n".join(quoted_lines).replace('"', '""') + '"'
                
                row_parts.append(cell_str)
            
            f.write(", ".join(row_parts) + "\n")


def _build_fbx_from_csv(vs_input_csv: str, vs_output_csv: str, fbx_path: str):
    """Build FBX file from CSV data"""
    # Parse VS Output CSV to get positions and UVs
    vertices = []
    indices = []
    uv_data = []
    
    # Find position and UV columns in VS Output
    position_cols = [-1, -1, -1, -1]  # SV_Position.x, SV_Position.y, SV_Position.z, SV_Position.w
    texcoord_cols = [-1, -1]  # TEXCOORD0.x, TEXCOORD0.y
    vtx_col = -1
    idx_col = -1
    
    with open(vs_output_csv, 'r', encoding='utf-8') as f:
        # Read the file content first to handle potential encoding issues
        content = f.read()
        # Remove BOM if present
        if content.startswith('\ufeff'):
            content = content[1:]
        
        # Parse CSV manually to handle edge cases
        lines = content.split('\n')
        if len(lines) < 2:
            raise RuntimeError("CSV file has no data rows")
        
        # Parse header manually (handle quoted strings)
        header_line = lines[0]
        header = []
        current_field = ""
        in_quotes = False
        for char in header_line:
            if char == '"':
                in_quotes = not in_quotes
            elif char == ',' and not in_quotes:
                header.append(current_field.strip())
                current_field = ""
            else:
                current_field += char
        if current_field or in_quotes:
            header.append(current_field.strip())
        
        # Find column indices
        for i, col_name in enumerate(header):
            col_name = col_name.strip().strip('"')
            if col_name == "VTX":
                vtx_col = i
            elif col_name == "IDX":
                idx_col = i
            elif "SV_Position" in col_name:
                if ".x" in col_name or col_name.endswith("x"):
                    position_cols[0] = i
                elif ".y" in col_name or col_name.endswith("y"):
                    position_cols[1] = i
                elif ".z" in col_name or col_name.endswith("z"):
                    position_cols[2] = i
                elif ".w" in col_name or col_name.endswith("w"):
                    position_cols[3] = i
            elif "TEXCOORD0" in col_name:
                if ".x" in col_name or col_name.endswith("x"):
                    texcoord_cols[0] = i
                elif ".y" in col_name or col_name.endswith("y"):
                    texcoord_cols[1] = i
        
        if vtx_col < 0:
            raise RuntimeError("Could not find VTX column in CSV header")
        
        # Helper function to safely convert string to float
        def safe_float(s, default=0.0):
            """Safely convert string to float, handling empty strings and whitespace"""
            if not s:
                return default
            s = s.strip()
            if not s:
                return default
            try:
                return float(s)
            except (ValueError, TypeError):
                return default
        
        # Helper function to safely convert string to int
        def safe_int(s, default=0):
            """Safely convert string to int, handling empty strings and whitespace"""
            if not s:
                return default
            s = s.strip()
            if not s:
                return default
            try:
                return int(float(s))  # Convert via float first to handle "79.0" -> 79
            except (ValueError, TypeError):
                return default
        
        # Helper function to parse CSV row manually
        def parse_csv_row(line):
            """Parse a CSV row, handling quoted fields"""
            row = []
            current_field = ""
            in_quotes = False
            for char in line:
                if char == '"':
                    in_quotes = not in_quotes
                elif char == ',' and not in_quotes:
                    row.append(current_field.strip())
                    current_field = ""
                else:
                    current_field += char
            if current_field or in_quotes:
                row.append(current_field.strip())
            return row
        
        # Read vertex data
        for row_num, line in enumerate(lines[1:], start=2):  # Skip header, start at row 2
            line = line.strip()
            if not line:
                continue
            
            # Parse row manually
            row = parse_csv_row(line)
            if len(row) == 0:
                continue
            
            # Skip rows that don't have enough columns
            if vtx_col < 0 or vtx_col >= len(row):
                continue
            
            # Get VTX and IDX with safe conversion
            vtx_str = row[vtx_col] if vtx_col < len(row) else ""
            idx_str = row[idx_col] if idx_col >= 0 and idx_col < len(row) else ""
            
            # Remove quotes if present
            vtx_str = vtx_str.strip().strip('"')
            idx_str = idx_str.strip().strip('"')
            
            vtx = safe_int(vtx_str, len(vertices))
            idx = safe_int(idx_str, vtx)
            
            # Get position
            pos = (0.0, 0.0, 0.0)
            if position_cols[0] >= 0 and position_cols[0] < len(row):
                try:
                    x_str = row[position_cols[0]] if position_cols[0] < len(row) else ""
                    y_str = row[position_cols[1]] if position_cols[1] >= 0 and position_cols[1] < len(row) else ""
                    z_str = row[position_cols[2]] if position_cols[2] >= 0 and position_cols[2] < len(row) else ""
                    
                    # Remove quotes and whitespace
                    x_str = x_str.strip().strip('"')
                    y_str = y_str.strip().strip('"')
                    z_str = z_str.strip().strip('"')
                    
                    x = safe_float(x_str, 0.0)
                    y = safe_float(y_str, 0.0)
                    z = safe_float(z_str, 0.0)
                    pos = (x, y, z)
                except (ValueError, IndexError, TypeError) as e:
                    pos = (0.0, 0.0, 0.0)
            
            # Get UV
            uv = (0.0, 0.0)
            if texcoord_cols[0] >= 0 and texcoord_cols[0] < len(row):
                try:
                    u_str = row[texcoord_cols[0]] if texcoord_cols[0] < len(row) else ""
                    v_str = row[texcoord_cols[1]] if texcoord_cols[1] >= 0 and texcoord_cols[1] < len(row) else ""
                    
                    # Remove quotes and whitespace
                    u_str = u_str.strip().strip('"')
                    v_str = v_str.strip().strip('"')
                    
                    u = safe_float(u_str, 0.0)
                    v = safe_float(v_str, 0.0)
                    uv = (u, v)
                except (ValueError, IndexError, TypeError) as e:
                    uv = (0.0, 0.0)
            
            # Store vertex data (order by VTX)
            while len(vertices) <= vtx:
                vertices.append({'position': (0.0, 0.0, 0.0), 'uv': (0.0, 0.0)})
            
            vertices[vtx] = {'position': pos, 'uv': uv}
            indices.append(vtx)
            uv_data.append(uv)
    
    if len(vertices) == 0:
        raise RuntimeError("No vertices found in CSV data")
    
    # Write FBX file
    _write_fbx(fbx_path, vertices, indices, uv_data)


def _write_fbx(file_path: str, vertices: list, indices: list, uv_data: list):
    """Write mesh data to FBX file (ASCII format)"""
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
        
        # Write vertices
        vertex_data = []
        for v in vertices:
            pos = v.get('position', (0.0, 0.0, 0.0))
            vertex_data.extend([float(pos[0]), float(pos[1]), float(pos[2]) if len(pos) > 2 else 0.0])
        
        f.write("\t\tVertices: *{} {{\n".format(len(vertex_data)))
        f.write("\t\t\ta: ")
        f.write(",".join("{:.6f}".format(x) for x in vertex_data))
        f.write("\n")
        f.write("\t\t}\n")
        
        # Write polygon vertex indices
        # FBX uses negative indices to mark end of polygon
        polygon_indices = []
        for i, idx in enumerate(indices):
            # Every 3rd index (i % 3 == 2) should be negative to mark triangle end
            if i % 3 == 2:
                polygon_indices.append(-(idx + 1))
            else:
                polygon_indices.append(idx)
        
        f.write("\t\tPolygonVertexIndex: *{} {{\n".format(len(polygon_indices)))
        f.write("\t\t\ta: ")
        f.write(",".join(str(i) for i in polygon_indices))
        f.write("\n")
        f.write("\t\t}\n")
        
        # Write edges (empty)
        f.write("\t\tEdges: *0 {\n")
        f.write("\t\t\ta: \n")
        f.write("\t\t}\n")
        
        # Write GeometryVersion
        f.write("\t\tGeometryVersion: 124\n")
        
        # Write UV data
        if uv_data and len(uv_data) > 0:
            uv_data_flat = []
            for uv in uv_data:
                u = float(uv[0]) if uv else 0.0
                v = float(uv[1]) if uv and len(uv) > 1 else 0.0
                # Flip V coordinate (FBX convention)
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
        if uv_data and len(uv_data) > 0:
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
        f.write("Connections:  {\n")
        f.write("\tC: \"OO\",2000,0\n")
        f.write("\tC: \"OO\",1000,2000\n")
        f.write("}\n\n")
        
        # Write footer
        f.write("; End of FBX file\n")


def register(version: str, ctx: qrd.CaptureContext):
    global extiface_version
    extiface_version = version
    
    try:
        # Register menu item in Tools menu
        ctx.Extensions().RegisterWindowMenu(
            qrd.WindowMenu.Tools, 
            ["Export Mesh to FBX"], 
            export_mesh_fbx_callback
        )
    except Exception as e:
        import traceback
        error_msg = "Error registering extension: {}\n{}".format(str(e), traceback.format_exc())
        ctx.Extensions().ErrorDialog(error_msg, "Extension Registration Error")


def unregister():
    pass

