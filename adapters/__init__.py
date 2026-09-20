"""GEO 自己的 adapters 包。

这个 __init__.py 不是装饰：同机上 eios-integrations（以及 foundation）也有一个带
__init__.py 的 adapters 包，而两者都会出现在 PYTHONPATH 上。没有这个文件时 GEO 的
adapters/ 只是「命名空间包」，Python 在找到后面那个常规包时会直接选中它 ——
于是 from adapters.llm import ... 会报 ModuleNotFoundError: No module named
'adapters.llm'，即使文件就在眼前。有它才按 PYTHONPATH 顺序（GEO 仓最前）解析到本仓。
"""
