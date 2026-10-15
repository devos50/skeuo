"""dis.py <bin> <base hex> <start hex> <end hex> [arm]: disassembles part of a raw binary loaded at base."""
import os, subprocess, sys, tempfile
b, base, start, end = sys.argv[1], int(sys.argv[2], 16), int(sys.argv[3], 16), int(sys.argv[4], 16)
arm = len(sys.argv) > 5 and sys.argv[5] == "arm"
d = open(b, "rb").read()[start - base:end - base]
with tempfile.TemporaryDirectory() as t:
    src, obj = os.path.join(t, "x.s"), os.path.join(t, "x.o")
    open(src, "w").write(".text\n.%s\n.byte %s\n" % ("arm" if arm else "thumb", ",".join(str(x) for x in d)))
    subprocess.run(["xcrun", "clang", "-c", "-target", "armv6-apple-ios", "-x", "assembler", src, "-o", obj],
                   check=True, stderr=subprocess.DEVNULL)
    out = subprocess.run(["xcrun", "llvm-objdump", "-d", "--triple=" + ("armv6" if arm else "thumbv6"),
                          "--no-show-raw-insn", obj], capture_output=True, text=True).stdout
for line in out.splitlines():
    p = line.strip().split(":", 1)
    if len(p) == 2 and p[0] and all(c in "0123456789abcdef" for c in p[0]):
        print("%08x: %s" % (start + int(p[0], 16), p[1].strip()))
