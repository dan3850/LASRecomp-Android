// Included only by the Mario/Linux kernel translation unit. No game ABI changes.
#include <dlfcn.h>
#include <errno.h>
#include <signal.h>
#include <ucontext.h>
#include <sys/syscall.h>
#include "gamelib.h"
#if __has_include("mario-capture-build.h")
#include "mario-capture-build.h"
#endif

_Static_assert(ATOMIC_POINTER_LOCK_FREE == 2 && ATOMIC_LLONG_LOCK_FREE == 2 &&
               ATOMIC_LONG_LOCK_FREE == 2 && ATOMIC_INT_LOCK_FREE == 2,
               "thread capture requires signal-safe lock-free atomics");
#ifndef LASRECOMP_MARIO_SOURCE_COMMIT
#define LASRECOMP_MARIO_SOURCE_COMMIT "unknown"
#endif

static _Atomic uint64_t capture_serial;
static _Atomic(KThread *) capture_targets[256];
static _Atomic unsigned capture_target_count;

static void mario_capture_signal(int signal_number, siginfo_t *info, void *context) {
    (void)signal_number; (void)info;
    int saved_errno=errno;
    // Do not invoke the engine's dynamic TLS resolver from a signal handler.
    // The collector pins this immutable target list until kernel teardown can
    // proceed. gettid is a direct Linux syscall; all shared slots are lock-free.
    uint64_t tid=(uint64_t)syscall(SYS_gettid);
    KThread *t=NULL;
    unsigned count=atomic_load_explicit(&capture_target_count,memory_order_acquire);
    for (unsigned i=0;i<count;i++) {
        KThread *candidate=atomic_load_explicit(&capture_targets[i],memory_order_relaxed);
        if (candidate->capture_tid==tid) { t=candidate; break; }
    }
    if (t) {
        uint64_t request=atomic_load_explicit(&t->capture_request,memory_order_relaxed);
        if (request && request!=atomic_load_explicit(&t->capture_ack,memory_order_relaxed)) {
            uint64_t pc=0,lr=0;
            ucontext_t *u=context;
#if defined(__aarch64__)
            pc=u->uc_mcontext.pc; lr=u->uc_mcontext.regs[30];
#elif defined(__x86_64__) && defined(REG_RIP)
            pc=u->uc_mcontext.gregs[REG_RIP];
#else
            (void)u;
#endif
            // Read the interrupted thread's own allocated Cpu, never another
            // running thread's Cpu from the collector. pc is a dispatch target,
            // NOT an exact guest instruction PC. Native PC above is exact.
            atomic_store_explicit(&t->capture_pc,t->cpu.pc,memory_order_relaxed);
            atomic_store_explicit(&t->capture_lr,t->cpu.x[30],memory_order_relaxed);
            atomic_store_explicit(&t->capture_sp,t->cpu.sp,memory_order_relaxed);
            atomic_store_explicit(&t->capture_native_pc,pc,memory_order_relaxed);
            atomic_store_explicit(&t->capture_native_lr,lr,memory_order_relaxed);
            atomic_store_explicit(&t->capture_svc_sample,t->capture_svc,memory_order_relaxed);
            atomic_store_explicit(&t->capture_in_svc_sample,t->capture_in_svc,memory_order_relaxed);
            atomic_store_explicit(&t->capture_svc_sample_pc,t->capture_svc_pc,memory_order_relaxed);
            for (int i=0;i<4;i++)
                atomic_store_explicit(&t->capture_args[i],t->capture_svc_args[i],memory_order_relaxed);
            atomic_store_explicit(&t->capture_ack,request,memory_order_release);
        }
    }
    errno=saved_errno;
}

static bool capture_read_word(uint64_t address,uint32_t *word) {
    // Caller holds g_klock. Read only an aligned word in a readable kernel
    // region, never an arbitrary guest pointer or an unregistered address.
    if (address&3) return false;
    // Region updates also occur in SVCs that do not hold g_klock. Do not wait
    // for that bookkeeping here or scan a table while it is being modified.
    if (pthread_mutex_trylock(&mario_region_lock)!=0) return false;
    bool found=false;
    for (int i=0;i<nregions;i++) {
        Region *r=&regions[i];
        if ((r->perm&1) && address>=r->addr && address-r->addr<r->size &&
            r->size-(address-r->addr)>=sizeof *word) {
            *word=__atomic_load_n((uint32_t *)(uintptr_t)address,__ATOMIC_RELAXED);
            found=true; break;
        }
    }
    pthread_mutex_unlock(&mario_region_lock);
    return found;
}

static const char *capture_wait_name(WaitKind kind) {
    switch (kind) {
    case WAIT_NONE: return "none";
    case WAIT_MUTEX: return "mutex";
    case WAIT_CONDVAR: return "condvar";
    case WAIT_ARBITER: return "arbiter";
    default: return "unknown";
    }
}

static void capture_native_symbol(FILE *out,const char *label,uint64_t address) {
    Dl_info info;
    if (address && dladdr((void *)(uintptr_t)address,&info) && info.dli_fbase) {
        const char *name=info.dli_fname?strrchr(info.dli_fname,'/'):NULL;
        name=name?name+1:(info.dli_fname?info.dli_fname:"?");
        fprintf(out," %s_module=%s %s_offset=%llx",label,name,label,
                (unsigned long long)(address-(uintptr_t)info.dli_fbase));
        if (info.dli_sname) fprintf(out," %s_symbol=%s",label,info.dli_sname);
    }
}

static void capture_thread_row(FILE *out,KThread *t,uint64_t request,int sent) {
    bool acknowledged=atomic_load_explicit(&t->capture_ack,memory_order_acquire)==request;
    uint64_t pc=0,lr=0;
    fprintf(out,"thread=%llu handle=%x entry=%llx signal_result=%d sampled=%d",
            (unsigned long long)t->id,t->handle,(unsigned long long)t->entry,sent,acknowledged);
    if (acknowledged) {
        pc=atomic_load(&t->capture_native_pc); lr=atomic_load(&t->capture_native_lr);
        fprintf(out," guest_dispatch_pc=%llx guest_lr=%llx guest_sp=%llx native_pc=%llx native_lr=%llx"
                " in_svc=%u svc=%x svc_pc=%llx args=%llx,%llx,%llx,%llx",
                (unsigned long long)atomic_load(&t->capture_pc),
                (unsigned long long)atomic_load(&t->capture_lr),
                (unsigned long long)atomic_load(&t->capture_sp),
                (unsigned long long)pc,(unsigned long long)lr,
                atomic_load(&t->capture_in_svc_sample),atomic_load(&t->capture_svc_sample),
                (unsigned long long)atomic_load(&t->capture_svc_sample_pc),
                (unsigned long long)atomic_load(&t->capture_args[0]),
                (unsigned long long)atomic_load(&t->capture_args[1]),
                (unsigned long long)atomic_load(&t->capture_args[2]),
                (unsigned long long)atomic_load(&t->capture_args[3]));
    }
    // Do not block or do file I/O while holding the kernel lock.
    char state[4096]; size_t used=0;
#define CAPTURE_STATE(...) do { \
    int n=snprintf(state+used,sizeof state-used,__VA_ARGS__); \
    if (n>0) used+=(size_t)n<sizeof state-used?(size_t)n:sizeof state-used-1; \
} while (0)
    if (pthread_mutex_trylock(&g_klock)==0) {
        CAPTURE_STATE(" main=%d ready=%d finished=%d wait=%s sync_wait=%d wait_addr=%llx mutex=%llx tag=%x",
                      t->is_main,t->capture_ready,t->finished,capture_wait_name(t->wait_kind),t->in_sync_wait,
                      (unsigned long long)t->wait_addr,(unsigned long long)t->wait_mutex,t->wait_tag);
        uint64_t word_address=t->wait_kind==WAIT_CONDVAR?t->wait_mutex:t->wait_addr;
        uint32_t word;
        if (t->wait_kind!=WAIT_NONE && capture_read_word(word_address,&word)) {
            CAPTURE_STATE(" wait_word=%08x",word);
            if (t->wait_kind==WAIT_MUTEX || t->wait_kind==WAIT_CONDVAR) {
                uint32_t owner=word&~WAITERS_BIT;
                KObject *object=owner>=0x101 && owner<0x100+MAX_HANDLES?handle_get(owner):NULL;
                CAPTURE_STATE(" owner_handle=%x owner_thread=%llu",owner,
                              (unsigned long long)(object && object->type==KOBJ_THREAD?((KThread *)object)->id:0));
            }
        }
        if (acknowledged && t->in_sync_wait && atomic_load(&t->capture_svc_sample)==0x18) {
            uint64_t address=atomic_load(&t->capture_args[1]),count=atomic_load(&t->capture_args[2]);
            for (uint64_t i=0;i<count && i<64;i++) {
                uint32_t handle;
                if (address>UINT64_MAX-4*i || !capture_read_word(address+4*i,&handle)) break;
                KObject *object=handle>=0x101 && handle<0x100+MAX_HANDLES?handle_get(handle):NULL;
                CAPTURE_STATE(" sync%llu=%x:type%d:signaled%d",(unsigned long long)i,handle,
                              object?(int)object->type:0,object?object->signaled:0);
            }
        }
        pthread_mutex_unlock(&g_klock);
    } else CAPTURE_STATE(" kernel_state=lock_busy");
#undef CAPTURE_STATE
    fputs(state,out);
    capture_native_symbol(out,"pc",pc); capture_native_symbol(out,"lr",lr);
    fputc('\n',out);
}

static bool capture_sample(FILE *out,int sample) {
    KThread *threads[256]; bool signal_thread[256]; int sent[256]; size_t count=0;
    uint64_t until=plat_now_ns()+100000000ull;
    while (pthread_mutex_trylock(&g_klock)!=0) {
        if (plat_now_ns()>=until) { fputs("kernel_list=lock_busy\n",out); return false; }
        struct timespec pause={0,1000000}; nanosleep(&pause,NULL);
    }
    if (g_rt_unwind) { pthread_mutex_unlock(&g_klock); fputs("capture=runtime_stopping\n",out); return false; }
    KThread *t=g_threads;
    for (;t && count<256;t=t->anext) {
        threads[count]=t; signal_thread[count]=t->capture_ready && !t->finished; count++;
    }
    bool truncated=t!=NULL;
    pthread_mutex_unlock(&g_klock);
    uint64_t request=atomic_fetch_add(&capture_serial,1)+1;
    unsigned active=0;
    for (size_t i=0;i<count;i++)
        if (signal_thread[i]) atomic_store_explicit(&capture_targets[active++],threads[i],memory_order_relaxed);
    atomic_store_explicit(&capture_target_count,active,memory_order_release);
    fprintf(out,"sample=%d monotonic_ns=%llu threads=%zu truncated=%d\n",sample,
            (unsigned long long)plat_now_ns(),count,truncated);
    for (size_t i=0;i<count;i++) {
        sent[i]=-1;
        if (signal_thread[i]) {
            atomic_store(&threads[i]->capture_request,request);
            sent[i]=pthread_kill(threads[i]->capture_host,SIGURG);
        }
    }
    until=plat_now_ns()+100000000ull;
    for (;;) {
        bool pending=false;
        for (size_t i=0;i<count;i++)
            if (sent[i]==0 && atomic_load_explicit(&threads[i]->capture_ack,memory_order_acquire)!=request) pending=true;
        if (!pending || plat_now_ns()>=until) break;
        struct timespec pause={0,1000000}; nanosleep(&pause,NULL);
    }
    for (size_t i=0;i<count;i++) capture_thread_row(out,threads[i],request,sent[i]);
    return true;
}

__attribute__((visibility("default"))) int lasrecomp_mario_thread_capture(void) {
    if (pthread_mutex_trylock(&mario_capture_lock)!=0) return 0;
    int result=0; struct sigaction previous,action={0}; bool installed=false;
    FILE *out=NULL;
    if (sigaction(SIGURG,NULL,&previous)!=0 ||
        (previous.sa_handler!=SIG_DFL && previous.sa_handler!=SIG_IGN)) goto done;
    action.sa_sigaction=mario_capture_signal; action.sa_flags=SA_SIGINFO|SA_RESTART;
    sigemptyset(&action.sa_mask);
    if (sigaction(SIGURG,&action,NULL)!=0) goto done;
    installed=true;
    out=fopen("mario-threads.log.partial","w");
    if (!out) goto done;
    fprintf(out,"mario-thread-capture schema=1 source_commit=%s library_id=%s\n"
            "guest_dispatch_pc is saved Cpu.pc, not an exact guest instruction; native_pc is interrupted PC.\n"
            "Kernel wait metadata is sampled separately under its lock; sampled=0 means no register response.\n",
            LASRECOMP_MARIO_SOURCE_COMMIT,GAMELIB_ID);
    bool first=capture_sample(out,1);
    struct timespec gap={0,100000000}; nanosleep(&gap,NULL); // collector only, not a guest delay
    bool second=capture_sample(out,2);
    fprintf(out,"complete=1 samples_available=%d\n",first+second);
    result=!ferror(out);
    if (fclose(out)!=0) result=0;
    out=NULL;
    if (result && rename("mario-threads.log.partial","mario-threads.log")!=0) result=0;
done:
    if (out) fclose(out);
    atomic_store_explicit(&capture_target_count,0,memory_order_release);
    if (installed) sigaction(SIGURG,&previous,NULL);
    pthread_mutex_unlock(&mario_capture_lock);
    return result;
}
