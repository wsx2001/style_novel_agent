# backend/tests/test_project_defaults.py
"""全局默认提供商/模型与项目默认联动测试（docs/TECHv1.1.md §4.6 / §5.2 / §5.5）。

覆盖：
- GET/PATCH /settings/app：读写全局默认提供商/模型，设置时同步 ModelProvider.is_default，
  清空时反向清除；
- POST /projects：未传 default_provider_id/model_id 时从全局默认复制，全局未配置时为 None，
  显式传入时覆盖继承，提供商不存在时 400；
- PATCH /projects/{id}：可设置 / 清空项目默认提供商与模型；
- services/llm/resolve：全局默认更新后，无项目覆盖的项目在生成/对话时走全局默认。
"""
from __future__ import annotations

import pytest

from fastapi import HTTPException

from app.api.v1.projects import create_project, update_project
from app.api.v1.settings import get_global_settings, update_global_settings
from app.models import ModelProvider
from app.schemas.project import ProjectCreate, ProjectUpdate
from app.schemas.settings import GlobalAppConfigUpdate
from app.services.llm.resolve import NoLLMConfigError, resolve_llm
from app.services.model_provider import create_provider

pytestmark = pytest.mark.anyio


# ---------------------------------------------------------------------------
# 构造辅助
# ---------------------------------------------------------------------------


async def _create_provider(
    session_factory,
    *,
    name: str = "测试提供商",
    model_id: str = "gpt-4o",
):
    async with session_factory() as session:
        provider = await create_provider(
            session,
            name=name,
            type="openai",
            base_url="https://api.openai.com/v1",
            api_keys=[{"key": "sk-default-1111", "enabled": True, "priority": 1}],
        )
        provider.models_json = [{"model_id": model_id, "enabled": True}]
        await session.commit()
        return provider


async def _set_global_defaults(
    session_factory, provider_id: str, model_id: str
) -> None:
    async with session_factory() as session:
        await update_global_settings(
            GlobalAppConfigUpdate(
                global_default_provider_id=provider_id,
                global_default_model_id=model_id,
            ),
            session,
        )


# ---------------------------------------------------------------------------
# GET /settings/app：未配置时返回空串
# ---------------------------------------------------------------------------


async def test_get_global_settings_empty_when_unset(session_factory):
    async with session_factory() as session:
        result = await get_global_settings(session)
    assert result.global_default_provider_id == ""
    assert result.global_default_model_id == ""
    assert result.global_default_prompt_template_id == ""
    assert result.global_default_model_config == {}


# ---------------------------------------------------------------------------
# PATCH /settings/app：写入 / 清空全局默认，同步 is_default
# ---------------------------------------------------------------------------


async def test_patch_global_settings_persists_and_syncs_is_default(session_factory):
    provider = await _create_provider(session_factory)
    async with session_factory() as session:
        result = await update_global_settings(
            GlobalAppConfigUpdate(
                global_default_provider_id=provider.id,
                global_default_model_id="gpt-4o",
            ),
            session,
        )
    assert result.global_default_provider_id == provider.id
    assert result.global_default_model_id == "gpt-4o"

    async with session_factory() as session:
        row = await session.get(ModelProvider, provider.id)
        assert row.is_default is True


async def test_patch_global_settings_clears_and_unsets_is_default(session_factory):
    provider = await _create_provider(session_factory)
    await _set_global_defaults(session_factory, provider.id, "gpt-4o")

    async with session_factory() as session:
        result = await update_global_settings(
            GlobalAppConfigUpdate(
                global_default_provider_id="",
                global_default_model_id="",
            ),
            session,
        )
    assert result.global_default_provider_id == ""
    assert result.global_default_model_id == ""

    async with session_factory() as session:
        row = await session.get(ModelProvider, provider.id)
        assert row.is_default is False


async def test_patch_global_settings_rejects_missing_provider(session_factory):
    async with session_factory() as session:
        with pytest.raises(HTTPException) as excinfo:
            await update_global_settings(
                GlobalAppConfigUpdate(global_default_provider_id="no-such"),
                session,
            )
    assert excinfo.value.status_code == 400


# ---------------------------------------------------------------------------
# POST /projects：默认提供商/模型继承逻辑
# ---------------------------------------------------------------------------


async def test_create_project_inherits_global_defaults(session_factory):
    provider = await _create_provider(session_factory)
    await _set_global_defaults(session_factory, provider.id, "gpt-4o")

    async with session_factory() as session:
        project = await create_project(ProjectCreate(title="继承全局"), session)
    assert project.default_provider_id == provider.id
    assert project.default_model_id == "gpt-4o"


async def test_create_project_null_defaults_when_no_global(session_factory):
    async with session_factory() as session:
        project = await create_project(ProjectCreate(title="无全局"), session)
    assert project.default_provider_id is None
    assert project.default_model_id is None


async def test_create_project_request_defaults_override_global(session_factory):
    global_provider = await _create_provider(session_factory, name="全局提供商")
    local_provider = await _create_provider(session_factory, name="项目提供商")
    await _set_global_defaults(session_factory, global_provider.id, "gpt-4o")

    async with session_factory() as session:
        project = await create_project(
            ProjectCreate(
                title="覆盖继承",
                default_provider_id=local_provider.id,
                default_model_id="claude-3-5-sonnet",
            ),
            session,
        )
    assert project.default_provider_id == local_provider.id
    assert project.default_model_id == "claude-3-5-sonnet"


async def test_create_project_rejects_missing_provider(session_factory):
    async with session_factory() as session:
        with pytest.raises(HTTPException) as excinfo:
            await create_project(
                ProjectCreate(title="坏提供商", default_provider_id="no-such"),
                session,
            )
    assert excinfo.value.status_code == 400


# ---------------------------------------------------------------------------
# PATCH /projects/{id}：设置 / 清空项目默认提供商与模型
# ---------------------------------------------------------------------------


async def test_update_project_sets_and_clears_defaults(session_factory):
    provider = await _create_provider(session_factory)
    async with session_factory() as session:
        project = await create_project(ProjectCreate(title="原项目"), session)
        project_id = project.id
        updated = await update_project(
            project_id,
            ProjectUpdate(
                default_provider_id=provider.id,
                default_model_id="gpt-4o",
            ),
            session,
        )
    assert updated.default_provider_id == provider.id
    assert updated.default_model_id == "gpt-4o"

    async with session_factory() as session:
        cleared = await update_project(
            project_id,
            ProjectUpdate(default_provider_id=None, default_model_id=None),
            session,
        )
    assert cleared.default_provider_id is None
    assert cleared.default_model_id is None


# ---------------------------------------------------------------------------
# 生成/对话解析：全局默认对无项目覆盖的项目生效（docs/TECHv1.1.md §7.2）
# ---------------------------------------------------------------------------


async def test_resolve_llm_uses_global_default(session_factory):
    provider = await _create_provider(session_factory)
    await _set_global_defaults(session_factory, provider.id, "gpt-4o")
    async with session_factory() as session:
        project = await create_project(ProjectCreate(title="继承全局"), session)

    async with session_factory() as session:
        resolved = await resolve_llm(session, project_id=project.id)
    assert resolved.provider_id == provider.id
    assert resolved.model_id == "gpt-4o"


async def test_resolve_llm_uses_project_default_over_global(session_factory):
    """项目设置了默认提供商/模型时优先于全局默认生效（docs/TECHv1.1.md §7.2）。

    对应项目设置页「模型设置」保存 default_provider_id / default_model_id 后，
    该项目后续生成 / 对话应使用项目默认而非全局默认。
    """
    global_provider = await _create_provider(session_factory, name="全局提供商")
    project_provider = await _create_provider(
        session_factory, name="项目提供商", model_id="claude-3-5-sonnet"
    )
    await _set_global_defaults(session_factory, global_provider.id, "gpt-4o")

    async with session_factory() as session:
        project = await create_project(
            ProjectCreate(
                title="项目覆盖全局",
                default_provider_id=project_provider.id,
                default_model_id="claude-3-5-sonnet",
            ),
            session,
        )

    async with session_factory() as session:
        resolved = await resolve_llm(session, project_id=project.id)
    assert resolved.provider_id == project_provider.id
    assert resolved.model_id == "claude-3-5-sonnet"


async def test_resolve_llm_raises_without_config(session_factory):
    async with session_factory() as session:
        project = await create_project(ProjectCreate(title="无提供商"), session)

    async with session_factory() as session:
        with pytest.raises(NoLLMConfigError):
            await resolve_llm(session, project_id=project.id)
