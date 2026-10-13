"""
Reads the files a restore needs from an IPSW, given as the .ipsw file itself (a zip archive) or as an extracted
directory. Files are extracted on demand into a work directory, so the 200+ MB root filesystem is only copied once.
"""
import os
import plistlib
import shutil
import zipfile

SUPPORTED_PRODUCTS = {"iPod2,1"}
# The firmware the emulator has GID keys for, by build, with the security epoch of its NAND driver. The NAND signature
# carries that epoch, and iBoot only boots from a NAND formatted for its own epoch.
NAND_EPOCHS = {
    "5F138": 1,  # iPhone OS 2.1.1
    "5G77a": 2,  # iPhone OS 2.2
    "7A341": 3,  # iPhone OS 3.0
    "8A293": 4,  # iOS 4.0
}


class IPSWError(Exception):
    pass


class IPSW:
    def __init__(self, path, workdir, nor_images=None):
        """nor_images: a directory with the NOR images (llb.img3, iboot.img3, dtree.img3, ...) for IPSW extractions
        that lack Firmware/all_flash."""
        self.path = path
        self.workdir = workdir
        self.nor_images_dir = nor_images
        self.zip = None
        if os.path.isfile(path):
            try:
                self.zip = zipfile.ZipFile(path)
            except zipfile.BadZipFile:
                raise IPSWError("%s is not an IPSW (not a zip archive)" % path)
            self.names = set(self.zip.namelist())
        elif not os.path.isdir(path):
            raise IPSWError("%s does not exist" % path)

        try:
            self.plist = plistlib.loads(self.read("Restore.plist"))
        except FileNotFoundError:
            raise IPSWError("%s has no Restore.plist" % path)
        self.product = self.plist["ProductType"]
        self.version = self.plist["ProductVersion"]
        self.build = self.plist["ProductBuildVersion"]
        if self.product not in SUPPORTED_PRODUCTS:
            raise IPSWError("%s is firmware for %s; supported: %s"
                            % (path, self.product, ", ".join(sorted(SUPPORTED_PRODUCTS))))
        self.board = self.plist["DeviceMap"][0]["BoardConfig"]
        if self.build not in NAND_EPOCHS:
            raise IPSWError("%s is %s %s (%s); supported builds: %s"
                            % (path, self.product, self.version, self.build, ", ".join(sorted(NAND_EPOCHS))))

    def __str__(self):
        return "%s %s (%s)" % (self.product, self.version, self.build)

    def exists(self, name):
        if self.zip:
            return name in self.names
        return os.path.exists(os.path.join(self.path, name))

    def read(self, name):
        if self.zip:
            if name not in self.names:
                raise FileNotFoundError(name)
            return self.zip.read(name)
        with open(os.path.join(self.path, name), "rb") as f:
            return f.read()

    def file(self, name):
        """Returns a path to the file on disk, extracting it from the archive if needed."""
        if not self.zip:
            path = os.path.join(self.path, name)
            if not os.path.exists(path):
                raise FileNotFoundError(name)
            return path
        dest = os.path.join(self.workdir, "ipsw", name)
        if not os.path.exists(dest):
            if name not in self.names:
                raise FileNotFoundError(name)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with self.zip.open(name) as src, open(dest + ".part", "wb") as dst:
                shutil.copyfileobj(src, dst, 1 << 20)
            os.rename(dest + ".part", dest)
        return dest

    def dfu_image(self, kind):
        """iBSS or iBEC."""
        return self.read("Firmware/dfu/%s.%s.RELEASE.dfu" % (kind, self.board))

    def restore_ramdisk(self, update=False):
        return self.read(self.plist["RestoreRamDisks"]["Update" if update else "User"])

    def kernelcache(self):
        """The kernelcache that boots the restore ramdisk. 4.0's Restore.plist names a kernelcache.release.s5l8720x
        that the IPSW doesn't ship; the system one (kernelcache.release.n72) boots the ramdisk too."""
        name = self.plist["RestoreKernelCaches"]["Release"]
        if not self.exists(name):
            name = self._system_kernelcache_name() or name
        return self.read(name)

    def system_kernelcache(self):
        """The kernelcache that boots the restored system. From 3.0 on it lives on the root filesystem, and restored
        asks for it during the restore."""
        name = self._system_kernelcache_name()
        return self.read(name) if name else self.kernelcache()

    def _system_kernelcache_name(self):
        # 3.x lists it by platform (s5l8720x), 4.x by target (the board without "ap": n72)
        for key in ("KernelCachesByPlatform", "KernelCachesByTarget"):
            caches = self.plist.get(key, {})
            if len(caches) == 1:
                return next(iter(caches.values()))["Release"]
        return None

    def system_image(self):
        return self.file(self.plist["SystemRestoreImages"]["User"])

    def device_tree(self):
        """The device tree image from all_flash, which iBEC needs to boot the restore ramdisk."""
        llb, images = self.nor_images()
        for path in images:
            name = os.path.basename(path).lower()
            if name.startswith("devicetree") or name.startswith("dtree"):
                with open(path, "rb") as f:
                    return f.read()
        raise IPSWError("%s has no device tree" % self.path)

    def nor_images(self):
        """Returns (LLB, [other images]) as paths, in the order of the all_flash manifest."""
        flash = "Firmware/all_flash/all_flash.%s.production/" % self.board
        try:
            names = [line.strip() for line in self.read(flash + "manifest").decode().splitlines() if line.strip()]
        except FileNotFoundError:
            raise IPSWError("%s has no all_flash manifest" % self.path)
        paths = []
        for name in names:
            if self.exists(flash + name):
                paths.append(self.file(flash + name))
                continue
            # extractions without the all_flash images: take them from nor_images, named like generate_nor does
            short = name.split(".")[0].lower().replace("devicetree", "dtree") + ".img3"
            path = os.path.join(self.nor_images_dir, short) if self.nor_images_dir else None
            if not path or not os.path.exists(path):
                raise IPSWError("NOR image %s is missing from %s" % (name, self.path))
            paths.append(path)
        return paths[0], paths[1:]
