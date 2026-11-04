#ifndef NDX12_GALLIUM_PROBE_H
#define NDX12_GALLIUM_PROBE_H

#include <stdbool.h>
#include <stdio.h>

struct pipe_screen;
struct pipe_context;

void require(bool ok, const char *message);
FILE *artifact(const char *prefix, const char *suffix, const char *mode);
void snapshot(const char *prefix, const char *phase);
int m0b_run(struct pipe_screen *screen, struct pipe_context *ctx, const char *mode,
            const char *prefix, unsigned seed, unsigned variant, const char *action);

#endif
