// NDX12 adaptation (SORT-FFX-012 stage 4) of FidelityFX ParallelSort sample ParallelSortCS.hlsl @ 0c539948
// (MIT, ../upstream/LICENSE.txt): only the FPS_ScanAdd entry point and its bindings. CBuffer stays in one
// 32-byte b0; ScanSrc/ScanDst/ScanScratch move from spaces 6/7/8 to u0/u1/u2. The entry body is copied
// verbatim from upstream. FFX_ParallelSort.h is included byte-identical to upstream.
#define FFX_HLSL
#include "FFX-ParallelSort/FFX_ParallelSort.h"

cbuffer NDX12Constants : register(b0)
{
    FFX_ParallelSortCB CBuffer;     // 6 words
    uint ndx_reserved0;
    uint ndx_reserved1;
};

RWStructuredBuffer<uint> ScanSrc     : register(u0);   // was u0, space6 (SumTable)
RWStructuredBuffer<uint> ScanDst     : register(u1);   // was u0, space7 (SumTable, scanned)
RWStructuredBuffer<uint> ScanScratch : register(u2);   // was u0, space8 (scanned ReduceTable)

[numthreads(FFX_PARALLELSORT_THREADGROUP_SIZE, 1, 1)]
void FPS_ScanAdd(uint localID : SV_GroupThreadID, uint groupID : SV_GroupID)
{
    // When doing adds, we need to access data differently because reduce
    // has a more specialized access pattern to match optimized count
    // Access needs to be done similarly to reduce
    // Figure out what bin data we are reducing
    uint BinID = groupID / CBuffer.NumReduceThreadgroupPerBin;
    uint BinOffset = BinID * CBuffer.NumThreadGroups;

    // Get the base index for this thread group
    uint BaseIndex = (groupID % CBuffer.NumReduceThreadgroupPerBin) * FFX_PARALLELSORT_ELEMENTS_PER_THREAD * FFX_PARALLELSORT_THREADGROUP_SIZE;

    FFX_ParallelSort_ScanPrefix(CBuffer.NumThreadGroups, localID, groupID, BinOffset, BaseIndex, true,
                                CBuffer, ScanSrc, ScanDst, ScanScratch);
}
