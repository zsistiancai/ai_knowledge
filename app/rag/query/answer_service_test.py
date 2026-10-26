from app.infra.persistence.history_repository import history_repository
from app.process.query.agent.state import QueryGraphState
from app.shared.utils.task_utils import add_done_task,add_running_task,push_to_session
from app.shared.utils.sse_utils import SSEEvent
from app.shared.runtime.logger import logger
import time
import sys

def generate_answer(state: QueryGraphState) -> QueryGraphState:
    """
    答案生成服务：
    1. 检查前置答案（如有追问或拒绝回答，直接输出）
    2. 构建 Prompt（用户问题 + 历史对话 + TopK 文档）
    3. 调用 LLM 生成最终答案（支持流式推送）
    4. 从引用文档中提取图片 URL
    5. 写入 MongoDB 历史记录
    6. 回写 answer 和 image_urls
    """
    ""
    print("---node_answer_output 节点处理开始---")
    add_running_task(state["session_id"], sys._getframe().f_code.co_name, state.get("is_stream"))

    session_id = state["session_id"]
    is_stream = state.get("is_stream", True)
    base_answer = state.get("answer") or f"这是关于「{state.get('original_query', '当前问题')}」的测试回答，正在演示打字机流式输出效果。"
    final_text = ""

    if is_stream:
        for ch in base_answer:
            final_text += ch
            push_to_session(session_id, SSEEvent.DELTA, {"delta": ch})
            time.sleep(0.03)

        image_urls = ["http://www.baidu.com/img/bd_logo.png", "https://gips3.baidu.com/it/u=3886271102,3123389489&fm=3028&app=3028&f=JPEG&fmt=auto?w=1280&h=960"]
        # push_to_session(
        #     session_id,
        #     SSEEvent.FINAL,
        #     {
        #         "answer": final_text,
        #         "status": "completed",
        #         "image_urls": image_urls
        #     }
        # )
        logger.info(f"流式输出完成，总长度: {len(final_text)}")
    else:
        final_text = base_answer

    history_repository.save_message(
        session_id=state['session_id'],
        role="assistant",
        text=final_text,
        rewritten_query="我喜欢黑丝高跟",
        item_names=["黑丝高跟"],
        image_urls=["https://picx.zhimg.com/v2-4693e9123eb9b261a2fa6aa81a15367b_1440w.jpg"]
    )
    add_done_task(state["session_id"], sys._getframe().f_code.co_name, state["is_stream"])
    return state

    add_done_task(state['session_id'], sys._getframe().f_code.co_name, state.get("is_stream"))
    print("---node_answer_output 节点处理结束---")
    # 关键点：return 必须保留 session_id！
    return {
        "session_id": session_id,  # 必须带回去
        "answer": final_text,
        "image_urls": image_urls,
        "is_stream": state.get("is_stream")
    }