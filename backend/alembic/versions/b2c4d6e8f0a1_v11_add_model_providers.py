"""v1.1 add model providers, project/conversation/generation model fields, migrate api_key_configs

Revision ID: b2c4d6e8f0a1
Revises: 9c1d10bb3b8e
Create Date: 2026-08-15 00:00:00.000000

数据迁移设计（docs/TECHv1.1.md §4.2 / §9-5）：
- 旧 api_key_configs 表按 (provider, base_url) 分组，每组生成一条 model_providers 记录，
  组内每个旧 Key 成为该 Provider 的一条 api_keys_json 记录。
- 密文直接复用：api_key_configs.encrypted_key 与 api_keys_json[].api_key_encrypted 采用
  相同加密格式（Base64(nonce+ciphertext)）与相同主密钥（DATA_DIR/secret.key）。
- 旧 Key 的 project_id 为空 → 全局提供商（scope='global'）；非空 → 同样转为全局提供商，
  但将该项目的 projects.default_provider_id 指向该提供商（V1.1 中 Provider 全局、项目仅存默认）。
- 旧全局默认 Key（is_default=True 且 project_id 为空）→ provider.is_default=True，
  并写入 app_configs.global_default_provider_id。
- downgrade 尽力可逆：api_key_configs 由 model_providers 反转重建（project 关联折叠为全局）。
"""
from typing import Optional, Sequence, Union

import json
import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b2c4d6e8f0a1'
down_revision: Union[str, Sequence[str], None] = '9c1d10bb3b8e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 旧 provider 值 → 新 type 值（moonshot 与 kimi 同服务；其余保持一致）
_PROVIDER_TYPE_MAP = {"moonshot": "kimi"}
_GLOBAL_DEFAULT_KEY = "global_default_provider_id"


def _now() -> str:
    """迁移内的统一时间戳（ISO 字符串，SQLite 存储为 TEXT）。"""
    return datetime.now(timezone.utc).isoformat()


def _upsert_app_config(bind, key: str, value: object) -> None:
    """按 key 更新或插入 app_configs 记录（value 为 JSON 序列化文本）。"""
    exists = bind.execute(
        sa.text("SELECT id FROM app_configs WHERE key = :k"), {"k": key}
    ).scalar()
    now = _now()
    if exists:
        bind.execute(
            sa.text("UPDATE app_configs SET value = :v, updated_at = :u WHERE key = :k"),
            {"v": json.dumps(value, ensure_ascii=False), "u": now, "k": key},
        )
    else:
        bind.execute(
            sa.text(
                "INSERT INTO app_configs (id, key, value, created_at, updated_at) "
                "VALUES (:id, :k, :v, :c, :u)"
            ),
            {"id": str(uuid.uuid4()), "k": key, "v": json.dumps(value, ensure_ascii=False),
             "c": now, "u": now},
        )


def _convert_api_key_configs() -> None:
    """将 api_key_configs 数据转换为 model_providers（升级方向）。"""
    bind = op.get_bind()
    rows = bind.execute(sa.text(
        "SELECT id, project_id, provider, name, encrypted_key, base_url, model, is_default, "
        "created_at, updated_at FROM api_key_configs ORDER BY created_at ASC"
    )).mappings().all()

    # 按 (provider, base_url) 分组；组内按 (is_default 优先, created_at 升序) 排序
    groups: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        groups.setdefault((row["provider"], row["base_url"] or ""), []).append(dict(row))

    # project_id -> (rank, created_at, new_provider_id)：项目级 Key 的最高优先级提供商
    project_default: dict[str, tuple[int, str, str]] = {}
    # (rank, new_provider_id)：全局默认提供商（无 is_default 时取最早创建）
    global_default: Optional[tuple[tuple[int, str], str]] = None

    for (provider, base_url), items in groups.items():
        new_id = str(uuid.uuid4())
        ordered = sorted(items, key=lambda it: (not bool(it["is_default"]), it["created_at"]))

        api_keys = []
        models_seen: dict[str, None] = {}
        for idx, it in enumerate(ordered, start=1):
            api_keys.append({
                "key_id": it["id"],  # 沿用旧 Key id，保持可追溯
                "api_key_encrypted": it["encrypted_key"],  # 同格式同主密钥，直接复用
                "enabled": True,
                "priority": idx,
                "available_models": [it["model"]] if it["model"] else [],
            })
            if it["model"]:
                models_seen.setdefault(it["model"], None)
        models_json = [{"model_id": m, "enabled": True} for m in models_seen]

        global_items = [it for it in items if it["project_id"] is None]
        provider_is_default = any(bool(it["is_default"]) for it in global_items)

        created_at = min(it["created_at"] for it in items)
        updated_at = max(it["updated_at"] for it in items)
        bind.execute(
            sa.text(
                "INSERT INTO model_providers (id, name, type, base_url, scope, api_keys_json, "
                "models_json, is_default, created_at, updated_at) "
                "VALUES (:id, :name, :type, :base_url, :scope, :api_keys_json, :models_json, "
                ":is_default, :created_at, :updated_at)"
            ),
            {
                "id": new_id,
                "name": ordered[0]["name"],
                "type": _PROVIDER_TYPE_MAP.get(provider, provider),
                "base_url": base_url or None,
                "scope": "global",
                "api_keys_json": json.dumps(api_keys, ensure_ascii=False),
                "models_json": json.dumps(models_json, ensure_ascii=False),
                "is_default": 1 if provider_is_default else 0,
                "created_at": created_at,
                "updated_at": updated_at,
            },
        )

        # 项目级 Key → 项目默认提供商（rank 低者优先：is_default 为 0，同类取 created_at 早）
        for it in items:
            if it["project_id"] is not None:
                rank = (0 if bool(it["is_default"]) else 1, it["created_at"])
                cur = project_default.get(it["project_id"])
                if cur is None or rank < (cur[0], cur[1]):
                    project_default[it["project_id"]] = (rank[0], rank[1], new_id)
        # 全局默认提供商
        for it in global_items:
            rank = (0 if bool(it["is_default"]) else 1, it["created_at"])
            if global_default is None or rank < global_default[0]:
                global_default = (rank, new_id)

    # 项目默认提供商回填（default_provider_id 为新增列，此时恒为 NULL）
    for project_id, (_, _, new_provider_id) in project_default.items():
        bind.execute(
            sa.text("UPDATE projects SET default_provider_id = :pid WHERE id = :id"),
            {"pid": new_provider_id, "id": project_id},
        )
    # 全局默认提供商（app_configs.global_default_provider_id）
    if global_default is not None:
        _upsert_app_config(bind, _GLOBAL_DEFAULT_KEY, global_default[1])


def _recreate_api_key_configs() -> None:
    """从 model_providers 反转重建 api_key_configs（尽力可逆，项目关联折叠为全局）。"""
    bind = op.get_bind()
    providers = bind.execute(sa.text(
        "SELECT id, name, type, base_url, api_keys_json, is_default, created_at, updated_at "
        "FROM model_providers"
    )).mappings().all()

    now = _now()
    for p in providers:
        try:
            api_keys = json.loads(p["api_keys_json"] or "[]")
        except (TypeError, json.JSONDecodeError):
            api_keys = []
        # 旧 provider 枚举不含 type 中的新值，未知类型回退 custom
        provider = "custom" if p["type"] not in (
            "openai", "deepseek", "kimi", "moonshot", "custom"
        ) else p["type"]
        for idx, k in enumerate(api_keys, start=1):
            models = k.get("available_models") or []
            bind.execute(
                sa.text(
                    "INSERT INTO api_key_configs (id, project_id, provider, name, encrypted_key, "
                    "base_url, model, is_default, created_at, updated_at) "
                    "VALUES (:id, NULL, :provider, :name, :encrypted_key, :base_url, :model, "
                    ":is_default, :created_at, :updated_at)"
                ),
                {
                    "id": k.get("key_id") or str(uuid.uuid4()),
                    "provider": provider,
                    "name": p["name"],
                    "encrypted_key": k.get("api_key_encrypted", ""),
                    "base_url": p["base_url"] or "",
                    "model": models[0] if models else None,
                    # 仅第一把 Key 继承 Provider 的全局默认标记
                    "is_default": 1 if (bool(p["is_default"]) and idx == 1) else 0,
                    "created_at": p["created_at"] or now,
                    "updated_at": p["updated_at"] or now,
                },
            )


def upgrade() -> None:
    """Upgrade schema."""
    # 1) 创建 model_providers 表
    op.create_table('model_providers',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('type', sa.String(length=50), nullable=False),
    sa.Column('base_url', sa.String(length=500), nullable=True),
    sa.Column('scope', sa.String(length=20), nullable=False, server_default='global'),
    sa.Column('api_keys_json', sa.JSON(), nullable=False),
    sa.Column('models_json', sa.JSON(), nullable=False),
    sa.Column('is_default', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )

    # 2) 修改 projects / conversations / generation_records 表
    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.add_column(sa.Column('default_provider_id', sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column('default_model_id', sa.String(length=200), nullable=True))
        batch_op.create_foreign_key('fk_projects_default_provider_id', 'model_providers', ['default_provider_id'], ['id'], ondelete='SET NULL')

    with op.batch_alter_table('conversations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('current_provider_id', sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column('current_model_id', sa.String(length=200), nullable=True))
        batch_op.create_foreign_key('fk_conversations_current_provider_id', 'model_providers', ['current_provider_id'], ['id'], ondelete='SET NULL')

    with op.batch_alter_table('generation_records', schema=None) as batch_op:
        batch_op.add_column(sa.Column('provider_id', sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column('model_id', sa.String(length=200), nullable=True))

    # 3) 数据转换：api_key_configs → model_providers（必须先于 drop）
    _convert_api_key_configs()

    # 4) 删除旧表
    op.drop_table('api_key_configs')


def downgrade() -> None:
    """Downgrade schema."""
    # 1) 反转数据：model_providers → api_key_configs（项目关联折叠为全局）
    op.create_table('api_key_configs',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('project_id', sa.String(length=36), nullable=True),
    sa.Column('provider', sa.String(length=50), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('encrypted_key', sa.Text(), nullable=False),
    sa.Column('base_url', sa.String(length=500), nullable=False),
    sa.Column('model', sa.String(length=100), nullable=True),
    sa.Column('is_default', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    _recreate_api_key_configs()
    # 移除升级时写入的全局默认提供商
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM app_configs WHERE key = :k"), {"k": _GLOBAL_DEFAULT_KEY})

    # 2) 回滚表结构
    with op.batch_alter_table('generation_records', schema=None) as batch_op:
        batch_op.drop_column('provider_id')
        batch_op.drop_column('model_id')

    with op.batch_alter_table('conversations', schema=None) as batch_op:
        batch_op.drop_constraint('fk_conversations_current_provider_id', type_='foreignkey')
        batch_op.drop_column('current_provider_id')
        batch_op.drop_column('current_model_id')

    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.drop_constraint('fk_projects_default_provider_id', type_='foreignkey')
        batch_op.drop_column('default_provider_id')
        batch_op.drop_column('default_model_id')

    op.drop_table('model_providers')
