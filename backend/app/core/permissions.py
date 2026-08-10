import enum

from fastapi import Depends, HTTPException, status

from app.models.user import Role


class Action(str, enum.Enum):
    VIEW = "view"  # 查看
    EDIT = "edit"  # 编辑
    DELETE = "delete"  # 删除
    AI_INVOKE = "ai_invoke"  # AI 调用
    DOCUMENT_GENERATE = "document_generate"  # 文书生成
    CONFIRM = "confirm"  # 审核确认
    MODEL_MANAGE = "model_manage"  # AI 模型配置管理


# 对应 04 PRD 第十一章"权限需求"表格。
ROLE_ACTIONS: dict[Role, set[Action]] = {
    Role.ARBITRATOR: {
        Action.VIEW,
        Action.EDIT,
        Action.AI_INVOKE,
        Action.DOCUMENT_GENERATE,
        Action.CONFIRM,
        Action.MODEL_MANAGE,
    },
    Role.CLERK: {Action.VIEW, Action.EDIT},
    Role.MEDIATOR: {Action.VIEW, Action.EDIT},
    Role.ADMIN: {Action.VIEW, Action.MODEL_MANAGE},
}


def require_permission(action: Action):
    """FastAPI 依赖工厂：声明式校验当前用户角色是否具备某项操作权限。"""

    from app.api.deps import get_current_user  # 延迟导入，避免循环依赖

    def _checker(current_user=Depends(get_current_user)):
        allowed = ROLE_ACTIONS.get(Role(current_user.role), set())
        if action not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"角色 {current_user.role} 无权执行 {action.value}",
            )
        return current_user

    return _checker
