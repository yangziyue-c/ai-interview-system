"""用户设置接口：设置页面的 6 项通用偏好

读写口径：
- 第一次读取（没有记录）返回默认值，**不建行**——打开设置页不该产生写操作；
- PUT 是部分更新，首次提交时建行（upsert）。
"""
from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession, validate_position
from app.core.exceptions import BadRequestError
from app.models.user_setting import REPORT_PREFERENCES, THEMES, UserSetting
from app.schemas.settings import SettingsOut, SettingsUpdate
from app.utils.response import ok

router = APIRouter()

_DEFAULTS = {
    "default_position": "",
    "voice_answer": True,
    "auto_tts": True,
    "body_language": True,
    "report_preference": "detailed",
    "theme": "system",
}


def _serialize(row: UserSetting | None) -> dict:
    """没有记录时返回默认值；有记录时逐字段回读（老行缺列值用默认兜底）"""
    return {
        key: (getattr(row, key) if row is not None else default)
        for key, default in _DEFAULTS.items()
    }


@router.get("", response_model=dict, summary="获取当前用户设置")
async def get_settings(user: CurrentUser, db: DbSession) -> dict:
    row = await db.get(UserSetting, user.id)
    return ok(SettingsOut(**_serialize(row)).model_dump())


@router.put("", response_model=dict, summary="更新当前用户设置（部分字段）")
async def update_settings(req: SettingsUpdate, user: CurrentUser, db: DbSession) -> dict:
    changes = {key: value for key, value in req.model_dump(exclude_unset=True).items() if value is not None}

    if "default_position" in changes and changes["default_position"]:
        # 岗位是数据库动态维护的集合：写一个不存在的 code，前端下次用它开场
        # 会直接 400，不如在这里拒绝
        await validate_position(db, changes["default_position"])
    if "report_preference" in changes and changes["report_preference"] not in REPORT_PREFERENCES:
        raise BadRequestError(
            f"report_preference 取值非法：{changes['report_preference']}，"
            f"可选：{'/'.join(REPORT_PREFERENCES)}"
        )
    if "theme" in changes and changes["theme"] not in THEMES:
        raise BadRequestError(
            f"theme 取值非法：{changes['theme']}，可选：{'/'.join(THEMES)}"
        )

    row = await db.get(UserSetting, user.id)
    if row is None:
        # 建行时把本次改动与默认值一起写入，避免刷新时用到 flush 前的 None
        row = UserSetting(user_id=user.id, **(_DEFAULTS | changes))
        db.add(row)
    else:
        for key, value in changes.items():
            setattr(row, key, value)
    await db.commit()
    await db.refresh(row)
    return ok(SettingsOut(**_serialize(row)).model_dump(), "设置已保存")
