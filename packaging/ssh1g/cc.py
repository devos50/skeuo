#!/usr/bin/env python3
import os,sys,subprocess
from pathlib import Path
p=Path(__file__).resolve().parent
args=sys.argv[1:]
cc=['/usr/bin/xcrun','clang','-target','armv6-apple-ios1.0','-isysroot',os.environ['SKEUO_SSH_SDK'],'-marm','-ffixed-r9','-D__DARWIN_64_BIT_INO_T=0','-D__DARWIN_UNIX03=0','-D__DARWIN_VERS_1050=0','-Wno-incompatible-sysroot','-Wno-deprecated-declarations']
if not any(x in args for x in ['-c','-E','-S','--version','-v']):
 cc+=['-nostdlib','-fuse-ld='+os.environ['SKEUO_SSH_LD'],'-Wl,-e,start,-no_pie,-no_function_starts',str(p/'crt.o'),str(p/'compat.o'),str(p/'sysroot/usr/lib/libSystem.B.dylib'),str(p/'sysroot/usr/lib/libgcc_s.1.dylib')]
 args=[x for x in args if x not in ['-lutil','-lcrypt']]
sys.exit(subprocess.call(cc+args))
