#ifndef NDX_NATIVE_WORDS_H
#define NDX_NATIVE_WORDS_H

#include <stdint.h>

/* Original bounded word-access ABI. Caller owns and retains a live mapping.
 * These functions validate integers, not mapping identity or permissions.
 * No signal recovery, threads, allocation, device access or completion logic.
 */
#define NDX_WORD_OK UINT32_C(0)
#define NDX_WORD_RANGE UINT32_C(1)
#define NDX_WORD_VALUE UINT32_C(2)
#define NDX_WORD_ABI UINT64_C(0x4e44585700000001)
#define NDX_WORD_EXPORT __attribute__((visibility("default")))

NDX_WORD_EXPORT uint64_t ndx_word_abi(void);
/* High 32 bits: status; low 32 bits: value, zero on failure. */
NDX_WORD_EXPORT uint64_t ndx_word_read32(uint64_t base, uint64_t size, uint64_t address);
NDX_WORD_EXPORT uint32_t ndx_word_write32(uint64_t base, uint64_t size,
                                       uint64_t address, uint64_t value);
NDX_WORD_EXPORT void ndx_word_release(void);
NDX_WORD_EXPORT void ndx_word_acquire(void);

#endif
