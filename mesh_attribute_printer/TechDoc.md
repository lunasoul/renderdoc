# RenderDoc Mesh 数据读取方法总结

本文档详细说明了如何在 RenderDoc Python 扩展中分别读取 VS Input 和 VS Output 数据。

---

## 目录

- [前置步骤](#前置步骤)
- [VS Input 数据读取](#vs-input-数据读取)
- [VS Output 数据读取](#vs-output-数据读取)
- [主要区别对比](#主要区别对比)
- [完整代码示例](#完整代码示例)

---

## 前置步骤

在读取任何数据之前，都需要完成以下步骤：

### 1. 设置 Frame Event（关键！）

controller.SetFrameEvent(event_id, True)**重要提示**：这是读取 VS Output 数据的**必需步骤**。如果不先调用 `SetFrameEvent`，`GetPostVSData` 将无法获取到数据。

### 2. 获取 Pipeline State
on
pipe = controller.GetPipelineState()---

## VS Input 数据读取

### 数据来源

VS Input 数据来自**原始顶点缓冲区**（Vertex Buffers），这是应用程序提供给 GPU 的原始顶点数据。

### 读取步骤

#### 步骤 1: 获取顶点输入布局

vbs = pipe.GetVBuffers()          # 顶点缓冲区列表
ib = pipe.GetIBuffer()            # 索引缓冲区
inputs = pipe.GetVertexInputs()   # 顶点输入属性列表#### 步骤 2: 获取索引数据

indices = self._get_indices(controller, ib, action)
# indices 是 IDX 列表，表示每个 VTX 对应的原始缓冲区索引#### 步骤 3: 预读取所有顶点缓冲区
n
vertex_buffers = {}
for vb_idx, vb in enumerate(vbs):
    if vb.resourceId != rd.ResourceId.Null():
        max_idx = max(indices)
        buffer_size = vb.byteOffset + vb.byteStride * (max_idx + action.vertexOffset + 1)
        vertex_buffers[vb_idx] = controller.GetBufferData(vb.resourceId, 0, buffer_size)#### 步骤 4: 按 VTX 顺序读取每个顶点的属性

for vtx in range(num_vertices):
    idx = indices[vtx]  # 获取该 VTX 对应的 IDX
    
    # 对每个输入属性
    for input_attr in inputs:
        vb = vbs[input_attr.vertexBuffer]
        buffer_data = vertex_buffers[input_attr.vertexBuffer]
        
        # 计算该属性在缓冲区中的偏移
        offset = (vb.byteOffset + input_attr.byteOffset + 
                 vb.byteStride * (idx + action.vertexOffset))
        
        # 解包数据
        value = self._unpack_data(input_attr.format, buffer_data, offset)### 关键点

- ✅ 使用 **IDX**（原始缓冲区索引）来定位数据
- ✅ 通过 `vb.byteStride * (idx + action.vertexOffset)` 计算顶点位置
- ✅ 属性偏移 = `vb.byteOffset + input_attr.byteOffset`
- ✅ 数据按 **IDX 顺序**存储，但通过索引缓冲区映射到 VTX

---

## VS Output 数据读取

### 数据来源

VS Output 数据来自 **PostVS 缓冲区**（Post-Vertex Shader），这是顶点着色器处理后的输出数据。

### 读取步骤

#### 步骤 1: 获取 PostVS 数据
n
postvs = controller.GetPostVSData(0, 0, rd.MeshDataStage.VSOut)
# 参数说明：
# - 第一个参数 (0): instance ID（实例索引）
# - 第二个参数 (0): view ID（视图索引，用于多视图渲染）
# - 第三个参数: 数据阶段（VSOut 表示顶点着色器输出）
**注意**：必须在调用 `SetFrameEvent` 之后才能获取到数据！

#### 步骤 2: 获取着色器反射信息
n
vs = pipe.GetShaderReflection(rd.ShaderStage.Vertex)
# 从 outputSignature 获取输出属性信息#### 步骤 3: 构建属性列表（需要过滤和格式化）

attrs = []
for sig in vs.outputSignature:
    # 跳过非光栅化流
    if pipe.GetRasterizedStream() >= 0:
        if sig.stream != pipe.GetRasterizedStream():
            continue
    
    # 跳过输出索引
    if sig.systemValue == rd.ShaderBuiltin.OutputIndices:
        continue
    
    # 创建属性对象
    attr = type('Attr', (), {})()
    attr.name = sig.semanticIdxName if sig.varName == '' else sig.varName
    attr.format = rd.ResourceFormat()
    attr.format.compByteWidth = rd.VarTypeByteSize(sig.varType)
    attr.format.compCount = sig.compCount
    attr.format.compType = rd.VarTypeCompType(sig.varType)
    attr.format.type = rd.ResourceFormatType.Regular
    attrs.append(attr)#### 步骤 4: 计算属性偏移（需要考虑对齐）
on
accum_offset = 0
for attr in attrs:
    fmt = attr.format
    elem_size = (8 if fmt.compByteWidth > 4 else 4)
    alignment = elem_size * 4
    
    # 对齐处理
    if pipe.HasAlignedPostVSData(rd.MeshDataStage.VSOut) and (accum_offset % alignment) != 0:
        padding = alignment - (accum_offset % alignment)
        accum_offset += padding
    
    attr.offset = postvs.vertexByteOffset + accum_offset
    accum_offset += elem_size * fmt.compCount#### 步骤 5: 读取 PostVS 缓冲区

output_buffer_size = postvs.vertexByteOffset + postvs.vertexByteStride * num_vertices
output_buffer = controller.GetBufferData(postvs.vertexResourceId, 0, output_buffer_size)#### 步骤 6: 按 VTX 顺序读取每个顶点的属性
hon
for vtx in range(num_vertices):
    # PostVS 数据按 VTX 顺序存储（0, 1, 2, ...）
    for attr in attrs:
        offset = attr.offset + postvs.vertexByteStride * vtx
        value = self._unpack_data(attr.format, output_buffer, offset)### 关键点

- ✅ 使用 **VTX 索引**（0, 1, 2, ...）来定位数据，PostVS 数据按 VTX 顺序存储
- ✅ 需要**手动计算属性偏移**，考虑对齐规则
- ✅ 通过 `postvs.vertexByteStride * vtx` 计算顶点位置
- ✅ 属性偏移 = `postvs.vertexByteOffset + 计算出的累积偏移`
- ✅ 必须过滤非光栅化流和输出索引

---

## 主要区别对比

| 方面 | VS Input | VS Output |
|------|----------|-----------|
| **数据来源** | 原始顶点缓冲区 | PostVS 缓冲区 |
| **索引方式** | 使用 **IDX**（原始缓冲区索引） | 使用 **VTX**（显示顶点索引，0,1,2...） |
| **获取方式** | `pipe.GetVBuffers()` + `pipe.GetVertexInputs()` | `controller.GetPostVSData()` |
| **属性信息** | `input_attr.format`（直接可用） | 从 `vs.outputSignature` 构建 |
| **偏移计算** | `vb.byteOffset + attr.byteOffset + stride * idx` | `postvs.vertexByteOffset + 计算的偏移 + stride * vtx` |
| **对齐处理** | 不需要 | **需要**（`HasAlignedPostVSData`） |
| **前置条件** | 不需要 SetFrameEvent | **必须**先调用 `SetFrameEvent` |
| **数据顺序** | 按 IDX 顺序（通过索引缓冲区映射） | 按 VTX 顺序（0, 1, 2, ...） |

---

## 完整代码示例

### VS Input 读取示例
n
def read_vs_input(controller, action):
    """读取 VS Input 数据"""
    pipe = controller.GetPipelineState()
    vbs = pipe.GetVBuffers()
    ib = pipe.GetIBuffer()
    inputs = pipe.GetVertexInputs()
    
    # 获取索引
    indices = get_indices(controller, ib, action)
    
    # 预读取缓冲区
    vertex_buffers = {}
    for vb_idx, vb in enumerate(vbs):
        if vb.resourceId != rd.ResourceId.Null():
            max_idx = max(indices)
            buffer_size = vb.byteOffset + vb.byteStride * (max_idx + action.vertexOffset + 1)
            vertex_buffers[vb_idx] = controller.GetBufferData(vb.resourceId, 0, buffer_size)
    
    # 读取顶点数据
    vertices = []
    for vtx in range(len(indices)):
        idx = indices[vtx]
        vertex = {}
        
        for input_attr in inputs:
            if input_attr.vertexBuffer < len(vbs):
                vb = vbs[input_attr.vertexBuffer]
                buffer_data = vertex_buffers.get(input_attr.vertexBuffer, b'')
                offset = (vb.byteOffset + input_attr.byteOffset + 
                         vb.byteStride * (idx + action.vertexOffset))
                
                if offset < len(buffer_data):
                    value = unpack_data(input_attr.format, buffer_data, offset)
                    if value:
                        vertex[input_attr.name] = value
        
        vertices.append(vertex)
    
    return vertices
### VS Output 读取示例
on
def read_vs_output(controller, action):
    """读取 VS Output 数据"""
    # 重要：必须先设置 Frame Event
    controller.SetFrameEvent(action.eventId, True)
    
    # 获取 PostVS 数据
    postvs = controller.GetPostVSData(0, 0, rd.MeshDataStage.VSOut)
    
    if postvs.numIndices == 0:
        return []
    
    # 获取着色器反射
    pipe = controller.GetPipelineState()
    vs = pipe.GetShaderReflection(rd.ShaderStage.Vertex)
    if vs is None:
        return []
    
    # 构建属性列表
    attrs = []
    for sig in vs.outputSignature:
        if pipe.GetRasterizedStream() >= 0:
            if sig.stream != pipe.GetRasterizedStream():
                continue
        
        if sig.systemValue == rd.ShaderBuiltin.OutputIndices:
            continue
        
        attr = create_attribute(sig)
        attrs.append(attr)
    
    # 计算属性偏移
    accum_offset = 0
    for attr in attrs:
        fmt = attr.format
        elem_size = (8 if fmt.compByteWidth > 4 else 4)
        alignment = elem_size * 4
        
        if pipe.HasAlignedPostVSData(rd.MeshDataStage.VSOut) and (accum_offset % alignment) != 0:
            padding = alignment - (accum_offset % alignment)
            accum_offset += padding
        
        attr.offset = postvs.vertexByteOffset + accum_offset
        accum_offset += elem_size * fmt.compCount
    
    # 读取缓冲区
    output_buffer_size = postvs.vertexByteOffset + postvs.vertexByteStride * postvs.numIndices
    output_buffer = controller.GetBufferData(postvs.vertexResourceId, 0, output_buffer_size)
    
    # 读取顶点数据
    vertices = []
    for vtx in range(postvs.numIndices):
        vertex = {}
        
        for attr in attrs:
            offset = attr.offset + postvs.vertexByteStride * vtx
            if offset < len(output_buffer):
                value = unpack_data(attr.format, output_buffer, offset)
                if value:
                    vertex[attr.name] = value
        
        vertices.append(vertex)
    
    return vertices---

## 常见问题

### Q: 为什么 VS Output 读取不到数据？

**A**: 最常见的原因是忘记调用 `SetFrameEvent`。必须在调用 `GetPostVSData` 之前先设置 frame event：
on
controller.SetFrameEvent(event_id, True)  # 必须先调用这个
postvs = controller.GetPostVSData(0, 0, rd.MeshDataStage.VSOut)### Q: VS Output 的属性偏移计算不正确怎么办？

**A**: 确保考虑了对齐规则。使用 `HasAlignedPostVSData` 检查是否需要对齐，并根据数据类型计算正确的对齐大小。

### Q: 如何区分 TEXCOORD0 和其他 TEXCOORD？

**A**: 在 VS Output 中，通过 `sig.semanticIdxName` 或 `sig.varName` 来识别。例如：

attr_name = sig.semanticIdxName if sig.varName == '' else sig.varName
if attr_name.lower() == 'texcoord0' or attr_name.lower() == 'texcoordo':
    # 这是 TEXCOORD0---

## 参考资料

- [RenderDoc 官方文档](https://renderdoc.org/docs/index.html)
- RenderDoc Python API 参考
- `mesh_attribute_printer` 插件源码

---

**最后更新**: 2025年1月