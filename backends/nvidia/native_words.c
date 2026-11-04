/* Original implementation from the local ABI/contract and ISA semantics.
 * No NVIDIA/tinygrad/helper implementation is included or adapted.
 */
#include "native_words.h"
#include <limits.h>

#if !defined(__linux__) || !defined(__x86_64__) || !defined(__GNUC__) || !defined(__SSE2__)
#error "native_words requires Linux x86_64 GNU C with SSE2"
#endif
#if __BYTE_ORDER__ != __ORDER_LITTLE_ENDIAN__
#error "native_words requires little endian"
#endif
_Static_assert(CHAR_BIT == 8, "byte width");
_Static_assert(sizeof(uint32_t) == 4, "word width");
_Static_assert(sizeof(uintptr_t) == 8, "pointer width");
_Static_assert(_Alignof(uint32_t) == 4, "word alignment");

static int word_range(uint64_t base, uint64_t size, uint64_t address)
{
    if (base == 0 || size < 4 || size > UINT64_MAX - base)
        return 0;
    if (address == 0 || (address & UINT64_C(3)) != 0 || address < base)
        return 0;
    return address - base <= size - 4;
}

uint64_t ndx_word_abi(void)
{
    return NDX_WORD_ABI;
}

uint64_t ndx_word_read32(uint64_t base, uint64_t size, uint64_t address)
{
    if (!word_range(base, size, address))
        return (uint64_t)NDX_WORD_RANGE << 32;
    return *(const volatile uint32_t *)(uintptr_t)address;
}

uint32_t ndx_word_write32(uint64_t base, uint64_t size, uint64_t address, uint64_t value)
{
    if (!word_range(base, size, address))
        return NDX_WORD_RANGE;
    if (value > UINT32_MAX)
        return NDX_WORD_VALUE;
    *(volatile uint32_t *)(uintptr_t)address = (uint32_t)value;
    return NDX_WORD_OK;
}

void ndx_word_release(void)
{
    __asm__ __volatile__("sfence" ::: "memory");
}

void ndx_word_acquire(void)
{
    __asm__ __volatile__("mfence" ::: "memory");
}
