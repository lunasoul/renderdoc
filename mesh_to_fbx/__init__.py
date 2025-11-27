###############################################################################
# Mesh to FBX Exporter Extension
#
# This extension exports mesh data from RenderDoc's Mesh Viewer to FBX format.
# Supports three export modes:
# 1. VS Input only
# 2. VS Input position + VS Output attributes
# 3. VS Output only
###############################################################################

import qrenderdoc as qrd
import renderdoc as rd
from typing import Optional, List, Dict, Tuple
import struct

# Import mesh export functionality
from .mesh_export import MeshExporter

extiface_version = ''
exporter: Optional[MeshExporter] = None


def export_mesh_callback(ctx: qrd.CaptureContext, data):
    """Callback for the export mesh menu item"""
    global exporter
    
    try:
        print("=" * 50)
        print("Export mesh callback called!")
        print("=" * 50)
        
        # First, show a simple message to confirm callback is working
        ctx.Extensions().MessageDialog(
            "Export Mesh to FBX callback triggered!\n\nThis confirms the menu item is working.",
            "Export Mesh to FBX - Test"
        )
        
        if exporter is None:
            print("Creating new MeshExporter instance")
            exporter = MeshExporter(ctx)
        
        # Show export dialog
        print("Calling show_export_dialog")
        exporter.show_export_dialog()
    except Exception as e:
        import traceback
        error_msg = "Error in export_mesh_callback: {}\n{}".format(str(e), traceback.format_exc())
        print(error_msg)
        ctx.Extensions().ErrorDialog(error_msg, "Export Mesh to FBX Error")


def register(version: str, ctx: qrd.CaptureContext):
    global extiface_version
    extiface_version = version
    
    try:
        print("=" * 50)
        print("Registering Mesh to FBX Exporter extension for RenderDoc version {}".format(version))
        print("=" * 50)
        
        # Register menu item in Tools menu
        print("Registering menu item: Tools -> Export Mesh to FBX")
        ctx.Extensions().RegisterWindowMenu(
            qrd.WindowMenu.Tools, 
            ["Export Mesh to FBX"], 
            export_mesh_callback
        )
        print("Menu item registered successfully")
    except Exception as e:
        import traceback
        error_msg = "Error registering extension: {}\n{}".format(str(e), traceback.format_exc())
        print(error_msg)
        ctx.Extensions().ErrorDialog(error_msg, "Extension Registration Error")


def unregister():
    global exporter
    print("Unregistering Mesh to FBX Exporter extension")
    
    if exporter is not None:
        exporter.cleanup()
        exporter = None

