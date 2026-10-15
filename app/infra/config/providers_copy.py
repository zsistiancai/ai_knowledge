"""
配置聚合模块，负责将旧配置对象统一收口到新的基础设施出口。
"""


from app.shared.config.embedding_config import embedding_config
from app.shared.config.lm_config import lm_config
from app.shared.config.bailian_mcp_config import mcp_config
from app.shared.config.milvus_config import milvus_config
from app.shared.config.mineru_config import mineru_config
from app.shared.config.minio_config import minio_config
from app.shared.config.reranker_config import reranker_config
from app.shared.config.settings_config import settings


from dataclasses import dataclass

@dataclass
class InfrastructureConfig:
    app: object = settings
    llm: object = lm_config
    embedding: object = embedding_config
    reranker: object = reranker_config
    mcp: object = mcp_config
    milvus: object = milvus_config
    mineru: object = mineru_config
    minio: object = minio_config


infra_config = InfrastructureConfig()



