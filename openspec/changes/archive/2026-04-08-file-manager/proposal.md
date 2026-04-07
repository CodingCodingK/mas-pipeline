## Why

管线中的 Agent 需要读取用户上传的文件（课件 PDF/PPT、参考资料等）。File Manager 负责文件的上传登记、路径管理和删除清理。Phase 4 RAG 模块会在 upload 后触发解析和 embedding，当前 Phase 2 先建好文件注册层。

## What Changes

- 新增 `src/files/manager.py` — Document ORM model + upload/list/delete/get_file_path 函数
- 在 `src/models.py` 中增加 Document model
- 文件存储在 `uploads/{project_id}/` 目录（project-manager 已建好目录）
- 删除文件时同时清理 documents 表记录和 document_chunks 关联数据
- 格式校验：只接受指定的文件类型（pdf/pptx/md/docx/png/jpg）

## Capabilities

### New Capabilities
- `file-management`: 项目文件的上传登记、列表查询、路径获取和删除清理

### Modified Capabilities
（无）

## Impact

- 新增文件：`src/files/manager.py`
- 修改文件：`src/models.py`（增加 Document model）
- 数据库：`documents` 表和 `document_chunks` 表已在 Phase 0 建好
- 文件系统：文件保存到 `uploads/{project_id}/`
- 下游：Phase 4 RAG parser 消费 Document 记录触发解析
