from typing import Any
from pydantic import BaseModel,Field

class QueryRequest(BaseModel):
    """
    查询请求参数
    """
    session_id: str = Field(None, description="会话ID")
    query: str | None = Field(..., description="原始查询")
    is_stream: bool = Field(False, description="是否流式返回")


# 错误示范
# class A:
#     lst = []
#
# a1 = A()
# a2 = A()
# a1.lst.append(1)
#
# print(a2.lst)  # 输出 [1] ！！！ 被污染了

class AsyncQueryResponse(BaseModel):
    """
    查询响应参数
    """
    session_id: str = Field(..., description="会话ID")
    message: str = Field(..., description="响应信息")



class QueryResponse(BaseModel):
    """
    查询响应参数
    """
    session_id: str = Field(..., description="会话ID")
    message: str = Field(..., description="响应信息")
    answer: str = Field("", description="答案")
    image_urls: list[str] = Field(description="图片URL列表" ,default_factory=list)
    done_list: list[str]  = Field(description="已完成任务列表", default_factory=list)


class ClearHistoryResponse(BaseModel):
    """
    清空聊天记录接口响应体
    """
    message: str = Field(..., description="操作提示信息")
    deleted_count: int = Field(..., description="成功删除的消息条数")


class HistoryItem(BaseModel):
    id: str = Field(default="", description="消息ID")
    session_id: str = ""
    role: str = ""
    text: str = ""
    rewritten_query: str = ""
    item_names: list[str] = Field(default_factory=list)
    image_urls: list[str] = Field(default_factory=list)
    ts: Any = None


class HistoryResponse(BaseModel):
    session_id: str
    items: list[HistoryItem] = Field(default_factory=list)