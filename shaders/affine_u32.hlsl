// Original bounded shader fixture. Input is logically read-only despite UAV type.
RWStructuredBuffer<uint> Input : register(u0, space0);
RWStructuredBuffer<uint> Output : register(u1, space0);

cbuffer Parameters : register(b0, space0)
{
    uint Count;
    uint Seed;
    uint Multiplier;
    uint Addend;
    uint4 Reserved;
};

[numthreads(128, 1, 1)]
void main(uint3 tid : SV_DispatchThreadID)
{
    if (tid.x < Count)
        Output[tid.x] = (Input[tid.x] * Multiplier + Addend) ^ Seed;
}
