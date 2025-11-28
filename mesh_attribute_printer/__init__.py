###############################################################################
# Mesh Attribute Printer Extension
#
# This extension prints all vertex attributes from Mesh Viewer to a text file.
###############################################################################

import qrenderdoc as qrd
import renderdoc as rd
from typing import Optional
import os

# Import mesh printer functionality
from .mesh_printer import MeshAttributePrinter

extiface_version = ''
printer: Optional[MeshAttributePrinter] = None


def print_mesh_attributes_callback(ctx: qrd.CaptureContext, data):
    """Callback for the print mesh attributes menu item"""
    global printer
    
    try:
        print("=" * 50)
        print("Print mesh attributes callback called!")
        print("=" * 50)
        
        if printer is None:
            print("Creating new MeshAttributePrinter instance")
            printer = MeshAttributePrinter(ctx)
        
        # Show print dialog
        print("Calling print_mesh_attributes")
        printer.print_mesh_attributes()
    except Exception as e:
        import traceback
        error_msg = "Error in print_mesh_attributes_callback: {}\n{}".format(str(e), traceback.format_exc())
        print(error_msg)
        ctx.Extensions().ErrorDialog(error_msg, "Mesh Attribute Printer Error")


def register(version: str, ctx: qrd.CaptureContext):
    global extiface_version
    extiface_version = version
    
    try:
        print("=" * 50)
        print("Registering Mesh Attribute Printer extension for RenderDoc version {}".format(version))
        print("=" * 50)
        
        # Register menu item in Tools menu
        print("Registering menu item: Tools -> Print Mesh Attributes")
        ctx.Extensions().RegisterWindowMenu(
            qrd.WindowMenu.Tools, 
            ["Print Mesh Attributes"], 
            print_mesh_attributes_callback
        )
        print("Menu item registered successfully")
    except Exception as e:
        import traceback
        error_msg = "Error registering extension: {}\n{}".format(str(e), traceback.format_exc())
        print(error_msg)
        ctx.Extensions().ErrorDialog(error_msg, "Extension Registration Error")


def unregister():
    global printer
    print("Unregistering Mesh Attribute Printer extension")
    
    if printer is not None:
        printer.cleanup()
        printer = None

