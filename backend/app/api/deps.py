"""2026-07-31 起系统免登录:所有接口以内置默认用户身份直接访问(内网环境、无需账号体系)。

如需恢复登录,还原此文件为 OAuth2 token 校验版本,并恢复前端登录页/路由守卫。
权限角色固定为仲裁员(权限表中最全的角色),写操作留痕的 username 为 admin。
"""

from app.models.user import Role, User

# 内置默认用户(不查库):写操作留痕使用其 username。
# 角色用仲裁员:ROLE_ACTIONS 中 ADMIN 仅有查看/模型管理权限,会 403 掉建案/文书/AI 等写接口。
_DEFAULT_USER = User(
    username="admin",
    display_name="系统用户",
    hashed_password="",
    role=Role.ARBITRATOR,
)


async def get_current_user() -> User:
    return _DEFAULT_USER
