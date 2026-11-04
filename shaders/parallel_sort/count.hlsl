// NDX12 adaptation (SORT-FFX-012) of FidelityFX ParallelSort sample/src/Common/shaders/ParallelSortCS.hlsl
// @ 0c539948 (MIT, see ../upstream/LICENSE.txt). Only the FPS_Count entry point and its bindings:
// the RTX adapter admits one 32-byte b0 and UAVs u0..u2 in space 0, so CBuffer (b0) and the root
// constant CShiftBit (b2) share b0, and SrcBuffer/SumTable move from spaces 0/2 to u0/u1.
// FFX_ParallelSort.h is included byte-identical to upstream.
#define FFX_HLSL
#include "FFX-ParallelSort/FFX_ParallelSort.h"

cbuffer NDX12Constants : register(b0)
{
    FFX_ParallelSortCB CBuffer;     // 6 words
    uint CShiftBit;                 // was rootConstData.CShiftBit (b2)
    uint ndx_reserved0;
};

RWStructuredBuffer<uint> SrcBuffer : register(u0);   // was u0, space0
RWStructuredBuffer<uint> SumTable  : register(u1);   // was u0, space2

[numthreads(FFX_PARALLELSORT_THREADGROUP_SIZE, 1, 1)]
void FPS_Count(uint localID : SV_GroupThreadID, uint groupID : SV_GroupID)
{
    // Call the uint version of the count part of the algorithm
    FFX_ParallelSort_Count_uint(localID, groupID, CBuffer, CShiftBit, SrcBuffer, SumTable);
}
