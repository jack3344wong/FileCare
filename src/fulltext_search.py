# -*- coding: utf-8 -*-
"""
全文搜索引擎 — 类 Anytxt Searcher 体验。

核心思路：
1. 使用 SQLite FTS5 建立文档内容的全文索引
2. 后台线程遍历文件，提取内容并写入索引
3. 搜索时查询 FTS5，返回匹配片段（snippet）

支持格式：PDF、DOCX、XLSX、PPTX、TXT、RTF 等（见 content_extractor.py）
"""
from __future__ import annotations

import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import List, Dict, Optional

from PyQt5.QtCore import QThread, pyqtSignal

from content_extractor import ContentExtractor, SUPPORTED_EXTENSIONS


# ─── 索引数据库路径 ───────────────────────────────────────────────────────────
def _get_fts_db_path() -> str:
    """全文索引数据库路径 - 从配置读取，默认 ~/.diskwise/fulltext.db"""
    from settings import get_settings
    settings = get_settings()
    custom_path = settings.get("scan", "index_db_path", "")
    if custom_path:
        base = Path(custom_path)
    else:
        base = Path.home() / ".diskwise"
    base.mkdir(parents=True, exist_ok=True)
    return str(base / "fulltext.db")


# ─── SQLite FTS5 索引管理 ─────────────────────────────────────────────────────
class FullTextIndexDB:
    """管理文档内容全文索引的 SQLite 数据库。"""

    SCHEMA = """
    -- 文件元数据表
    CREATE TABLE IF NOT EXISTS documents (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        path        TEXT    NOT NULL UNIQUE,
        name        TEXT    NOT NULL,
        ext         TEXT    NOT NULL,
        size        INTEGER NOT NULL DEFAULT 0,
        mtime       REAL    NOT NULL DEFAULT 0,
        indexed_at  REAL    NOT NULL DEFAULT 0,
        content_len INTEGER NOT NULL DEFAULT 0,
        content     TEXT    NOT NULL DEFAULT ''
    );

    -- FTS5 全文索引表（独立存储，按 documents.id 手动同步）
    CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
        path,
        content,
        tokenize='unicode61'
    );

    -- 索引元数据
    CREATE TABLE IF NOT EXISTS fts_meta (
        key   TEXT PRIMARY KEY,
        value TEXT
    );
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or _get_fts_db_path()
        self._local = threading.local()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        """每个线程一个连接。"""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(self.db_path, timeout=30)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA cache_size=-64000")
            self._local.conn = conn
        return self._local.conn

    def _init_db(self):
        conn = self._get_conn()
        conn.executescript(self.SCHEMA)
        # 迁移：为旧版 documents 表添加 content 列（如果不存在）
        try:
            conn.execute("SELECT content FROM documents LIMIT 1")
        except sqlite3.OperationalError:
            conn.execute("ALTER TABLE documents ADD COLUMN content TEXT NOT NULL DEFAULT ''")
        conn.commit()

    def close(self):
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    def upsert_document(self, path: str, name: str, ext: str, size: int,
                        mtime: float, content: str) -> int:
        """
        插入或更新文档记录和内容。
        返回文档 ID。
        """
        conn = self._get_conn()
        now = time.time()

        # 先检查是否已存在
        cursor = conn.execute("SELECT id FROM documents WHERE path = ?", (path,))
        row = cursor.fetchone()

        if row:
            doc_id = row[0]
            # 更新主表（包含 content 字段）
            conn.execute(
                "UPDATE documents SET name=?, ext=?, size=?, mtime=?, indexed_at=?, content_len=?, content=? WHERE id=?",
                (name, ext, size, mtime, now, len(content), content, doc_id)
            )
            # 当前是普通 FTS5 表（非 external-content 表），直接按 rowid 删除。
            conn.execute("DELETE FROM documents_fts WHERE rowid = ?", (doc_id,))
            conn.execute(
                "INSERT INTO documents_fts(rowid, path, content) VALUES (?, ?, ?)",
                (doc_id, path, content)
            )
        else:
            # 插入主表（包含 content 字段）
            cursor = conn.execute(
                "INSERT INTO documents (path, name, ext, size, mtime, indexed_at, content_len, content) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (path, name, ext, size, mtime, now, len(content), content)
            )
            doc_id = cursor.lastrowid
            # 插入 FTS（带内容）
            conn.execute(
                "INSERT INTO documents_fts(rowid, path, content) VALUES (?, ?, ?)",
                (doc_id, path, content)
            )

        return doc_id

    def commit(self):
        """手动提交事务（批量索引用）。"""
        conn = self._get_conn()
        conn.commit()

    def clear_all(self):
        """清空所有索引数据（用于强制重建）。"""
        conn = self._get_conn()
        conn.execute("DELETE FROM documents_fts")
        conn.execute("DELETE FROM documents")
        conn.execute("DELETE FROM fts_meta")
        conn.commit()

    def delete_document(self, path: str):
        """删除文档记录。"""
        conn = self._get_conn()
        row = conn.execute("SELECT id FROM documents WHERE path = ?", (path,)).fetchone()
        if row:
            conn.execute("DELETE FROM documents_fts WHERE rowid = ?", (row[0],))
            conn.execute("DELETE FROM documents WHERE id = ?", (row[0],))
        conn.commit()

    def prune_missing(self, scan_paths: List[str], seen_paths: set[str],
                      preserved_prefixes: Optional[List[str]] = None):
        """成功扫描后清理已删除的文档；取消时不调用。"""
        roots = [os.path.normcase(os.path.abspath(path)).rstrip("\\/")
                 for path in scan_paths]
        normalized_seen = {os.path.normcase(os.path.abspath(path))
                           for path in seen_paths}
        preserved = [os.path.normcase(os.path.abspath(path)).rstrip("\\/")
                     for path in (preserved_prefixes or [])]
        conn = self._get_conn()
        rows = conn.execute("SELECT id, path FROM documents").fetchall()
        stale_ids = []
        for doc_id, path in rows:
            normalized = os.path.normcase(os.path.abspath(path))
            in_scope = any(normalized == root or
                           normalized.startswith(root + os.sep) for root in roots)
            must_preserve = any(
                normalized == prefix or normalized.startswith(prefix + os.sep)
                for prefix in preserved)
            if in_scope and not must_preserve and normalized not in normalized_seen:
                stale_ids.append((doc_id,))
        if stale_ids:
            conn.executemany("DELETE FROM documents_fts WHERE rowid = ?", stale_ids)
            conn.executemany("DELETE FROM documents WHERE id = ?", stale_ids)
            conn.commit()

    @staticmethod
    def _extension_condition(ext_filter: str):
        exts = [ext.strip().lower() for ext in ext_filter.split(",") if ext.strip()]
        exts = [ext if ext.startswith(".") else "." + ext for ext in exts]
        if not exts:
            return "", []
        return "ext IN (" + ",".join("?" for _ in exts) + ")", exts

    @staticmethod
    def _path_condition(path_filter: str):
        if not path_filter:
            return "", []
        absolute = os.path.abspath(path_filter).rstrip("\\/")
        escaped = absolute.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        separator = os.sep.replace("\\", "\\\\")
        return "(path=? OR path LIKE ? ESCAPE '\\')", [
            absolute, escaped + separator + "%"]

    def search(self, query: str, max_results: int = 100,
               ext_filter: str = "", path_filter: str = "") -> List[Dict]:
        """
        全文搜索。

        Args:
            query: 搜索关键词
            max_results: 最大结果数
            ext_filter: 扩展名过滤（如 ".pdf"）
            path_filter: 路径前缀过滤

        Returns:
            匹配结果列表，每项包含 path, name, snippet, rank
        """
        if not query.strip():
            return []

        conn = self._get_conn()

        # 检测是否包含中文字符
        has_chinese = any('\u4e00' <= c <= '\u9fff' for c in query)

        # 对于中文或包含中文的查询，直接使用 LIKE 子串匹配
        # 因为 FTS5 的 unicode61 分词器不支持中文分词
        if has_chinese:
            return self._fallback_search(query, max_results, ext_filter, path_filter)

        # 对于纯英文/数字查询，尝试使用 FTS5
        fts_query = query.strip()
        conditions = ["documents_fts MATCH ?"]
        params = [fts_query]

        if ext_filter:
            ext_condition, ext_params = self._extension_condition(ext_filter)
            conditions.append("documents." + ext_condition)
            params.extend(ext_params)

        if path_filter:
            path_condition, path_params = self._path_condition(path_filter)
            conditions.append(path_condition.replace("path", "documents.path"))
            params.extend(path_params)

        where_clause = " AND ".join(conditions)

        sql = f"""
            SELECT
                documents.path,
                documents.name,
                documents.ext,
                documents.size,
                documents.mtime,
                snippet(documents_fts, 1, '<b>', '</b>', '...', 32) as snippet,
                rank
            FROM documents_fts
            JOIN documents ON documents.id = documents_fts.rowid
            WHERE {where_clause}
            ORDER BY rank
            LIMIT ?
        """
        params.append(max_results)

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
                    "snippet": row[5],
                    "rank": row[6],
                })
            return results
        except sqlite3.OperationalError:
            # FTS 查询语法错误，回退到 LIKE 搜索
            return self._fallback_search(query, max_results, ext_filter, path_filter)

    def _fallback_search(self, query: str, max_results: int,
                         ext_filter: str, path_filter: str) -> List[Dict]:
        """当 FTS 查询失败时，使用 LIKE 子串匹配。"""
        conn = self._get_conn()
        escaped_query = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        conditions = ["content LIKE ? ESCAPE '\\'"]
        params = [f"%{escaped_query}%"]

        if ext_filter:
            ext_condition, ext_params = self._extension_condition(ext_filter)
            conditions.append(ext_condition)
            params.extend(ext_params)

        if path_filter:
            path_condition, path_params = self._path_condition(path_filter)
            conditions.append(path_condition)
            params.extend(path_params)

        where_clause = " AND ".join(conditions)

        sql = f"""
            SELECT path, name, ext, size, mtime, content
            FROM documents
            WHERE {where_clause}
            LIMIT ?
        """
        params.append(max_results)

        try:
            cursor = conn.execute(sql, params)
            results = []
            for row in cursor:
                # 生成简单 snippet
                content = row[5]
                snippet = self._generate_snippet(content, query)
                results.append({
                    "path": row[0],
                    "name": row[1],
                    "ext": row[2],
                    "size": row[3],
                    "mtime": row[4],
                    "snippet": snippet,
                    "rank": 0.0,
                })
            return results
        except Exception:
            return []

    def _generate_snippet(self, content: str, query: str, context_chars: int = 80) -> str:
        """生成匹配片段，高亮关键词。显示所有匹配位置。"""
        if not content:
            return ""

        import re as _re
        # 查找所有匹配位置
        query_lower = query.lower()
        content_lower = content.lower()
        positions = []
        start = 0
        while True:
            pos = content_lower.find(query_lower, start)
            if pos == -1:
                break
            positions.append(pos)
            start = pos + len(query)

        if not positions:
            # 未找到，返回开头
            return content[:context_chars * 2] + "..." if len(content) > context_chars * 2 else content

        # 生成包含所有匹配的片段（合并重叠的区间）
        snippets = []
        for pos in positions:
            s = max(0, pos - context_chars)
            e = min(len(content), pos + len(query) + context_chars)
            snippet = content[s:e]
            if s > 0:
                snippet = "..." + snippet
            if e < len(content):
                snippet = snippet + "..."
            # 高亮关键词（大小写不敏感）
            pattern = _re.compile(_re.escape(query), _re.IGNORECASE)
            snippet = pattern.sub(lambda m: f"<b>{m.group(0)}</b>", snippet)
            snippets.append(snippet)
            # 最多展示 5 个匹配片段
            if len(snippets) >= 5:
                break

        return "\n---\n".join(snippets)

    def get_document_content(self, path: str) -> Optional[str]:
        """获取已索引文档的内容。"""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "SELECT content FROM documents WHERE path = ?",
                (path,)
            )
            row = cursor.fetchone()
            return row[0] if row else None
        except Exception:
            return None

    def is_indexed(self, path: str, mtime: float) -> bool:
        """检查文件是否已索引且是最新的。"""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "SELECT mtime FROM documents WHERE path = ?",
                (path,)
            )
            row = cursor.fetchone()
            return row is not None and abs(row[0] - mtime) < 0.01
        except Exception:
            return False

    def get_total_count(self) -> int:
        conn = self._get_conn()
        try:
            return conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        except Exception:
            return 0

    def set_meta(self, key: str, value: str):
        conn = self._get_conn()
        conn.execute("INSERT OR REPLACE INTO fts_meta (key, value) VALUES (?, ?)", (key, value))
        conn.commit()

    def get_meta(self, key: str) -> Optional[str]:
        conn = self._get_conn()
        try:
            row = conn.execute("SELECT value FROM fts_meta WHERE key = ?", (key,)).fetchone()
            return row[0] if row else None
        except Exception:
            return None


# ─── 全文索引构建线程 ─────────────────────────────────────────────────────────
class FullTextIndexThread(QThread):
    """后台线程：遍历文件并构建全文索引。"""

    progress_signal = pyqtSignal(int, int, str)  # (已索引数, 总数, 当前文件)
    finished_signal = pyqtSignal(int, float)     # (已索引数, 耗时秒)
    cancelled_signal = pyqtSignal(int, float)
    error_signal = pyqtSignal(str)

    def __init__(self, paths: Optional[List[str]] = None, force_reindex: bool = False):
        super().__init__()
        self.db = FullTextIndexDB()
        self.extractor = ContentExtractor()
        self._cancel = False
        self._paths = paths
        self._force_reindex = force_reindex

    def cancel(self):
        self._cancel = True

    def _get_scan_paths(self) -> List[str]:
        """获取要扫描的路径列表。

        文件名搜索会索引所有本地卷；内容搜索也必须使用同一默认范围，
        否则用户能按名称找到的 D 盘、移动硬盘等文档不会进入内容索引。
        """
        if self._paths:
            return self._paths
        drives = []
        try:
            import psutil
            for part in psutil.disk_partitions(all=False):
                drive, _ = os.path.splitdrive(part.mountpoint)
                root = drive.upper() + os.sep if drive else part.mountpoint
                if os.path.isdir(root):
                    drives.append(root)
        except Exception:
            pass
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
        indexed_count = 0
        error_count = 0
        last_error_msg = ""

        scan_paths = self._get_scan_paths()
        inaccessible_paths = []

        def on_walk_error(exc):
            path = getattr(exc, "filename", "")
            if path:
                inaccessible_paths.append(path)

        # 收集所有可索引文件
        all_files = []
        for scan_path in scan_paths:
            if self._cancel:
                break
            for root, dirs, files in os.walk(
                    scan_path, topdown=True, onerror=on_walk_error,
                    followlinks=False):
                if self._cancel:
                    break
                # 跳过系统/依赖目录；用户资料、网盘、微信和其他数据盘目录保留。
                dirs[:] = [d for d in dirs if not d.startswith(".") and d not in
                          {"$RECYCLE.BIN", "System Volume Information", "node_modules", "__pycache__",
                           "Windows", "Program Files", "Program Files (x86)", "ProgramData"}]

                for name in files:
                    ext = os.path.splitext(name)[1].lower()
                    if ext in SUPPORTED_EXTENSIONS:
                        full_path = os.path.join(root, name)
                        try:
                            st = os.stat(full_path, follow_symlinks=False)
                            # 跳过过大的文件（>100MB）
                            if st.st_size > 100 * 1024 * 1024:
                                continue
                            all_files.append((full_path, name, ext, st.st_size, st.st_mtime))
                        except (OSError, PermissionError):
                            continue

        total = len(all_files)
        self.progress_signal.emit(0, total, "开始索引...")

        # 索引文件 — 批量提交（每50个文件提交一次事务，大幅提速）
        BATCH_SIZE = 50
        for i, (path, name, ext, size, mtime) in enumerate(all_files):
            if self._cancel:
                break

            # 检查是否已索引且是最新的（仅增量模式）
            if not self._force_reindex and self.db.is_indexed(path, mtime):
                indexed_count += 1
                if i % 50 == 0:
                    self.progress_signal.emit(indexed_count, total, f"跳过已索引: {name}")
                continue

            # 提取内容
            if i % 50 == 0:
                self.progress_signal.emit(indexed_count, total, f"正在索引: {name}")
            content = self.extractor.extract(path)

            if content:
                try:
                    self.db.upsert_document(path, name, ext, size, mtime, content)
                    indexed_count += 1
                except Exception as e:
                    error_count += 1
                    last_error_msg = f"{path}: {e}"
            else:
                # 文档已变更但无法再提取时，不保留过期内容。
                self.db.delete_document(path)

            # 批量提交
            if (i + 1) % BATCH_SIZE == 0:
                self.db.commit()

        # 最终提交
        self.db.commit()

        if not self._cancel:
            self.db.prune_missing(
                scan_paths, {item[0] for item in all_files}, inaccessible_paths)

        elapsed = time.time() - start_time
        indexed_count = self.db.get_total_count()
        if not self._cancel:
            self.db.set_meta("last_index_time", str(time.time()))
            self.db.set_meta("total_documents", str(indexed_count))
            if self._paths is None:
                self.db.set_meta("scan_scope_version", "2")
        
        # 只在有错误时发送一次汇总错误信息
        if error_count > 0:
            self.error_signal.emit(f"索引完成，但有 {error_count} 个文件失败。最后一个错误: {last_error_msg}")
        
        if self._cancel:
            self.cancelled_signal.emit(indexed_count, elapsed)
        else:
            self.finished_signal.emit(indexed_count, elapsed)
        self.db.close()


# ─── 全文搜索引擎（对外接口） ─────────────────────────────────────────────────
class FullTextSearchEngine:
    """
    全文搜索引擎的对外接口。
    整合索引构建和搜索查询。
    """

    def __init__(self):
        self.db = FullTextIndexDB()
        self.extractor = ContentExtractor()
        self._index_thread: Optional[FullTextIndexThread] = None

    @property
    def is_indexed(self) -> bool:
        """是否已经建过索引。"""
        return self.db.get_total_count() > 0

    @property
    def total_documents(self) -> int:
        return self.db.get_total_count()

    @property
    def last_index_time(self) -> Optional[float]:
        val = self.db.get_meta("last_index_time")
        return float(val) if val else None

    @property
    def needs_full_disk_refresh(self) -> bool:
        """旧版仅索引桌面/文档/下载，升级后补建一次所有本地卷索引。"""
        return self.db.get_meta("scan_scope_version") != "2"

    def start_indexing(self, paths: Optional[List[str]] = None,
                       force_reindex: bool = False) -> FullTextIndexThread:
        """启动后台索引构建。"""
        if self._index_thread and self._index_thread.isRunning():
            return self._index_thread
        # 如果已有索引且未指定强制重建，自动使用增量模式
        if not force_reindex and self.is_indexed:
            force_reindex = False  # 使用增量模式
        self._index_thread = FullTextIndexThread(paths=paths, force_reindex=force_reindex)
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

    def search(self, query: str, max_results: int = 100,
               ext_filter: str = "", path_filter: str = "") -> List[Dict]:
        """搜索文档内容。"""
        return self.db.search(query, max_results, ext_filter, path_filter)

    def get_content(self, path: str) -> Optional[str]:
        """获取已索引文档的内容。"""
        return self.db.get_document_content(path)

    def extract_and_preview(self, path: str, max_chars: int = 10000) -> str:
        """实时提取文件内容用于预览（不依赖索引）。"""
        return self.extractor.extract(path, max_chars)

    def can_extract(self, path: str) -> bool:
        """检查是否支持提取该文件。"""
        return self.extractor.can_extract(path)

    def force_reindex(self, paths: Optional[List[str]] = None) -> FullTextIndexThread:
        """强制重建全文索引（不使用增量）。"""
        if self._index_thread and self._index_thread.isRunning():
            self._index_thread.cancel()
            self._index_thread.wait()
        self._index_thread = FullTextIndexThread(paths=paths, force_reindex=True)
        self._index_thread.start()
        return self._index_thread
