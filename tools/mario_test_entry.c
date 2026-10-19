// Private full-generator experiment. This is deliberately a different entry
// from lasgame_tables: the Zelda APK must not load a Mario module as Zelda.
#include "gamelib.h"

extern const uint64_t main_fn_addrs[], sdk_fn_addrs[], main_fn_count, sdk_fn_count;
extern const GuestFn main_fn_ptrs[], sdk_fn_ptrs[];

GAMELIB_EXPORT const GameLibTables *mario_test_tables(void) {
    static const GameLibTables tables = {
        GAMELIB_ABI, GAMELIB_ID, main_fn_addrs, sdk_fn_addrs,
        main_fn_ptrs, sdk_fn_ptrs, &main_fn_count, &sdk_fn_count
    };
    return &tables;
}
