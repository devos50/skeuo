/* Minimal ARMv6 process entry and the classic dyld lazy-binding ABI. */
.syntax unified
.arm
.text
.globl start
.p2align 2
start:
    ldr r0, [sp]
    add r1, sp, #4
    add r2, r1, r0, lsl #2
    add r2, r2, #4
    ldr r3, =_NXArgc
    str r0, [r3]
    ldr r3, =_NXArgv
    str r1, [r3]
    ldr r3, =_environ
    str r2, [r3]
    ldr r3, [r1]
    ldr ip, =___progname
    str r3, [ip]
    bic sp, sp, #7
    bl _skeuo_init
    ldr r0, =_NXArgc
    ldr r0, [r0]
    ldr r1, =_NXArgv
    ldr r1, [r1]
    ldr r2, =_environ
    ldr r2, [r2]
    bl _main
    bl _exit
    b .
.globl dyld_stub_binding_helper
dyld_stub_binding_helper:
    /* The stub supplies its lazy-pointer address in ip. dyld consumes a
       stack pair (image header, lazy pointer) and preserves call arguments. */
    sub sp, sp, #8
    str ip, [sp, #4]
    ldr ip, =__mh_execute_header
    str ip, [sp]
    ldr ip, =dyld_entry
    ldr ip, [ip]
    bx ip
.globl __dyld_func_lookup
__dyld_func_lookup:
    ldr ip, =dyld_entry
    ldr ip, [ip, #4]
    bx ip
.data
.globl _NXArgc, _NXArgv, _environ, ___progname
_NXArgc: .long 0
_NXArgv: .long 0
_environ: .long 0
___progname: .long 0
.section __DATA,__dyld
.p2align 2
dyld_entry: .long 0
.long 0
