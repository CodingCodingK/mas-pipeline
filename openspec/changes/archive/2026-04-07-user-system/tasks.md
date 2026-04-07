## 1. User 模型与获取函数

- [x] 1.1 实现 `src/auth/user.py` — User dataclass（id, name, email, config, created_at）+ `get_current_user()` 函数（读配置 → 查 DB → 缓存）
- [x] 1.2 确认 `config/settings.yaml` 的 `default_user` 配置和 `scripts/init_db.sql` 的 seed 数据一致

## 2. 验证

- [x] 2.1 创建 `scripts/test_user_system.py` — 验证 get_current_user 返回正确 User、缓存生效、用户不存在时报错
