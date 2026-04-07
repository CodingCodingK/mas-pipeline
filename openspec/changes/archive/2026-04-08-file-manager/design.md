## Context

Phase 4 课件管线需要用户上传 PDF/PPT 等文件，经 RAG parser 解析为 chunks + embedding。File Manager 是文件注册层：管理文件的存储、元数据记录和删除清理。Phase 6 API 层通过 multipart upload 调用。

`documents` 表和 `document_chunks` 表已在 Phase 0 建好，chunks 有 `ON DELETE CASCADE`。`uploads/{project_id}/` 目录由 project-manager 创建。

## Goals / Non-Goals

**Goals:**
- 提供 Document ORM model 和 upload/list/delete/get_file_path 函数
- upload 接收文件路径，复制到 uploads 目录，登记到 DB
- 格式白名单校验（pdf/pptx/md/docx/png/jpg/jpeg）
- 删除时清理物理文件，DB 级联删 chunks

**Non-Goals:**
- 不做 RAG 解析（Phase 4）
- 不更新 parsed/chunk_count（Phase 4 parser 更新）
- 不做 multipart upload 处理（Phase 6 API 层）
- 不做文件大小限制（Phase 6 API 层）

## Decisions

### D1. upload 接收文件路径，复制到 uploads 目录

Phase 2 验证脚本通过路径调用。Phase 6 API 层先将 multipart 写到临时文件再调 upload。函数签名：`upload(project_id, file_path) -> Document`。内部用 `shutil.copy2` 复制到 `uploads/{project_id}/{filename}`。

### D2. 格式校验用后缀白名单

`ALLOWED_EXTENSIONS = {"pdf", "pptx", "md", "docx", "png", "jpg", "jpeg"}`。不在白名单内的拒绝，抛 ValueError。不做 MIME 检测（复杂度高，收益低）。

### D3. 删除靠 DB CASCADE + 代码删物理文件

`document_chunks` 有 `ON DELETE CASCADE`，删 document 记录自动删 chunks。代码只需删物理文件 + 删 documents 行。

### D4. Document model 放 src/models.py

和 User / Project 一致，统一 ORM model 层。

## Risks / Trade-offs

- **[文件名冲突]** → 同 project 上传同名文件会覆盖。Phase 2 可接受，Phase 6 可加 UUID 前缀
- **[物理文件删除失败]** → 记录日志但不阻塞 DB 删除，避免不一致
