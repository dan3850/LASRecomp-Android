// Real pthread/signal/kernel capture with synthetic callers only.
#define _GNU_SOURCE
#include <assert.h>
#include <errno.h>
#include "kernel.c"
#include "../android/game/mario_capture_bridge.h"

uint64_t plat_now_ns(void) {
    struct timespec now; assert(clock_gettime(CLOCK_MONOTONIC,&now)==0);
    return (uint64_t)now.tv_sec*1000000000ull+now.tv_nsec;
}
uint32_t vi_vsync_handle(void) { return 0; } // optional environment-controlled backtrace hook

static KThread worker,owner;
static uint32_t mutex_word,key_word,sync_handle=0x121;
static KEvent event={.type=KOBJ_EVENT};
static _Atomic bool stop,returned;
static _Atomic uint64_t iterations;
static const char *mode;
static uint32_t wait_result;

static void register_worker(void) {
    t_cur=&worker;
    worker.cpu.pc=MAIN_BASE+0x40; worker.cpu.x[30]=SDK_BASE+0x80;
    worker.cpu.sp=STACK_BASE+0x10000;
    pthread_mutex_lock(&g_klock);
    worker.capture_host=pthread_self(); worker.capture_ready=true;
    worker.capture_tid=(uint64_t)syscall(SYS_gettid);
    pthread_mutex_unlock(&g_klock);
}
static void *run_worker(void *unused) {
    (void)unused;
    if (!strcmp(mode,"unanswered")) {
        sigset_t blocked; sigemptyset(&blocked); sigaddset(&blocked,SIGURG);
        assert(pthread_sigmask(SIG_BLOCK,&blocked,NULL)==0);
    }
    register_worker();
    if (!strcmp(mode,"condvar")) {
        worker.capture_svc=0x1c; worker.capture_svc_pc=SDK_BASE+0x90;
        worker.capture_svc_args[0]=(uintptr_t)&mutex_word;
        worker.capture_svc_args[1]=(uintptr_t)&key_word;
        worker.capture_svc_args[2]=worker.handle; worker.capture_svc_args[3]=UINT64_MAX;
        worker.capture_in_svc=true;
        mutex_word=worker.handle;
        wait_result=svc_wait_process_wide_key((uintptr_t)&mutex_word,(uintptr_t)&key_word,worker.handle,-1);
        assert(wait_result==R_OK && mutex_word==worker.handle);
    } else if (!strcmp(mode,"sync")) {
        worker.capture_svc=0x18; worker.capture_svc_pc=SDK_BASE+0xa0;
        worker.capture_svc_args[1]=(uintptr_t)&sync_handle; worker.capture_svc_args[2]=1;
        worker.capture_in_svc=true;
        int32_t index=-1;
        wait_result=svc_wait_synchronization((uintptr_t)&sync_handle,1,-1,&index);
        assert(wait_result==R_OK && index==0);
    } else {
        while (!atomic_load(&stop)) atomic_fetch_add(&iterations,1);
    }
    atomic_store(&returned,true);
    pthread_mutex_lock(&g_klock); worker.finished=true; pthread_mutex_unlock(&g_klock);
    t_cur=NULL;
    return NULL;
}
static void unrelated_signal(int number) { (void)number; }
static _Atomic bool bridge_entered,bridge_release,bridge_cleared;
static int bridge_callback(void) {
    atomic_store(&bridge_entered,true);
    while (!atomic_load(&bridge_release)) usleep(1000);
    return 41;
}
static void *bridge_run(void *unused) {
    (void)unused; assert(mario_capture_bridge_run()==41); return NULL;
}
static void *bridge_clear(void *unused) {
    (void)unused; mario_capture_bridge_set(NULL); atomic_store(&bridge_cleared,true); return NULL;
}

int main(int argc,char **argv) {
    assert(argc==2); mode=argv[1];
    if (!strcmp(mode,"bridge")) {
        assert(mario_capture_bridge_run()==0);
        mario_capture_bridge_set(bridge_callback); atomic_store(&bridge_release,true);
        assert(mario_capture_bridge_run()==41);
        mario_capture_bridge_set(NULL); assert(mario_capture_bridge_run()==0);
        return 0;
    }
    if (!strcmp(mode,"bridge-lifetime")) {
        mario_capture_bridge_set(bridge_callback);
        pthread_t caller,closer;
        assert(pthread_create(&caller,NULL,bridge_run,NULL)==0);
        while (!atomic_load(&bridge_entered)) usleep(1000);
        assert(pthread_mutex_trylock(&mario_capture_bridge_lock)==EBUSY);
        assert(pthread_create(&closer,NULL,bridge_clear,NULL)==0);
        assert(!atomic_load(&bridge_cleared));
        atomic_store(&bridge_release,true);
        assert(pthread_join(caller,NULL)==0 && pthread_join(closer,NULL)==0);
        assert(atomic_load(&bridge_cleared) && mario_capture_bridge_run()==0);
        return 0;
    }
    if (!strcmp(mode,"handler")) {
        struct sigaction action={0},current;
        action.sa_handler=unrelated_signal; sigemptyset(&action.sa_mask);
        assert(sigaction(SIGURG,&action,NULL)==0);
        assert(lasrecomp_mario_thread_capture()==0);
        assert(sigaction(SIGURG,NULL,&current)==0 && current.sa_handler==unrelated_signal);
        return 0;
    }
    if (!strcmp(mode,"busy")) {
        pthread_mutex_lock(&mario_capture_lock);
        assert(lasrecomp_mario_thread_capture()==0);
        pthread_mutex_unlock(&mario_capture_lock);
        return 0;
    }
    if (!strcmp(mode,"lock")) {
        pthread_mutex_lock(&g_klock);
        assert(lasrecomp_mario_thread_capture()==1);
        pthread_mutex_unlock(&g_klock);
        return 0;
    }
    if (!strcmp(mode,"reader")) {
        uint32_t word=123,result=0;
        regions[0]=(Region){(uintptr_t)&word,sizeof word,4,1}; nregions=1;
        assert(capture_read_word((uintptr_t)&word,&result) && result==123);
        assert(!capture_read_word((uintptr_t)&word+1,&result));
        assert(!capture_read_word(0xdead0000,&result));
        regions[0].perm=0; assert(!capture_read_word((uintptr_t)&word,&result));
        regions[0].perm=1;
        pthread_mutex_lock(&mario_region_lock);
        assert(!capture_read_word((uintptr_t)&word,&result));
        pthread_mutex_unlock(&mario_region_lock);
        return 0;
    }
    worker.id=80; worker.handle=0x116; worker.prio=44; worker.obj.type=KOBJ_THREAD;
    owner.id=81; owner.handle=0x120; owner.obj.type=KOBJ_THREAD;
    handles[worker.handle-0x100]=&worker.obj;
    handles[owner.handle-0x100]=&owner.obj;
    handles[sync_handle-0x100]=&event;
    owner.anext=&worker; g_threads=&owner;
    assert(pthread_cond_init(&worker.cond,NULL)==0);
    regions[0]=(Region){(uintptr_t)&mutex_word,sizeof mutex_word,4,3};
    regions[1]=(Region){(uintptr_t)&sync_handle,sizeof sync_handle,4,1}; nregions=2;
    pthread_t host; assert(pthread_create(&host,NULL,run_worker,NULL)==0);
    for (int i=0;;i++) {
        assert(i<2000);
        pthread_mutex_lock(&g_klock);
        bool ready=worker.capture_ready;
        if (!strcmp(mode,"condvar")) ready=ready && worker.wait_kind==WAIT_CONDVAR;
        if (!strcmp(mode,"sync")) ready=ready && worker.in_sync_wait;
        pthread_mutex_unlock(&g_klock);
        if (ready) break;
        usleep(1000);
    }
    if (!strcmp(mode,"condvar")) assert(mutex_acquire_or_mark((uintptr_t)&mutex_word,owner.handle));
    uint64_t before=atomic_load(&iterations);
    assert(lasrecomp_mario_thread_capture()==1);
    assert(!atomic_load(&returned)); // capture never completes a guest wait
    if (!strcmp(mode,"condvar")) {
        assert((mutex_word&~WAITERS_BIT)==owner.handle);
        svc_signal_process_wide_key((uintptr_t)&key_word,1);
        svc_arbitrate_unlock((uintptr_t)&mutex_word);
    } else if (!strcmp(mode,"sync")) {
        assert(!event.signaled);
        pthread_mutex_lock(&g_klock); kernel_signal(&event); pthread_mutex_unlock(&g_klock);
    } else {
        assert(atomic_load(&iterations)>before); // native loop keeps running between samples
        atomic_store(&stop,true);
    }
    assert(pthread_join(host,NULL)==0);
    struct sigaction restored;
    assert(sigaction(SIGURG,NULL,&restored)==0 && restored.sa_handler==SIG_DFL);
    pthread_cond_destroy(&worker.cond);
    return 0;
}
