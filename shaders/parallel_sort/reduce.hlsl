// NDX12 adaptation (SORT-FFX-012 stage 2) of FidelityFX ParallelSort sample ParallelSortCS.hlsl @ 0c539948
// (MIT, ../upstream/LICENSE.txt): only the FPS_CountReduce entry point and its bindings. CBuffer (b0)
// stays b0 inside one 32-byte block; SumTable/ReduceTable move from spaces 2/3 to u0/u1.
// FFX_ParallelSort.h is included byte-identical to upstream.
#define FFX_HLSL
#include "FFX-ParallelSort/FFX_ParallelSort.h"

cbuffer NDX12Constants : register(b0)
{
    FFX_ParallelSortCB CBuffer;     // 6 words
    uint ndx_reserved0;             // CShiftBit slot, unused by this kernel
    uint ndx_reserved1;
};

RWStructuredBuffer<uint> SumTable    : register(u0);   // was u0, space2
RWStructuredBuffer<uint> ReduceTable : register(u1);   // was u0, space3

[numthreads(FFX_PARALLELSORT_THREADGROUP_SIZE, 1, 1)]
void FPS_CountReduce(uint localID : SV_GroupThreadID, uint groupID : SV_GroupID)
{
    // Call the reduce part of the algorithm
    FFX_ParallelSort_ReduceCount(localID, groupID, CBuffer, SumTable, ReduceTable);
}
