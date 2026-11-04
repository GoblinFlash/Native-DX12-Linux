#ifndef NDX_CPU_INSPECT_H
#define NDX_CPU_INSPECT_H
#include "compiler/nir/nir.h"
/* Test-only: 32 sentinel words, 1024 payload words, 32 sentinel words.
 * Run 1088 logical invocations to exercise shader bounds as well as full data. */
int inspect_nir(nir_shader *, uint32_t output[1088], unsigned *stores);
#endif
