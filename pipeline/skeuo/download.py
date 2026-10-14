"""
Downloads restore IPSWs from Apple's servers into a cache directory.

Apple still serves the iPod touch 2G IPSWs of the firmware Skeuo supports, except iPhone OS 3.0: that was a paid
upgrade for the iPod touch, sold through the iTunes Store, and its IPSW was never on a public URL (Apple's catalog
only names a protected:// asset, and only for 3.1.3). A 3.0 device needs a local IPSW.

Apple's version catalog (itunes.apple.com/...MZITunesClientCheck/version) only publishes a FirmwareSHA1 for the
firmware it currently offers, which for the iPod touch 2G is 4.1 and 4.2.1. What Apple's download server does
publish for every file is its size and an ETag that is the file's MD5. A download is checked against both, as the
server reports them, and against the SHA-1 below, which matches the IPSWs as archived elsewhere (ipsw.me) and a
copy downloaded from Apple in 2008.

Downloads resume: the data goes to <name>.part, and a later download continues it with a Range request, as long as
the server's ETag is still the one it started with (kept in <name>.part.etag).
"""
import hashlib
import os
import sys
import urllib.error
import urllib.request

FIRMWARES = {
    "2.1.1": {
        "build": "5F138",
        "url": "https://secure-appldnld.apple.com/iPod/SBML/osx/bundles/061-5494.20080909.8i9o0/"
               "iPod2,1_2.1.1_5F138_Restore.ipsw",
        "size": 282083944,
        "sha1": "c3c700be49ad227d1152188e7c1e46b8958fd1e4",
    },
    "2.2": {
        "build": "5G77a",
        "url": "https://secure-appldnld.apple.com/iPod/SBML/osx/061-5358.20081120.Gtghy/iPod2,1_2.2_5G77a_Restore.ipsw",
        "size": 291123491,
        "sha1": "34a0a489605f34d6cc6c9954edcaaf9a050deedc",
    },
    "3.0": {
        "build": "7A341",
        "url": None,  # never on a public URL, see above
    },
    "4.0": {
        "build": "8A293",
        "url": "https://secure-appldnld.apple.com/iPhone4/061-7435.20100621.tr49t/iPod2,1_4.0_8A293_Restore.ipsw",
        "size": 330278777,
        "sha1": "c026c373bc535496a6f901de2ba37d4a487413bf",
    },
}

CHUNK = 1 << 20


class DownloadError(Exception):
    pass


class Cancelled(DownloadError):
    def __init__(self):
        super().__init__("download cancelled")


def default_cache():
    """<the platform's data directory>/Skeuo/ipsw, or $SKEUO_IPSW_CACHE."""
    if os.environ.get("SKEUO_IPSW_CACHE"):
        return os.environ["SKEUO_IPSW_CACHE"]
    if sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    elif sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/AppData/Local")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "Skeuo", "ipsw")


def firmware(version):
    if version not in FIRMWARES:
        raise DownloadError("Skeuo supports iPod touch 2G firmware %s, not %s" % (", ".join(FIRMWARES), version))
    return FIRMWARES[version]


def filename(version):
    return "iPod2,1_%s_%s_Restore.ipsw" % (version, FIRMWARES[version]["build"])


def cached(version, cache=None):
    """The path of the cached IPSW, or None."""
    path = os.path.join(cache or default_cache(), filename(version))
    return path if os.path.exists(path) else None


def available(cache=None):
    """Every supported version: whether it is cached and whether Apple serves it."""
    result = []
    for version, fw in FIRMWARES.items():
        path = cached(version, cache)
        part = os.path.join(cache or default_cache(), filename(version) + ".part")
        result.append({
            "product": "iPod2,1",
            "version": version,
            "build": fw["build"],
            "downloadable": bool(fw["url"]),
            "size": fw.get("size"),
            "cached": path,
            "partial": os.path.getsize(part) if os.path.exists(part) else 0,
        })
    return result


def delete(version, cache=None):
    """Removes the cached IPSW of version, and a partial download of it."""
    path = os.path.join(cache or default_cache(), filename(version))
    for name in (path, path + ".part", path + ".part.etag"):
        if os.path.exists(name):
            os.remove(name)


def download(version, cache=None, progress=None, cancel=None):
    """Downloads the IPSW of version into the cache (if it isn't there yet) and returns its path.
    progress(done, total) is called as data arrives; a set cancel event stops the download, keeping what it has."""
    fw = firmware(version)
    cache = cache or default_cache()
    dest = os.path.join(cache, filename(version))
    if os.path.exists(dest):
        return dest
    if not fw["url"]:
        raise DownloadError("Apple never published iPhone OS %s for the iPod touch on a public URL (it was a paid "
                            "upgrade); restore from a local IPSW instead" % version)
    os.makedirs(cache, exist_ok=True)
    part = dest + ".part"
    etag_file = part + ".etag"
    have = os.path.getsize(part) if os.path.exists(part) else 0
    etag = None
    if have and os.path.exists(etag_file):
        with open(etag_file) as f:
            etag = f.read().strip()
    if not etag:
        have = 0
    if have == fw["size"]:  # complete, but not checked yet
        check(part, fw, etag)
        os.replace(part, dest)
        os.remove(etag_file)
        return dest

    request = urllib.request.Request(fw["url"], headers={"User-Agent": "Skeuo"})
    if have:
        request.add_header("Range", "bytes=%d-" % have)
        request.add_header("If-Range", etag)
    try:
        response = urllib.request.urlopen(request, timeout=60)
    except (urllib.error.URLError, OSError) as e:
        raise DownloadError("downloading %s: %s" % (fw["url"], getattr(e, "reason", e)))
    with response:
        server_etag = response.headers.get("ETag", "")
        if response.status == 206:
            if server_etag != etag:
                raise DownloadError("the server's file changed during the download; delete %s and retry" % part)
            mode = "ab"
        else:
            have = 0  # the server sent the whole file (no range support, or the file changed)
            mode = "wb"
            with open(etag_file, "w") as f:
                f.write(server_etag)
        total = have + int(response.headers.get("Content-Length", 0))
        if total != fw["size"]:
            raise DownloadError("the server offers %d bytes for %s, expected %d" % (total, filename(version), fw["size"]))
        done = have
        if progress:
            progress(done, total)
        with open(part, mode) as f:
            while True:
                if cancel is not None and cancel.is_set():
                    raise Cancelled()
                try:
                    chunk = response.read(CHUNK)
                except OSError as e:
                    raise DownloadError("downloading %s: %s (run it again to resume)" % (filename(version), e))
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    if done != total:
        raise DownloadError("the download of %s stopped at %d of %d bytes (run it again to resume)"
                            % (filename(version), done, total))
    check(part, fw, server_etag)
    os.replace(part, dest)
    os.remove(etag_file)
    return dest


def check(path, fw, etag):
    """Checks a downloaded IPSW against the MD5 in Apple's ETag and the known SHA-1; removes it if it doesn't match."""
    md5, sha1 = hashlib.md5(), hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            md5.update(chunk)
            sha1.update(chunk)
    etag = etag.strip('"')
    problems = []
    if len(etag) == 32 and md5.hexdigest() != etag:
        problems.append("its MD5 %s differs from the one Apple's server reports (%s)" % (md5.hexdigest(), etag))
    if sha1.hexdigest() != fw["sha1"]:
        problems.append("its SHA-1 %s differs from the expected %s" % (sha1.hexdigest(), fw["sha1"]))
    if problems:
        os.remove(path)
        raise DownloadError("the downloaded IPSW is damaged: %s; it was removed, download it again"
                            % "; ".join(problems))
