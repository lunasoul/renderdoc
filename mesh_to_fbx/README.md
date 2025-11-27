# Mesh to FBX Exporter

RenderDoc Python extension for exporting mesh data from Mesh Viewer to FBX format.

## Features

This extension allows you to export mesh data from RenderDoc's Mesh Viewer to FBX format with three different export modes:

1. **VS Input Only** - Exports vertex shader input attributes (raw vertex buffer data)
2. **VS Input Position + VS Output** - Uses vertex shader input position combined with vertex shader output attributes
3. **VS Output Only** - Exports vertex shader output attributes (post-vertex-shader data)

## Installation

1. Copy the `mesh_to_fbx` folder to your RenderDoc extensions directory:
   - **Windows**: `%APPDATA%\renderdoc\plugins\python\`
   - **Linux**: `~/.renderdoc/plugins/python/`
   - **macOS**: `~/Library/Application Support/renderdoc/plugins/python/`

2. Restart RenderDoc

3. The extension will appear in the Tools menu as "Export Mesh to FBX"

## Usage

1. Open a capture file in RenderDoc
2. Select a drawcall in the Event Browser
3. Go to **Tools** → **Export Mesh to FBX**
4. Select the export mode:
   - **Yes** for VS Input Only
   - **No** for VS Input Position + VS Output
   - **Cancel** for VS Output Only
5. Choose a file path to save the FBX file
6. The mesh will be exported to the selected location

## Export Modes Explained

### VS Input Only
Exports the raw vertex buffer data as it was provided to the vertex shader. This includes all vertex attributes from the input layout.

### VS Input Position + VS Output
Uses the position from the vertex shader input (original vertex buffer) but combines it with other attributes from the vertex shader output. This is useful when you want the original geometry position but transformed attributes.

### VS Output Only
Exports the vertex shader output data, which includes the position after vertex shader transformation. This is typically what you see in the Mesh Viewer.

## Notes

- The extension exports mesh data in FBX ASCII format
- Only triangle list topology is currently supported
- Default normals (0, 0, 1) are generated if not available
- The extension handles various vertex formats including normalized types

## Requirements

- RenderDoc 1.12 or later
- Python 3.6 or later (included with RenderDoc)

## Limitations

- Currently exports only the first instance in instanced draws
- Does not handle geometry shader output
- Basic FBX format support (no materials, textures, or animations)

