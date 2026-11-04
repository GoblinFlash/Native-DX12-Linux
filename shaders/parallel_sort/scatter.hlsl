// NDX12 adaptation (SORT-FFX-012 stage 5) of FidelityFX ParallelSort sample ParallelSortCS.hlsl @ 0c539948
// (MIT, ../upstream/LICENSE.txt): only the keys-only FPS_Scatter entry point (kRS_ValueCopy undefined) and its
// bindings. As in stage 1, CBuffer (b0) and the root constant CShiftBit (b2) share one 32-byte b0, and
// SrcBuffer/DstBuffer/SumTable move from spaces 0/4/2 to u0/u1/u2. FFX_ParallelSort.h is included
// byte-identical to upstream.
#define FFX_HLSL
#include "FFX-ParallelSort/FFX_ParallelSort.h"

cbuffer NDX12Constants : register(b0)
{
    FFX_ParallelSortCB CBuffer;     // 6 words
    uint CShiftBit;                 // was rootConstData.CShiftBit (b2)
    uint ndx_reserved0;
};

RWStructuredBuffer<uint> SrcBuffer : register(u0);   // was u0, space0
RWStructuredBuffer<uint> DstBuffer : register(u1);   // was u0, space4
RWStructuredBuffer<uint> SumTable  : register(u2);   // was u0, space2

[numthreads(FFX_PARALLELSORT_THREADGROUP_SIZE, 1, 1)]
void FPS_Scatter(uint localID : SV_GroupThreadID, uint groupID : SV_GroupID)
{
    FFX_ParallelSort_Scatter_uint(localID, groupID, CBuffer, CShiftBit, SrcBuffer, DstBuffer, SumTable);
}
