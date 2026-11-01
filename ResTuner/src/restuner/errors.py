"""ResTuner 异常类型。

所有对外抛出的异常都继承 :class:`ResTunerError`，GUI 只需捕获这一层。
"""
from __future__ import annotations


class ResTunerError(Exception):
    """所有 ResTuner 错误的基类。"""


class PEError(ResTunerError):
    """PE 结构不合法 / 不支持的输入。"""


class ResourceError(ResTunerError):
    """资源目录解析或重建失败。"""


class ThemeError(ResTunerError):
    """主题素材缺失或与目标不兼容。"""


class TargetError(ResTunerError):
    """目标目录 / 目标文件不满足打补丁的前提。"""


class VerifyError(ResTunerError):
    """写回前的自检未通过。"""


class BackupError(ResTunerError):
    """备份或还原失败。"""
