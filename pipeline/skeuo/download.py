"""
Downloads restore IPSWs from Apple's servers into a cache directory. Which firmware a device has, and where Apple
serves it, is in the device's profile (devices/).

Apple's version catalog (itunes.apple.com/...MZITunesClientCheck/version) only publishes a FirmwareSHA1 for the
firmware it currently offers. What Apple's download server does publish for every file is its size and an ETag that
is the file's MD5. A download is checked against both, as the server reports them, and against the SHA-1 in the
profile, which comes from the IPSWs as archived elsewhere. Some firmware was a paid upgrade, sold through the iTunes
Store, and never on a public URL; its profile entry has no URL, and a device with it needs a local IPSW.

Downloads resume: the data goes to <name>.part, and a later download continues it with a Range request, as long as
the server's ETag is still the one it started with (kept in <name>.part.etag).
"""
import hashlib
import os
import sys
import urllib.error
import urllib.request

from . import devices

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


def firmware(profile, version):
    if version not in profile.firmwares:
        raise DownloadError("Skeuo supports %s firmware %s, not %s"
                            % (profile.name, ", ".join(profile.firmwares), version))
    return profile.firmwares[version]


def filename(profile, version):
    return "%s_%s_%s_Restore.ipsw" % (profile.product, version, profile.firmwares[version]["build"])


def cached(profile, version, cache=None):
    """The path of the cached IPSW, or None."""
    path = os.path.join(cache or default_cache(), filename(profile, version))
    return path if os.path.exists(path) else None


def available(cache=None):
    """Every supported version of every device: whether it is cached and whether Apple serves it."""
    result = []
    for profile in devices.profiles():
        for version, fw in profile.firmwares.items():
            path = cached(profile, version, cache)
            part = os.path.join(cache or default_cache(), filename(profile, version) + ".part")
            result.append({
                "product": profile.product,
                "version": version,
                "build": fw["build"],
                "downloadable": bool(fw["url"]),
                "size": fw.get("size"),
                "cached": path,
                "partial": os.path.getsize(part) if os.path.exists(part) else 0,
            })
    return result


def delete(profile, version, cache=None):
    """Removes the cached IPSW of version, and a partial download of it."""
    path = os.path.join(cache or default_cache(), filename(profile, version))
    for name in (path, path + ".part", path + ".part.etag"):
        if os.path.exists(name):
            os.remove(name)


def download(profile, version, cache=None, progress=None, cancel=None):
    """Downloads the IPSW of version into the cache (if it isn't there yet) and returns its path.
    progress(done, total) is called as data arrives; a set cancel event stops the download, keeping what it has."""
    fw = firmware(profile, version)
    cache = cache or default_cache()
    dest = os.path.join(cache, filename(profile, version))
    if os.path.exists(dest):
        return dest
    if not fw["url"]:
        raise DownloadError("Apple never published %s for the %s on a public URL (it was a paid upgrade); restore "
                            "from a local IPSW instead" % (os_name(version), profile.name))
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
            raise DownloadError("the server offers %d bytes for %s, expected %d"
                                % (total, filename(profile, version), fw["size"]))
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
                    raise DownloadError("downloading %s: %s (run it again to resume)" % (filename(profile, version), e))
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    if done != total:
        raise DownloadError("the download of %s stopped at %d of %d bytes (run it again to resume)"
                            % (filename(profile, version), done, total))
    check(part, fw, server_etag)
    os.replace(part, dest)
    os.remove(etag_file)
    return dest


def os_name(version):
    return "%s %s" % ("iOS" if int(version.split(".")[0]) >= 4 else "iPhone OS", version)


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
