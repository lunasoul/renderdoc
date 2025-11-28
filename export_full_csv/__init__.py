###############################################################################
# Export Full CSV Extension
#
# This extension exports VS Input and VS Output to CSV files using RenderDoc's built-in export functionality.
###############################################################################

import qrenderdoc as qrd
import renderdoc as rd
from typing import Optional
import os

extiface_version = ''


def export_full_csv_callback(ctx: qrd.CaptureContext, data):
    """Callback for the export full CSV menu item"""
    try:
        # Check if we have a capture loaded
        if not ctx.HasEventBrowser():
            ctx.Extensions().MessageDialog(
                "No capture loaded. Please open a capture file first.",
                "Export Full CSV"
            )
            return
        
        # Get current selected event
        event_id = ctx.CurSelectedEvent()
        if event_id == 0:
            ctx.Extensions().MessageDialog(
                "No event selected. Please select a drawcall in the Event Browser.",
                "Export Full CSV"
            )
            return
        
        # Get action to verify it's a drawcall
        action = ctx.GetAction(event_id)
        if action is None:
            ctx.Extensions().ErrorDialog(
                "Could not get action for event {}".format(event_id),
                "Export Full CSV Error"
            )
            return
        
        if not (action.flags & (rd.ActionFlags.Drawcall | rd.ActionFlags.MeshDispatch)):
            ctx.Extensions().ErrorDialog(
                "Selected event is not a drawcall",
                "Export Full CSV Error"
            )
            return
        
        # Get base file path for output
        default_path = os.path.join(os.path.expanduser("~"), "mesh_export")
        base_path = ctx.Extensions().SaveFileName(
            "Export Full CSV (Base Path)",
            default_path,
            "CSV Files (*.csv);;All Files (*.*)"
        )
        
        if not base_path:
            return
        
        # Generate 2 CSV file paths
        base_dir = os.path.dirname(base_path)
        base_name = os.path.splitext(os.path.basename(base_path))[0]
        if not base_name:
            base_name = "mesh_export"
        
        vs_input_csv = os.path.join(base_dir, "{}_vs_input.csv".format(base_name))
        vs_output_csv = os.path.join(base_dir, "{}_vs_output.csv".format(base_name))
        
        # Get Mesh Preview (BufferViewer)
        mesh_viewer = ctx.GetMeshPreview()
        if mesh_viewer is None:
            ctx.Extensions().ErrorDialog(
                "Could not get Mesh Preview window",
                "Export Full CSV Error"
            )
            return
        
        # Export using RenderDoc's built-in model data (same as BufferViewer.exportData)
        try:
            from PySide2 import QtWidgets, QtCore
            import time
            
            # Export VS Input
            _export_mesh_stage_to_csv(ctx, mesh_viewer, rd.MeshDataStage.VSIn, vs_input_csv)
            
            # Small delay to ensure UI updates
            time.sleep(0.1)
            
            # Export VS Output
            _export_mesh_stage_to_csv(ctx, mesh_viewer, rd.MeshDataStage.VSOut, vs_output_csv)
            
            ctx.Extensions().MessageDialog(
                "CSV files exported successfully:\n\n"
                "VS Input: {}\n"
                "VS Output: {}".format(vs_input_csv, vs_output_csv),
                "Export Complete"
            )
            
        except ImportError:
            # PySide2 not available
            ctx.Extensions().ErrorDialog(
                "PySide2 is required for this extension. Please ensure PySide2 is installed.",
                "Export Full CSV Error"
            )
        except Exception as e:
            import traceback
            error_msg = "Error exporting CSV: {}\n{}".format(str(e), traceback.format_exc())
            ctx.Extensions().ErrorDialog(error_msg, "Export Full CSV Error")
            
    except Exception as e:
        import traceback
        error_msg = "Error in export_full_csv_callback: {}\n{}".format(str(e), traceback.format_exc())
        ctx.Extensions().ErrorDialog(error_msg, "Export Full CSV Error")


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
    # VSIn uses inTable, VSOut uses out1Table (or out2Table for GS output)
    table_view = None
    if stage == rd.MeshDataStage.VSIn:
        # Find the input table
        tables = widget.findChildren(QtWidgets.QTableView)
        for table in tables:
            if table.objectName() == "inTable":
                table_view = table
                break
    elif stage == rd.MeshDataStage.VSOut:
        # Find the first output table (out1Table for VS output)
        tables = widget.findChildren(QtWidgets.QTableView)
        for table in tables:
            if table.objectName() == "out1Table":
                table_view = table
                break
    else:
        # For other stages, try to find any output table
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
        # Write header (same format as BufferViewer)
        header_parts = []
        for col in range(model.columnCount()):
            header_data = model.headerData(col, QtCore.Qt.Horizontal, QtCore.Qt.DisplayRole)
            header_str = str(header_data) if header_data else ""
            header_parts.append(header_str)
        
        f.write(", ".join(header_parts) + "\n")
        
        # Write data rows (same format as BufferViewer::exportData)
        for row in range(model.rowCount()):
            row_parts = []
            for col in range(model.columnCount()):
                index = model.index(row, col)
                cell_data = model.data(index, QtCore.Qt.DisplayRole)
                cell_str = str(cell_data) if cell_data else ""
                
                # Handle multi-line cells (same as BufferViewer::exportData)
                # Split by newline and quote if multiple lines
                lines = cell_str.split("\n")
                if len(lines) > 1:
                    # Quote the entire cell and escape quotes
                    quoted_lines = []
                    for line in lines:
                        quoted_lines.append(line.strip())
                    cell_str = '"' + "\n".join(quoted_lines).replace('"', '""') + '"'
                
                row_parts.append(cell_str)
            
            f.write(", ".join(row_parts) + "\n")


def register(version: str, ctx: qrd.CaptureContext):
    global extiface_version
    extiface_version = version
    
    try:
        # Register menu item in Tools menu
        ctx.Extensions().RegisterWindowMenu(
            qrd.WindowMenu.Tools, 
            ["Export Full CSV"], 
            export_full_csv_callback
        )
    except Exception as e:
        import traceback
        error_msg = "Error registering extension: {}\n{}".format(str(e), traceback.format_exc())
        ctx.Extensions().ErrorDialog(error_msg, "Extension Registration Error")


def unregister():
    pass

