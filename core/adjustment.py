"""Adjustment names only. Never transform prices or infer missing metadata."""
from typing import Literal

AdjustmentInput = Literal["none", "forward", "backward", "qfq", "hfq"]
ADJUSTMENT_DESCRIPTION = "复权：none不复权 / forward前复权 / backward后复权；兼容qfq=forward、hfq=backward"
_ALIASES = {"none": "none", "forward": "forward", "backward": "backward", "qfq": "forward", "hfq": "backward"}


def normalize_adjustment(value: object) -> str | None:
    return _ALIASES.get(value.strip().lower()) if isinstance(value, str) else None


def adjustment_error(*, metadata: bool = False) -> dict:
    return {"ok": False, "error": "invalid_adjustment_metadata" if metadata else "unsupported_adjustment",
            "message": "数据复权标记缺失或无效，未猜测复权方式或发布图表。" if metadata else
                       "复权方式请选择none（不复权）、forward/qfq（前复权）、backward/hfq（后复权）；未知值不会改为不复权。"}
