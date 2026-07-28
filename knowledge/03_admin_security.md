---
source_id: admin-security-v1
title: 管理员安全边界（教学样例）
access_roles: admin
version: 1.0
---

# 管理员专属规则

- 生产环境写工具的审批人必须属于 admin 角色。
- 审计日志保留周期为 180 天，普通 employee 角色不可查看完整操作参数。
- 出现连续三次工具执行失败时，生产工作流应停止自动重试并通知值班人员。
