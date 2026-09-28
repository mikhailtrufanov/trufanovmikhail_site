"""Deploy root HTML pages and the local media they reference to Timeweb."""

import argparse
import os
import posixpath
import re
import shutil
import subprocess
from ftplib import FTP
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[2]
MEDIA_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".mp4", ".webm", ".avif"}
PAGES = (
    "Political_case_vibory2021.html",
    "case.html",
    "case_marafon.html",
    "casino_case.html",
    "sites_prises.html",
    "index.html",
)
CSS_URL = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.IGNORECASE)


class MediaReferences(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if not value:
                continue
            if name in {"src", "poster", "href"}:
                self.urls.append(value)
            elif name == "srcset":
                self.urls.extend(part.strip().split()[0] for part in value.split(",") if part.strip())
            elif name == "style":
                self.urls.extend(match.group(2) for match in CSS_URL.finditer(value))


def local_media(url, page):
    if url.startswith(("data:", "//", "#")):
        return None
    parsed = urlsplit(url)
    if parsed.scheme or parsed.netloc:
        return None
    path = unquote(parsed.path).replace("\\", "/")
    if not path or Path(path).suffix.lower() not in MEDIA_EXTENSIONS:
        return None
    if path.startswith("/"):
        path = path.lstrip("/")
    else:
        path = posixpath.join(page.parent.as_posix(), path)
    normalized = posixpath.normpath(path)
    if normalized in {"", ".", ".."} or normalized.startswith("../"):
        raise ValueError(f"Media path outside site: {page}: {url}")
    return normalized


def site_files():
    tracked = set(subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().rstrip("\0").split("\0"))
    pages = PAGES
    for page in pages:
        if page not in tracked or not (ROOT / page).is_file():
            raise ValueError(f"Missing or untracked page: {page}")

    media = set()
    for page in pages:
        content = (ROOT / page).read_text(encoding="utf-8")
        parser = MediaReferences()
        parser.feed(content)
        urls = parser.urls + [match.group(2) for match in CSS_URL.finditer(content)]
        for url in urls:
            path = local_media(url, Path(page))
            if path:
                if path not in tracked or not (ROOT / path).is_file():
                    raise ValueError(f"Missing or untracked media: {page} -> {path}")
                media.add(path)

    return sorted(media) + sorted(page for page in pages if page != "index.html") + ["index.html"]


def stage(files):
    output = ROOT / ".deploy"
    output.mkdir(exist_ok=True)
    for path in files:
        destination = output / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / path, destination)


def verify_remote():
    with FTP(timeout=30) as ftp:
        ftp.connect(os.environ["FTP_SERVER"], 21)
        ftp.login(os.environ["FTP_USERNAME"], os.environ["FTP_PASSWORD"])
        ftp.cwd("/")
        names = {posixpath.basename(item.rstrip("/")) for item in ftp.nlst()}
        if "index.html" not in names:
            raise ValueError("FTP root has no index.html; upload stopped")
        print("Destination folder contains index.html")


if __name__ == "__main__":
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--stage", action="store_true", help="Copy selected files to .deploy")
    argument_parser.add_argument("--verify-remote", action="store_true", help="Check target FTP directory before upload")
    args = argument_parser.parse_args()
    if args.verify_remote:
        verify_remote()
        raise SystemExit(0)
    selected = site_files()
    print(f"Selected {len(selected)} files:")
    for selected_file in selected:
        print(f"  {selected_file}")
    if args.stage:
        stage(selected)
