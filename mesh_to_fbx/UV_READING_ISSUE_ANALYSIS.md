# mesh_to_fbx UV 读取错误原因分析

## 问题总结

通过对比 `mesh_attribute_printer`（正确实现）和 `mesh_to_fbx`（有问题的实现），发现了导致 UV 读取错误的几个关键问题。

---

## 关键差异对比

### 1. 属性列表构建时的过滤缺失 ❌

#### `mesh_attribute_printer`（正确）：
```python
for sig in vs.outputSignature:
    # Skip if not on rasterized stream
    if pipe.GetRasterizedStream() >= 0:
        if sig.stream != pipe.GetRasterizedStream():
            continue
    
    # Skip output indices
    if sig.systemValue == rd.ShaderBuiltin.OutputIndices:
        continue
    
    # 创建属性...
    attrs.append(attr)
```

#### `mesh_to_fbx`（错误）：
```python
for sig in vs.outputSignature:
    # ❌ 没有过滤非光栅化流
    # ❌ 没有跳过输出索引
    
    attr = MeshAttribute()
    # ...
    all_attrs.append(attr)  # 包含了所有属性，包括不应该包含的
```

**影响**：这导致 `all_attrs` 包含了不应该包含的属性（非光栅化流、输出索引等），使得后续的偏移计算基于错误的属性列表。

---

### 2. 对齐计算方式不同 ⚠️

#### `mesh_attribute_printer`（正确）：
```python
elem_size = (8 if fmt.compByteWidth > 4 else 4)
alignment = elem_size * 4  # 固定使用 4 倍对齐

if pipe.HasAlignedPostVSData(rd.MeshDataStage.VSOut) and (accum_offset % alignment) != 0:
    padding = alignment - (accum_offset % alignment)
    accum_offset += padding
```

#### `mesh_to_fbx`（可能有问题）：
```python
elem_size = (8 if fmt.compByteWidth > 4 else 4)
alignment = elem_size  # 初始对齐
if fmt.compCount == 2:
    alignment = elem_size * 2
elif fmt.compCount > 2:
    alignment = elem_size * 4

# 对齐逻辑更复杂，可能不准确
```

**影响**：对齐计算方式不一致可能导致偏移计算错误。

---

### 3. Position 属性处理方式不同 ⚠️

#### `mesh_to_fbx`：
```python
# 尝试将 Position 移到最前面
if position_attr and position_attr != all_attrs[0]:
    all_attrs.remove(position_attr)
    all_attrs.insert(0, position_attr)
```

**问题**：如果 Position 不在原始列表的第一位，移动它会导致偏移计算错误，因为 PostVS 数据的实际布局可能与 shader 输出签名顺序一致，而不是 Position 在前。

#### `mesh_attribute_printer`：
```python
# 不移动 Position，保持原始顺序
# 直接使用 shader 输出签名的顺序
```

---

### 4. 属性名称获取方式

两者都使用：
```python
attr.name = sig.semanticIdxName if sig.varName == '' else sig.varName
```

这个是正确的。

---

## 根本原因

**主要问题**：`mesh_to_fbx` 在构建属性列表时**没有过滤非光栅化流和输出索引**，导致：

1. 属性列表包含了不应该包含的属性
2. 偏移计算基于错误的属性列表
3. 当尝试读取 TEXCOORD0 时，使用的偏移量是错误的
4. 结果读取到了错误位置的数据（可能是 TEXCOORD9 或其他属性的数据）

---

## 修复方案

### 修复 1: 添加属性过滤

在 `_get_mixed_mesh` 和 `_get_vs_output_mesh` 中，构建属性列表时添加过滤：

```python
for sig in vs.outputSignature:
    # 过滤非光栅化流
    if pipe.GetRasterizedStream() >= 0:
        if sig.stream != pipe.GetRasterizedStream():
            continue
    else:
        if sig.stream != 0:
            continue
    
    # 跳过输出索引
    if sig.systemValue == rd.ShaderBuiltin.OutputIndices:
        continue
    
    # 创建属性...
    all_attrs.append(attr)
```

### 修复 2: 简化对齐计算

使用与 `mesh_attribute_printer` 相同的对齐方式：

```python
elem_size = (8 if fmt.compByteWidth > 4 else 4)
alignment = elem_size * 4  # 固定使用 4 倍对齐

if pipe.HasAlignedPostVSData(rd.MeshDataStage.VSOut) and (accum_offset % alignment) != 0:
    padding = alignment - (accum_offset % alignment)
    accum_offset += padding
```

### 修复 3: 移除 Position 重排序

不要移动 Position 到最前面，保持 shader 输出签名的原始顺序：

```python
# 移除这段代码：
# if position_attr and position_attr != all_attrs[0]:
#     all_attrs.remove(position_attr)
#     all_attrs.insert(0, position_attr)
```

---

## 验证方法

修复后，可以通过以下方式验证：

1. 使用 `mesh_attribute_printer` 打印 VS Output 数据，查看 TEXCOORD0 的实际值
2. 使用修复后的 `mesh_to_fbx` 导出，对比 UV 值是否一致
3. 检查导出的 FBX 文件中的 UV 是否在 0-1 范围内（如果应该在这个范围内）

---

## 修复状态

✅ **已修复**：已在 `mesh_to_fbx/mesh_export.py` 中应用以下修复：

1. ✅ 在 `_get_mixed_mesh` 中添加了属性过滤（非光栅化流、输出索引）
2. ✅ 在 `_get_mixed_mesh` 中简化了对齐计算（使用固定的 `elem_size * 4`）
3. ✅ 在 `_get_mixed_mesh` 中移除了 Position 重排序逻辑
4. ✅ 在 `_get_vs_output_mesh` 中添加了相同的属性过滤
5. ✅ 在 `_get_vs_output_mesh` 中简化了对齐计算
6. ✅ 在 `_get_vs_output_mesh` 中移除了 Position 重排序逻辑

## 总结

**核心问题**：属性列表构建时缺少过滤，导致偏移计算错误，从而读取到错误位置的数据。

**解决方案**：参考 `mesh_attribute_printer` 的正确实现，添加属性过滤、简化对齐计算、保持原始属性顺序。

**修复后的代码现在与 `mesh_attribute_printer` 的实现保持一致，应该能够正确读取 TEXCOORD0 的 UV 数据。**

