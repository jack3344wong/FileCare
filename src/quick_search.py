# -*- coding: utf-8 -*-
"""
快速文件名搜索引擎 — 类 Everything 体验。

核心思路：
1. 首次启动或安装完成阶段遍历所有本地卷，将目录项写入 SQLite。
2. 后续刷新用扫描批次标记安全更新：新增/修改项被覆盖，已删除项在整卷
   扫描成功后清理；中途取消不会毁掉原有索引。
3. 搜索时直接查 SQLite，毫秒级响应。
"""
from __future__ import annotations

import os
import re
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import List, Dict, Optional

from PyQt5.QtCore import QThread, pyqtSignal


# ─── 索引数据库路径 ───────────────────────────────────────────────────────────
def _get_db_path() -> str:
    """索引数据库路径 - 从配置读取，默认 ~/.diskwise/index.db"""
    from settings import get_settings
    settings = get_settings()
    custom_path = settings.get("scan", "index_db_path", "")
    if custom_path:
        base = Path(custom_path)
    else:
        base = Path.home() / ".diskwise"
    base.mkdir(parents=True, exist_ok=True)
    return str(base / "index.db")


# ─── SQLite 索引管理 ──────────────────────────────────────────────────────────
class FileIndexDB:
    """管理文件名索引的 SQLite 数据库。"""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS files (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        path        TEXT    NOT NULL UNIQUE,
        name        TEXT    NOT NULL,
        name_lower  TEXT    NOT NULL,
        ext         TEXT    NOT NULL DEFAULT '',
        size        INTEGER NOT NULL DEFAULT 0,
        mtime       REAL    NOT NULL DEFAULT 0,
        is_dir      INTEGER NOT NULL DEFAULT 0,
        drive       TEXT    NOT NULL DEFAULT '',
        scan_token  TEXT    NOT NULL DEFAULT ''
    );

    CREATE INDEX IF NOT EXISTS idx_files_name_lower ON files(name_lower);
    CREATE INDEX IF NOT EXISTS idx_files_ext ON files(ext);
    CREATE INDEX IF NOT EXISTS idx_files_drive ON files(drive);
    CREATE INDEX IF NOT EXISTS idx_files_path ON files(path);

    CREATE TABLE IF NOT EXISTS index_meta (
        key   TEXT PRIMARY KEY,
        value TEXT
    );
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or _get_db_path()
        self._local = threading.local()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        """每个线程一个连接（SQLite 线程安全要求）。"""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(self.db_path, timeout=30)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA cache_size=-64000")  # 64MB cache
            conn.execute("PRAGMA mmap_size=268435456")  # 256MB mmap
            self._local.conn = conn
        return self._local.conn

    def _init_db(self):
        conn = self._get_conn()
        conn.executescript(self.SCHEMA)
        # 旧版数据库就地升级，不要求用户手动删除索引。
        columns = {row[1] for row in conn.execute("PRAGMA table_info(files)")}
        if "scan_token" not in columns:
            conn.execute("ALTER TABLE files ADD COLUMN scan_token TEXT NOT NULL DEFAULT ''")
        conn.commit()

    def close(self):
        """显式关闭当前线程的 SQLite 连接。"""
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    def insert_batch(self, records: List[tuple]):
        """批量写入目录项，保留稳定的行 id。"""
        if not records:
            return
        normalized = [record + ("",) if len(record) == 8 else record
                      for record in records]
        conn = self._get_conn()
        conn.executemany(
            "INSERT INTO files "
            "(path, name, name_lower, ext, size, mtime, is_dir, drive, scan_token) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(path) DO UPDATE SET "
            "name=excluded.name, name_lower=excluded.name_lower, ext=excluded.ext, "
            "size=excluded.size, mtime=excluded.mtime, is_dir=excluded.is_dir, "
            "drive=excluded.drive, scan_token=excluded.scan_token",
            normalized,
        )
        conn.commit()

    def mark_prefix_seen(self, prefix: str, scan_token: str):
        """扫描时无权进入的子树保留旧索引，避免短暂权限错误造成丢项。"""
        escaped = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        conn = self._get_conn()
        conn.execute(
            "UPDATE files SET scan_token=? WHERE path=? OR path LIKE ? ESCAPE '\\'",
            (scan_token, prefix, escaped + self._escape_like(os.sep) + "%"),
        )
        conn.commit()

    def finalize_drive_scan(self, drive: str, scan_token: str):
        """仅在整卷扫描完成后清理本轮未见的旧记录。"""
        conn = self._get_conn()
        conn.execute(
            "DELETE FROM files WHERE drive=? AND scan_token<>?", (drive, scan_token))
        conn.commit()

    def delete_by_path_prefix(self, prefix: str):
        """删除某路径前缀下的所有记录。"""
        conn = self._get_conn()
        child_pattern = (self._escape_like(prefix) +
                         self._escape_like(os.sep) + "%")
        conn.execute(
            "DELETE FROM files WHERE path=? OR path LIKE ? ESCAPE '\\'",
            (prefix, child_pattern))
        conn.commit()

    def delete_by_drive(self, drive: str):
        """删除某个磁盘的所有记录。"""
        conn = self._get_conn()
        conn.execute("DELETE FROM files WHERE drive = ?", (drive,))
        conn.commit()

    @staticmethod
    def _escape_like(value: str) -> str:
        return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    @staticmethod
    def _normalize_drive(drive: str) -> str:
        drive = os.path.abspath(drive)
        letter, _ = os.path.splitdrive(drive)
        return letter.upper() + os.sep if letter else drive

    def search(self, query: str, max_results: int = 1000,
               drive_filter: str = "", ext_filter: str = "",
               is_dir_filter: Optional[bool] = None,
               path_filter: str = "", offset: int = 0) -> List[Dict]:
        """
        搜索文件名。支持：
        - 普通子串匹配（默认）
        - 通配符 * 和 ?
        - ext:xxx 按扩展名过滤
        - path_filter: 路径前缀过滤
        - 结果按相关性排序（名称开头匹配 > 名称包含 > 路径包含）
        """
        if not query.strip():
            return []

        conn = self._get_conn()
        conditions = []
        params = []

        # 解析搜索修饰符
        clean_query = query.strip()
        ext_from_query = ""
        ext_match = re.search(r'\bext:(\S+)', clean_query)
        if ext_match:
            ext_from_query = ext_match.group(1).lower().lstrip(".")
            clean_query = clean_query[:ext_match.start()] + clean_query[ext_match.end():]
            clean_query = clean_query.strip()

        # 扩展名过滤（支持逗号分隔的多个扩展名）
        ext = ext_filter.lstrip(".").lower() or ext_from_query
        if ext:
            exts = [e.strip().lstrip(".") for e in ext.split(",") if e.strip()]
            if len(exts) == 1:
                conditions.append("ext = ?")
                params.append("." + exts[0] if not exts[0].startswith(".") else exts[0])
            elif len(exts) > 1:
                placeholders = ",".join(["?"] * len(exts))
                conditions.append(f"ext IN ({placeholders})")
                for e in exts:
                    params.append("." + e if not e.startswith(".") else e)

        # 路径前缀过滤
        if path_filter:
            absolute_filter = os.path.abspath(path_filter).rstrip("\\/")
            conditions.append("(path=? OR path LIKE ? ESCAPE '\\')")
            params.extend([
                absolute_filter,
                self._escape_like(absolute_filter) +
                self._escape_like(os.sep) + "%",
            ])

        # 磁盘过滤
        if drive_filter:
            conditions.append("drive = ?")
            params.append(self._normalize_drive(drive_filter))

        # 目录/文件过滤
        if is_dir_filter is not None:
            conditions.append("is_dir = ?")
            params.append(1 if is_dir_filter else 0)

        # 文件名匹配
        if clean_query:
            # 判断是否包含通配符
            if "*" in clean_query or "?" in clean_query:
                # 通配符模式 → 转为 SQL LIKE
                like_pattern = self._escape_like(clean_query.casefold())
                like_pattern = like_pattern.replace("*", "%").replace("?", "_")
                conditions.append("name_lower LIKE ? ESCAPE '\\'")
                params.append(like_pattern)
            else:
                # 子串匹配，按相关性排序
                like_pattern = f"%{self._escape_like(clean_query.casefold())}%"
                conditions.append("name_lower LIKE ? ESCAPE '\\'")
                params.append(like_pattern)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        # 排序：名称以查询开头 > 名称包含 > 路径包含，然后按大小降序
        if clean_query and "*" not in clean_query and "?" not in clean_query:
            order = """
                ORDER BY
                    CASE WHEN name_lower LIKE ? ESCAPE '\\' THEN 0
                         WHEN name_lower LIKE ? ESCAPE '\\' THEN 1
                         ELSE 2
                    END,
                    size DESC,
                    path COLLATE NOCASE
            """
            escaped_query = self._escape_like(clean_query.casefold())
            params.append(escaped_query + "%")
            params.append(f"%{escaped_query}%")
        else:
            order = "ORDER BY size DESC, path COLLATE NOCASE"

        sql = f"""
            SELECT path, name, ext, size, mtime, is_dir, drive
            FROM files
            WHERE {where_clause}
            {order}
            LIMIT ? OFFSET ?
        """
        params.extend([max_results, max(0, int(offset))])

        try:
            cursor = conn.execute(sql, params)
            results = []
            for row in cursor:
                results.append({
                    "path": row[0],
                    "name": row[1],
                    "ext": row[2],
                    "size": row[3],
                    "mtime": row[4],
                    "is_dir": bool(row[5]),
                    "drive": row[6],
                })
            return results
        except sqlite3.OperationalError:
            return []

    def count_search_results(self, query: str, drive_filter: str = "",
                             ext_filter: str = "", is_dir_filter: Optional[bool] = None,
                             path_filter: str = "") -> int:
        """返回与界面当前常用筛选一致的命中总数。"""
        # 复用查询构造的边界规则；计数时不做排序。
        clean_query = query.strip()
        ext_from_query = ""
        ext_match = re.search(r'\bext:(\S+)', clean_query)
        if ext_match:
            ext_from_query = ext_match.group(1).casefold().lstrip(".")
            clean_query = (clean_query[:ext_match.start()] +
                           clean_query[ext_match.end():]).strip()
        conditions, params = [], []
        ext = ext_filter.lstrip(".").casefold() or ext_from_query
        exts = [e.strip().lstrip(".") for e in ext.split(",") if e.strip()]
        if exts:
            conditions.append("ext IN (" + ",".join("?" for _ in exts) + ")")
            params.extend("." + e for e in exts)
        if path_filter:
            absolute_filter = os.path.abspath(path_filter).rstrip("\\/")
            conditions.append("(path=? OR path LIKE ? ESCAPE '\\')")
            params.extend([
                absolute_filter,
                self._escape_like(absolute_filter) +
                self._escape_like(os.sep) + "%",
            ])
        if drive_filter:
            conditions.append("drive=?")
            params.append(self._normalize_drive(drive_filter))
        if is_dir_filter is not None:
            conditions.append("is_dir=?")
            params.append(1 if is_dir_filter else 0)
        if clean_query:
            if "*" in clean_query or "?" in clean_query:
                pattern = self._escape_like(clean_query.casefold())
                pattern = pattern.replace("*", "%").replace("?", "_")
            else:
                pattern = "%" + self._escape_like(clean_query.casefold()) + "%"
            conditions.append("name_lower LIKE ? ESCAPE '\\'")
            params.append(pattern)
        where = " AND ".join(conditions) if conditions else "1=1"
        try:
            return int(self._get_conn().execute(
                f"SELECT COUNT(*) FROM files WHERE {where}", params).fetchone()[0])
        except sqlite3.OperationalError:
            return 0

    def get_total_count(self) -> int:
        conn = self._get_conn()
        try:
            return conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        except sqlite3.OperationalError:
            return 0

    def get_indexed_drives(self) -> List[str]:
        conn = self._get_conn()
        try:
            rows = conn.execute("SELECT DISTINCT drive FROM files").fetchall()
            return [r[0] for r in rows]
        except sqlite3.OperationalError:
            return []

    def set_meta(self, key: str, value: str):
        conn = self._get_conn()
        conn.execute("INSERT OR REPLACE INTO index_meta (key, value) VALUES (?, ?)", (key, value))
        conn.commit()

    def get_meta(self, key: str) -> Optional[str]:
        conn = self._get_conn()
        try:
            row = conn.execute("SELECT value FROM index_meta WHERE key = ?", (key,)).fetchone()
            return row[0] if row else None
        except Exception:
            return None

    def is_indexed(self, path: str, mtime: float) -> bool:
        """检查文件是否已索引且未修改"""
        conn = self._get_conn()
        try:
            cursor = conn.execute("SELECT mtime FROM files WHERE path = ?", (path,))
            row = cursor.fetchone()
            return row is not None and abs(row[0] - mtime) < 0.01
        except Exception:
            return False


# ─── 磁盘扫描线程 ─────────────────────────────────────────────────────────────
class IndexBuildThread(QThread):
    """后台线程：遍历磁盘并构建文件名索引。"""

    progress_signal = pyqtSignal(int, str)       # (已扫描文件数, 当前路径)
    drive_signal = pyqtSignal(str, str)           # (drive, status: "start"|"done")
    finished_signal = pyqtSignal(int, float)      # (总文件数, 耗时秒)
    cancelled_signal = pyqtSignal(int, float)     # (已保留的索引总数, 耗时秒)
    error_signal = pyqtSignal(str)

    def __init__(self, drives: Optional[List[str]] = None, incremental: bool = False,
                 db_path: Optional[str] = None,
                 time_budget_seconds: Optional[float] = None):
        super().__init__()
        self.db = FileIndexDB(db_path)
        self._cancel = False
        self._drives = drives
        self._incremental = incremental
        self._time_budget_seconds = time_budget_seconds
        self._deadline: Optional[float] = None
        self._budget_exhausted = False

    def cancel(self):
        self._cancel = True

    def _get_drives(self) -> List[str]:
        if self._drives:
            # 主程序传入的通常是卷根目录；保留明确子目录也方便
            # 安全测试和未来的“仅索引指定位置”功能。
            return sorted({os.path.abspath(d) for d in self._drives
                           if os.path.isdir(d)})
        import psutil
        drives = []
        try:
            for part in psutil.disk_partitions(all=True):
                drive, _ = os.path.splitdrive(part.mountpoint)
                root = drive.upper() + os.sep if drive else part.mountpoint
                if os.path.isdir(root):
                    drives.append(root)
        except Exception:
            pass
        # psutil 在某些 Windows 配置下会漏掉本地卷，用系统位图补全。
        if os.name == "nt":
            try:
                import ctypes
                mask = ctypes.windll.kernel32.GetLogicalDrives()
                for index in range(26):
                    if mask & (1 << index):
                        root = f"{chr(65 + index)}:{os.sep}"
                        if os.path.isdir(root):
                            drives.append(root)
            except Exception:
                pass
        return sorted(set(drives))

    def run(self):
        start_time = time.time()
        if self._time_budget_seconds is not None:
            self._deadline = time.monotonic() + max(1.0, self._time_budget_seconds)
        drives = self._get_drives()
        scan_errors = 0

        if not drives:
            self.error_signal.emit("没有找到可索引的磁盘或目录")
            self.db.set_meta("index_complete", "0")
            self.finished_signal.emit(self.db.get_total_count(), 0.0)
            self.db.close()
            return

        for drive in drives:
            if self._cancel or self._past_deadline():
                break
            self.drive_signal.emit(drive, "start")
            try:
                self._scan_drive(drive)
            except Exception as e:
                scan_errors += 1
                self.error_signal.emit(f"扫描 {drive} 失败: {e}")
            self.drive_signal.emit(drive, "done")

        elapsed = time.time() - start_time
        total = self.db.get_total_count()
        if self._cancel:
            self.cancelled_signal.emit(total, elapsed)
            self.db.close()
            return
        self.db.set_meta("last_index_time", str(time.time()))
        self.db.set_meta("total_files", str(total))
        incomplete = scan_errors or self._budget_exhausted
        self.db.set_meta("index_complete", "0" if incomplete else "1")
        self.finished_signal.emit(total, elapsed)
        self.db.close()

    def _past_deadline(self) -> bool:
        if self._deadline is None or time.monotonic() < self._deadline:
            return False
        self._budget_exhausted = True
        return True

    def _scan_drive(self, drive: str) -> int:
        """遍历一个磁盘，不主动排除任何目录项。"""
        batch = []
        count = 0
        # 大批量事务避免为每两千项都落盘一次；索引构建主要受目录遍历和
        # SQLite 提交影响，增大批量能明显缩短首次构建时间。
        BATCH_SIZE = 10000
        scan_token = uuid.uuid4().hex

        def flush():
            if batch:
                self.db.insert_batch(batch)
                batch.clear()

        def on_walk_error(exc):
            # 资源管理器可以显示但当前用户无权遍历的子树，
            # 保留已有索引，不将“读取失败”误判成“已删除”。
            path = getattr(exc, "filename", "")
            if path:
                self.db.mark_prefix_seen(path, scan_token)

        # os.walk 会只返回名称，随后又对每个项目 os.stat 一次。直接使用
        # scandir 可复用系统已取到的目录项信息，大型磁盘会快得多。
        pending_dirs = [drive]
        while pending_dirs:
            if self._cancel or self._past_deadline():
                break
            root = pending_dirs.pop()
            try:
                with os.scandir(root) as entries:
                    for entry in entries:
                        if self._cancel or self._past_deadline():
                            break
                        name = entry.name
                        full_path = entry.path
                        try:
                            is_dir = entry.is_dir(follow_symlinks=False)
                            st = entry.stat(follow_symlinks=False)
                            attrs = getattr(st, "st_file_attributes", 0)
                            is_reparse = entry.is_symlink() or bool(attrs & 0x400)
                            batch.append((
                                full_path, name, name.casefold(),
                                "" if is_dir else os.path.splitext(name)[1].lower(),
                                0 if is_dir else st.st_size, st.st_mtime,
                                1 if is_dir else 0, drive, scan_token,
                            ))
                            count += 1
                            if is_dir and not is_reparse:
                                pending_dirs.append(full_path)
                        except (OSError, PermissionError):
                            # 能列出但无法读取属性的项仍可按名称搜索。
                            batch.append((
                                full_path, name, name.casefold(),
                                "", 0, 0.0, 0, drive, scan_token,
                            ))
                            count += 1
                        if len(batch) >= BATCH_SIZE:
                            flush()
                            self.progress_signal.emit(count, root)
            except (OSError, PermissionError) as exc:
                on_walk_error(exc)

        # 写入剩余
        flush()
        if not self._cancel and not self._budget_exhausted:
            self.db.finalize_drive_scan(drive, scan_token)

        return count


# ─── 搜索引擎（对外接口） ─────────────────────────────────────────────────────
class QuickSearchEngine:
    """
    快速搜索引擎的对外接口。
    整合索引构建、搜索查询、文件监控。
    """

    def __init__(self):
        self.db = FileIndexDB()
        self._index_thread: Optional[IndexBuildThread] = None

    @property
    def is_indexed(self) -> bool:
        """是否已经建过索引。"""
        return self.db.get_total_count() > 0

    @property
    def is_index_complete(self) -> bool:
        """是否已完整扫描所有可访问磁盘。"""
        return self.db.get_meta("index_complete") == "1"

    @property
    def total_files(self) -> int:
        return self.db.get_total_count()

    @property
    def last_index_time(self) -> Optional[float]:
        val = self.db.get_meta("last_index_time")
        return float(val) if val else None

    def start_indexing(self, drives: Optional[List[str]] = None, incremental: bool = False) -> IndexBuildThread:
        """启动后台索引构建。"""
        if self._index_thread and self._index_thread.isRunning():
            return self._index_thread
        # 如果已有索引且未指定强制重建，自动使用增量模式
        if not incremental and self.is_indexed:
            incremental = True
        self._index_thread = IndexBuildThread(drives=drives, incremental=incremental)
        self._index_thread.start()
        return self._index_thread

    def cancel_indexing(self):
        if self._index_thread and self._index_thread.isRunning():
            self._index_thread.cancel()

    def is_indexing(self) -> bool:
        return self._index_thread is not None and self._index_thread.isRunning()

    def close(self):
        if self._index_thread and self._index_thread.isRunning():
            self._index_thread.cancel()
            self._index_thread.wait()
        self.db.close()

    def search(self, query: str, max_results: int = 500,
               drive_filter: str = "", ext_filter: str = "",
               is_dir_filter: Optional[bool] = None,
               path_filter: str = "", offset: int = 0) -> List[Dict]:
        """搜索文件。"""
        return self.db.search(
            query, max_results, drive_filter, ext_filter,
            is_dir_filter, path_filter, offset)

    def count_search_results(self, query: str, drive_filter: str = "",
                             ext_filter: str = "", is_dir_filter: Optional[bool] = None,
                             path_filter: str = "") -> int:
        return self.db.count_search_results(
            query, drive_filter=drive_filter,
            ext_filter=ext_filter, is_dir_filter=is_dir_filter,
            path_filter=path_filter)

    def get_indexed_drives(self) -> List[str]:
        return self.db.get_indexed_drives()

    def rebuild_drive(self, drive: str):
        """重建某个磁盘的索引。"""
        return self.start_indexing(drives=[drive], incremental=False)

    def force_rebuild(self, drives: Optional[List[str]] = None) -> IndexBuildThread:
        """强制重建索引（不使用增量）。"""
        if self._index_thread and self._index_thread.isRunning():
            self._index_thread.cancel()
            # 不允许两个索引线程同时清理同一数据库。
            self._index_thread.wait()
        self._index_thread = IndexBuildThread(drives=drives, incremental=False)
        self._index_thread.start()
        return self._index_thread


def build_name_index_sync(drives: Optional[List[str]] = None,
                           db_path: Optional[str] = None,
                           time_budget_seconds: Optional[float] = None
                           ) -> tuple[int, float, List[str]]:
    """供安装程序调用的无界面首次索引入口。"""
    result = {"total": 0, "elapsed": 0.0}
    errors: List[str] = []
    thread = IndexBuildThread(
        drives=drives, incremental=False, db_path=db_path,
        time_budget_seconds=time_budget_seconds)
    thread.finished_signal.connect(
        lambda total, elapsed: result.update(total=total, elapsed=elapsed))
    thread.error_signal.connect(errors.append)
    # 同步调用 run，不创建隐藏 GUI；安装器等待返回即可。
    thread.run()
    thread.db.close()
    return int(result["total"]), float(result["elapsed"]), errors
