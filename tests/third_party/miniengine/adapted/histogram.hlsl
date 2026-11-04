//
// Copyright (c) Microsoft. All rights reserved.
// This code is licensed under the MIT License (MIT).
// THIS CODE IS PROVIDED *AS IS* WITHOUT WARRANTY OF
// ANY KIND, EITHER EXPRESS OR IMPLIED, INCLUDING ANY
// IMPLIED WARRANTIES OF FITNESS FOR A PARTICULAR
// PURPOSE, MERCHANTABILITY, OR NON-INFRINGEMENT.
//
// Developed by Minigraph
//
// Author:  James Stanard 
//
// The group size is 16x16, but one group iterates over an entire 16-wide column of pixels (384 pixels tall)
// Assuming the total workspace is 640x384, there will be 40 thread groups computing the histogram in parallel.
// The histogram measures logarithmic luminance ranging from 2^-12 up to 2^4.  This should provide a nice window
// where the exposure would range from 2^-4 up to 2^4.

// NDX12 adaptation (READYMADE-001): no textures/root signatures in the RTX adapter, so the
// luma texture becomes a UAV structured buffer indexed with an explicit width.
RWStructuredBuffer<uint> LumaBuf : register( u1 );
RWByteAddressBuffer Histogram : register( u0 );

groupshared uint g_TileHistogram[256];

cbuffer CB0 : register(b0)
{
    uint kBufferHeight;
    uint kBufferWidth;      // NDX12 adaptation: texture width
    uint kReserved0, kReserved1, kReserved2, kReserved3, kReserved4, kReserved5; // NDX12: b0 is 32 bytes
}

[numthreads( 16, 16, 1 )]
void main( uint GI : SV_GroupIndex, uint3 DTid : SV_DispatchThreadID )
{
    g_TileHistogram[GI] = 0;

    GroupMemoryBarrierWithGroupSync();

    // Loop until the entire column has been processed
    for (uint2 ST = DTid.xy; ST.y < kBufferHeight; ST.y += 16)
    {
        uint QuantizedLogLuma = LumaBuf[ST.y * kBufferWidth + ST.x];
        InterlockedAdd( g_TileHistogram[QuantizedLogLuma], 1 );
    }

    GroupMemoryBarrierWithGroupSync();

    Histogram.InterlockedAdd( GI * 4, g_TileHistogram[GI] );
}
