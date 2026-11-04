// NDX12 adaptation (SORT-FFX-012 stage 3) of FidelityFX ParallelSort sample ParallelSortCS.hlsl @ 0c539948
// (MIT, ../upstream/LICENSE.txt): only the FPS_Scan entry point and its bindings. CBuffer stays in one
// 32-byte b0; ScanSrc/ScanDst/ScanScratch move from spaces 6/7/8 to u0/u1/u2 (ScanScratch is unused by
// FPS_Scan because AddPartialSums is false). FFX_ParallelSort.h is included byte-identical to upstream.
#define FFX_HLSL
#include "FFX-ParallelSort/FFX_ParallelSort.h"

cbuffer NDX12Constants : register(b0)
{
    FFX_ParallelSortCB CBuffer;     // 6 words
    uint ndx_reserved0;
    uint ndx_reserved1;
};

RWStructuredBuffer<uint> ScanSrc     : register(u0);   // was u0, space6
RWStructuredBuffer<uint> ScanDst     : register(u1);   // was u0, space7
RWStructuredBuffer<uint> ScanScratch : register(u2);   // was u0, space8

[numthreads(FFX_PARALLELSORT_THREADGROUP_SIZE, 1, 1)]
void FPS_Scan(uint localID : SV_GroupThreadID, uint groupID : SV_GroupID)
{
    uint BaseIndex = FFX_PARALLELSORT_ELEMENTS_PER_THREAD * FFX_PARALLELSORT_THREADGROUP_SIZE * groupID;
    FFX_ParallelSort_ScanPrefix(CBuffer.NumScanValues, localID, groupID, 0, BaseIndex, false,
                                CBuffer, ScanSrc, ScanDst, ScanScratch);
}
