# Mesh Attribute Printer

RenderDoc Python extension for printing all vertex attributes from Mesh Viewer to a text file.

## Features

This extension prints all vertex attributes from the currently selected drawcall to a text file, including:

- **VS Input Data**: All vertex shader input attributes from vertex buffers
- **VS Output Data**: All vertex shader output attributes (post-vertex-shader data)
- **Detailed Vertex Information**: First 100 vertices with all their attributes
- **Statistics**: Min, max, and average values for each attribute component

## Installation

1. Copy the `mesh_attribute_printer` folder to your RenderDoc extensions directory:
   - **Windows**: `%APPDATA%\renderdoc\plugins\python\`
   - **Linux**: `~/.renderdoc/plugins/python/`
   - **macOS**: `~/Library/Application Support/renderdoc/plugins/python/`

2. Restart RenderDoc

3. The extension will appear in the Tools menu as "Print Mesh Attributes"

## Usage

1. Open a capture file in RenderDoc
2. Select a drawcall in the Event Browser
3. Go to **Tools** → **Print Mesh Attributes**
4. Choose a file path to save the text file
5. The mesh attributes will be printed to the selected file

## Output Format

The output text file contains:

1. **Header Information**: Event ID, action name
2. **VS Input Data Section**:
   - Vertex buffer information
   - Vertex input layout
   - Detailed vertex data (first 100 vertices)
   - Statistics for all vertices
3. **VS Output Data Section**:
   - VS output signature
   - Detailed vertex data (first 100 vertices)
   - Statistics for all vertices

Each vertex entry includes:
- All attribute names and values
- Individual component values
- Component indices

Statistics include:
- Minimum value per component
- Maximum value per component
- Average value per component
- Total count of vertices with each attribute

## Notes

- The extension prints the first 100 vertices in detail to keep the file size manageable
- Statistics are calculated for all vertices
- The output file is in UTF-8 encoding and can be opened with any text editor

