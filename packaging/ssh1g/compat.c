#include <stddef.h>
/* stpncpy was added after iPhone OS 1; Dash uses it for job status text. */
char *stpncpy(char *dst, const char *src, size_t count) {
    char *end = dst;
    while (count && *src) { *dst++ = *src++; --count; }
    end = dst;
    while (count--) *dst++ = 0;
    return end;
}
/* Keep modern SDK FD_SET's bounds check on the legacy 1024-bit fd_set. */
int __darwin_check_fd_set_overflow(int fd, const void *set, int unlimited) {
    (void)set; (void)unlimited;
    return fd >= 0 && fd < 1024;
}
/* libSystem 94 leaves Mach/thread and module initialization to crt1. */
extern void (*mach_init_routine)(void);
extern void (*_cthread_init_routine)(void);
extern int _dyld_func_lookup(const char *, void **);
void skeuo_init(void) {
    void (*initialize)(void) = 0;
    if (mach_init_routine) mach_init_routine();
    if (_cthread_init_routine) _cthread_init_routine();
    if (_dyld_func_lookup("__dyld_make_delayed_module_initializer_calls", (void **)&initialize)
        && initialize) initialize();
}
