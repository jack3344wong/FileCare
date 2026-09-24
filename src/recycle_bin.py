# -*- coding: utf-8 -*-
"""Windows 系统回收站操作模块 (Windows System Recycle Bin Operations)

通过 PowerShell 调用 Shell.Application COM 对象直接操作 Windows 系统回收站，
支持：列表查看、还原文件、永久删除、清空回收站。
无需额外 Python 依赖 (pywin32/winshell)。
"""
import subprocess
import json
import os
import re
import tempfile

# PowerShell 脚本：列出回收站所有项目
_LIST_SCRIPT = r"""
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$shell = New-Object -ComObject Shell.Application
$rb = $shell.NameSpace(0xa)
$items = $rb.Items()
Write-Host "TOTAL=$($items.Count)"
for ($i = 0; $i -lt $items.Count; $i++) {
    $item = $items.Item($i)
    $name = $rb.GetDetailsOf($item, 0)
    $orig = $rb.GetDetailsOf($item, 1)
    $date = $rb.GetDetailsOf($item, 2)
    $size = $rb.GetDetailsOf($item, 3)
    $type = $rb.GetDetailsOf($item, 4)
    # 判断是文件夹还是文件
    $isFolder = ($item.IsFolder -eq $true)
    Write-Host "ITEM|$i|$name|$orig|$date|$size|$type|$isFolder"
}
"""

# PowerShell 脚本：还原指定索引的项目
_RESTORE_SCRIPT = r"""
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$idx = {index}
$shell = New-Object -ComObject Shell.Application
$rb = $shell.NameSpace(0xa)
$items = $rb.Items()
if ($idx -lt 0 -or $idx -ge $items.Count) {
    Write-Host "ERROR:索引超出范围"
    exit 1
}
$item = $items.Item($idx)
$verbFound = $false
foreach ($verb in $item.Verbs()) {
    if ($verb.Name -like '*还原*' -or $verb.Name -like '*undelete*' -or $verb.Name -like '*恢复*') {
        $verb.DoIt()
        $verbFound = $true
        break
    }
}
if (-not $verbFound) {
    Write-Host "ERROR:未找到还原操作"
    exit 1
}
Write-Host "OK"
"""

# PowerShell 脚本：永久删除指定索引的项目
#
# 这里刻意不使用 $item.Verbs() 里的「删除」动词（DoIt）：
# 在回收站命名空间下它会弹出标题为“删除文件”的确认对话框，
# 没有人点击时 PowerShell 会一直阻塞（实测 30 秒超时都结束不了），
# 表现为界面上点「永久删除」卡住然后报错。
# 改为直接删除回收站存储里的两个文件：
#   $R……  项目数据本体
#   $I……  对应的元数据（名称 / 原路径 / 删除时间）
# 删完重新枚举回收站确认真的消失，避免“命令执行过”被当成“已删掉”。
_DELETE_SCRIPT = r"""
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$idx = {index}
$shell = New-Object -ComObject Shell.Application
$rb = $shell.NameSpace(0xa)
$items = $rb.Items()
if ($idx -lt 0 -or $idx -ge $items.Count) {
    Write-Host "ERROR:索引超出范围"
    exit 1
}
$item = $items.Item($idx)
$storage = $item.Path
if ([string]::IsNullOrEmpty($storage)) {
    Write-Host "ERROR:无法取得该项目的回收站存储路径"
    exit 1
}
if ($storage -notlike '*$Recycle.Bin*') {
    Write-Host "ERROR:该项目不在回收站存储目录中，已中止"
    exit 1
}
$dir = Split-Path -Parent $storage
$leaf = Split-Path -Leaf $storage
$targets = @($storage)
if ($leaf.Length -gt 2) {
    $targets += (Join-Path $dir ('$I' + $leaf.Substring(2)))
}
foreach ($p in $targets) {
    if (Test-Path -LiteralPath $p) {
        Remove-Item -LiteralPath $p -Recurse -Force -ErrorAction SilentlyContinue
    }
}
Start-Sleep -Milliseconds 400
$left = 0
foreach ($it in (New-Object -ComObject Shell.Application).NameSpace(0xa).Items()) {
    if ($it.Path -eq $storage) { $left++ }
}
if ($left -gt 0) {
    Write-Host "ERROR:删除未生效，该项目仍在回收站中"
    exit 1
}
Write-Host "OK"
"""

# PowerShell 脚本：逐项清空回收站（SHEmptyRecycleBin 不可用时的回退）
# 同样避开会弹确认框的动词调用，改为直接删除回收站存储文件。
_EMPTY_SCRIPT = r"""
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$shell = New-Object -ComObject Shell.Application
$items = $shell.NameSpace(0xa).Items()
if ($items.Count -eq 0) {
    Write-Host "OK:0"
    exit 0
}
$storages = @()
$targets = @()
foreach ($it in $items) {
    $storage = $it.Path
    if ([string]::IsNullOrEmpty($storage)) { continue }
    if ($storage -notlike '*$Recycle.Bin*') { continue }
    $storages += $storage
    $targets += $storage
    $leaf = Split-Path -Leaf $storage
    if ($leaf.Length -gt 2) {
        $targets += (Join-Path (Split-Path -Parent $storage) ('$I' + $leaf.Substring(2)))
    }
}
foreach ($p in $targets) {
    if (Test-Path -LiteralPath $p) {
        Remove-Item -LiteralPath $p -Recurse -Force -ErrorAction SilentlyContinue
    }
}
Start-Sleep -Milliseconds 400
$left = (New-Object -ComObject Shell.Application).NameSpace(0xa).Items().Count
if ($left -gt 0) {
    Write-Host "ERROR:仍有 $left 个项目未能删除"
    exit 1
}
Write-Host ("OK:" + $storages.Count)
"""

# 备选：使用 Shell32 SHEmptyRecycleBin API 清空
_EMPTY_VIA_SHELL32 = r"""
[Console]::OutputEncoding = [Text.Encoding]::UTF8
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public class RecycleBin {
    [DllImport("shell32.dll", CharSet = CharSet.Unicode)]
    public static extern int SHEmptyRecycleBin(IntPtr hwnd, string rootPath, uint flags);
}
"@
# flags: 1=无确认 3=无确认+无声效+无进度
$result = [RecycleBin]::SHEmptyRecycleBin([IntPtr]::Zero, "", 3)
Write-Host "OK:$result"
"""


def _parse_size(size_str):
    """将 PowerShell 返回的大小字符串解析为字节数。"""
    if not size_str:
        return 0
    size_str = size_str.strip()
    try:
        # 纯数字 = 字节
        return int(size_str)
    except ValueError:
        pass
    # 匹配 "5.16 MB", "80.0 KB", "0 字节" 等
    match = re.match(r'([\d,.]+)\s*(KB|MB|GB|TB|字节|B)', size_str, re.IGNORECASE)
    if match:
        value = float(match.group(1).replace(',', ''))
        unit = match.group(2).upper()
        multipliers = {'字节': 1, 'B': 1, 'KB': 1024, 'MB': 1024**2, 'GB': 1024**3, 'TB': 1024**4}
        return int(value * multipliers.get(unit, 1))
    return 0


def _parse_date(date_str):
    """将 PowerShell 返回的日期字符串解析为时间戳。"""
    if not date_str:
        return 0
    date_str = date_str.strip()
    # PowerShell 中文格式: "2026/9/12 19:06" (可能含有不可见 Unicode 字符)
    # 清理不可见字符
    date_str = re.sub(r'[\u200e\u200f\u200d\u202a-\u202e]', '', date_str)
    # 尝试多种格式
    formats = [
        '%Y/%m/%d %H:%M',
        '%Y/%m/%d %H:%M:%S',
        '%Y-%m-%d %H:%M',
        '%Y-%m-%d %H:%M:%S',
        '%Y/%m/%d',
    ]
    import time
    for fmt in formats:
        try:
            return time.mktime(time.strptime(date_str, fmt))
        except ValueError:
            continue
    return 0


class WindowsRecycleBin:
    """Windows 系统回收站管理器。"""

    @staticmethod
    def get_items():
        """获取回收站中所有项目。
        
        Returns:
            list[dict]: 每个项目包含:
                index (int), name (str), origin_path (str),
                deleted_date (str), size_bytes (int), size_display (str),
                file_type (str), is_folder (bool)
        """
        try:
            result = _run_ps(_LIST_SCRIPT)
        except Exception as e:
            raise RuntimeError(f"执行 PowerShell 失败: {e}")
        
        if not result:
            return []
        
        items = []
        total = 0
        for line in result.strip().split('\n'):
            line = line.strip()
            if line.startswith('TOTAL='):
                try:
                    total = int(line.split('=', 1)[1])
                except (ValueError, IndexError):
                    pass
            elif line.startswith('ITEM|'):
                try:
                    parts = line.split('|', 7)
                    if len(parts) >= 8:
                        index = int(parts[1])
                        name = parts[2] or ""
                        origin_path = parts[3] or ""
                        date_str = parts[4] or ""
                        size_str = parts[5] or ""
                        file_type = parts[6] or ""
                        is_folder = (parts[7] or "").lower() == 'true'
                        size_bytes = _parse_size(size_str)
                        items.append({
                            'index': index,
                            'name': name,
                            'origin_path': origin_path,
                            'deleted_date': date_str,
                            'deleted_ts': _parse_date(date_str),
                            'size_bytes': size_bytes,
                            'size_display': size_str,
                            'file_type': file_type,
                            'is_folder': is_folder,
                        })
                except Exception as e:
                    # 跳过解析失败的行，继续处理其他项目
                    continue
        return items

    @staticmethod
    def restore_item(index):
        """还原指定索引的项目到原始位置。
        
        Returns:
            tuple[bool, str]: (成功与否, 消息)
        """
        script = _RESTORE_SCRIPT.replace('{index}', str(index))
        result = _run_ps(script)
        if 'ERROR:' in result:
            return False, result.split('ERROR:', 1)[1].strip()
        return True, '已还原'

    @staticmethod
    def delete_item(index):
        """永久删除指定索引的项目。
        
        Returns:
            tuple[bool, str]: (成功与否, 消息)
        """
        script = _DELETE_SCRIPT.replace('{index}', str(index))
        result = _run_ps(script)
        if 'ERROR:' in result:
            return False, result.split('ERROR:', 1)[1].strip()
        return True, '已永久删除'

    @staticmethod
    def empty_bin():
        """清空回收站。
        
        Returns:
            tuple[bool, str]: (成功与否, 消息)
        """
        result = _run_ps(_EMPTY_VIA_SHELL32)
        # SHEmptyRecycleBin 返回 0 才算清空成功；非 0 说明没清掉，需要走回退。
        # 这里不能只判断 'OK:' 存在——失败时脚本同样会打印 OK:非零返回值。
        if 'OK:0' in result:
            return True, '回收站已清空'
        # 回退：逐项删除
        result = _run_ps(_EMPTY_SCRIPT)
        if 'OK:' in result:
            deleted = result.split(':', 1)[1].strip()
            return True, f'已清空 {deleted} 个项目'
        return False, result


def _run_ps(script):
    """执行 PowerShell 脚本并返回 stdout（强制 UTF-8 解码）。"""
    # 将脚本写入临时文件避免 shell 转义问题
    tmp_path = os.path.join(tempfile.gettempdir(), '_filecare_rb.ps1')
    try:
        # 使用 UTF-8 with BOM，让中文 Windows PowerShell 正确读取中文动词名
        with open(tmp_path, 'w', encoding='utf-8-sig') as f:
            f.write(script)
        proc = subprocess.run(
            ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', tmp_path],
            capture_output=True, timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0,
        )
        # 强制用 UTF-8 解码（PowerShell 脚本已设置 OutputEncoding = UTF8）
        return proc.stdout.decode('utf-8', errors='replace')
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass