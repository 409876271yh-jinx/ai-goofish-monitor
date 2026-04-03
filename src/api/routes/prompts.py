"""
Prompt 管理路由
"""
import os
import re
import aiofiles
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


router = APIRouter(prefix="/api/prompts", tags=["prompts"])
PROMPTS_DIR = "prompts"
PROMPT_FILENAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\.txt$")


class PromptUpdate(BaseModel):
    """Prompt 更新模型"""
    content: str


class PromptCreate(BaseModel):
    """Prompt 创建模型"""
    filename: str
    content: str = ""


def _validate_prompt_filename(filename: str) -> str:
    normalized = str(filename or "").strip()
    if "/" in normalized or ".." in normalized:
        raise HTTPException(status_code=400, detail="无效的文件名")
    if not PROMPT_FILENAME_PATTERN.fullmatch(normalized):
        raise HTTPException(
            status_code=400,
            detail="文件名必须为 .txt 结尾，且只能包含字母、数字、点、下划线或短横线",
        )
    return normalized


@router.get("")
async def list_prompts():
    """列出所有 prompt 文件"""
    if not os.path.isdir(PROMPTS_DIR):
        return []
    return sorted(f for f in os.listdir(PROMPTS_DIR) if f.endswith(".txt"))


@router.post("")
async def create_prompt(prompt_create: PromptCreate):
    """创建新的 prompt 文件"""
    filename = _validate_prompt_filename(prompt_create.filename)
    os.makedirs(PROMPTS_DIR, exist_ok=True)
    filepath = os.path.join(PROMPTS_DIR, filename)

    if os.path.exists(filepath):
        raise HTTPException(status_code=409, detail="Prompt 文件已存在")

    try:
        async with aiofiles.open(filepath, "w", encoding="utf-8") as f:
            await f.write(prompt_create.content)
        return {"message": f"Prompt 文件 '{filename}' 创建成功", "filename": filename}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"创建文件时出错: {e}")


@router.get("/{filename}")
async def get_prompt(filename: str):
    """获取 prompt 文件内容"""
    filename = _validate_prompt_filename(filename)
    filepath = os.path.join(PROMPTS_DIR, filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Prompt 文件未找到")

    async with aiofiles.open(filepath, 'r', encoding='utf-8') as f:
        content = await f.read()
    return {"filename": filename, "content": content}


@router.put("/{filename}")
async def update_prompt(
    filename: str,
    prompt_update: PromptUpdate,
):
    """更新 prompt 文件内容"""
    filename = _validate_prompt_filename(filename)
    filepath = os.path.join(PROMPTS_DIR, filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Prompt 文件未找到")

    try:
        async with aiofiles.open(filepath, 'w', encoding='utf-8') as f:
            await f.write(prompt_update.content)
        return {"message": f"Prompt 文件 '{filename}' 更新成功"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"写入文件时出错: {e}")
