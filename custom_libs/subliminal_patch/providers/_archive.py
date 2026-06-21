# -*- coding: utf-8 -*-

import logging
import io
import os
import shutil
import subprocess
import tempfile
import zipfile

from subliminal.video import Episode
from subliminal_patch.providers.utils import get_archive_from_bytes
from subliminal_patch.providers.utils import get_subtitle_from_archive


logger = logging.getLogger(__name__)

_ARCHIVE_EXTENSIONS = (".zip", ".rar", ".7z")
_SUBTITLE_EXTENSIONS = (".srt", ".sub", ".ssa", ".ass")


def subtitle_content_from_bytes(content, video=None, max_depth=2):
    archive = get_archive_from_bytes(content)
    if archive is not None:
        extracted = subtitle_content_from_archive(archive, video=video, max_depth=max_depth)
        if extracted:
            return extracted

    return _subtitle_content_with_7z(content, video=video)


def subtitle_content_from_archive(archive, video=None, max_depth=2):
    episode = video.episode if isinstance(video, Episode) else None

    try:
        content = get_subtitle_from_archive(
            archive,
            episode=episode,
            get_first_subtitle=not isinstance(video, Episode),
        )
    except Exception:
        logger.debug("Could not read subtitle from archive", exc_info=True)
        content = None

    if content or max_depth <= 0:
        return content

    try:
        names = archive.namelist()
    except Exception:
        logger.debug("Could not list archive entries", exc_info=True)
        return None

    for name in names:
        if not name.lower().endswith(_ARCHIVE_EXTENSIONS):
            continue

        try:
            nested_content = archive.read(name)
        except Exception:
            logger.debug("Could not read nested archive %r", name, exc_info=True)
            continue

        content = subtitle_content_from_bytes(
            nested_content,
            video=video,
            max_depth=max_depth - 1,
        )
        if content:
            return content

    return None


def _subtitle_content_with_7z(content, video=None):
    tool = _sevenzip_tool()
    if tool is None:
        return None

    with tempfile.TemporaryDirectory(prefix="bazarr-archive-") as tmp_dir:
        archive_path = os.path.join(tmp_dir, "subtitle.archive")
        extract_dir = os.path.join(tmp_dir, "extract")
        os.mkdir(extract_dir)

        with open(archive_path, "wb") as handle:
            handle.write(content)

        result = subprocess.run(
            [tool, "x", "-y", "-bd", "-o%s" % extract_dir, archive_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if result.returncode != 0:
            return None

        archive = _zip_subtitle_files(extract_dir)
        if archive is None:
            return None

        return subtitle_content_from_archive(archive, video=video, max_depth=0)


def _sevenzip_tool():
    for tool in ("7z", "7za"):
        path = shutil.which(tool)
        if path:
            return path
    return None


def _zip_subtitle_files(root):
    subtitle_files = []
    for base, _, files in os.walk(root):
        for filename in files:
            if filename.lower().endswith(_SUBTITLE_EXTENSIONS):
                subtitle_files.append(os.path.join(base, filename))

    if not subtitle_files:
        return None

    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        for path in subtitle_files:
            archive.write(path, os.path.relpath(path, root))

    payload.seek(0)
    return zipfile.ZipFile(payload)
